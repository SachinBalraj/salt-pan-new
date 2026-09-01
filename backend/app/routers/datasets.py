from __future__ import annotations

import io
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.config import get_settings
from app.config.domain_thresholds import get_domain_thresholds, thresholds_signature
from app.database import get_db
from app.models import DataSet
from app.schemas import (
    DataSetOut,
    DataSetPreview,
    DatasetAnalysisOut,
    ImportOut,
    ThresholdOut,
    ThresholdsOut,
    UploadPreviewOut,
)
from app.services.dataset_validator import _legacy_report, validate_dataset
from app.services.ingestion import (
    REQUIRED_COLUMNS,
    analyze_dataframe_full,
    analyze_stored_file,
    import_rows,
    persist_artifacts,
    rejection_frame,
)

router = APIRouter(prefix="/api/datasets", tags=["datasets"])

ALLOWED_EXTS = {".csv", ".tsv"}
MAX_PREVIEW_ROWS = 50
_MAX_CSV_ROWS_HARD_LIMIT = 500_000  # safety cap to prevent memory exhaustion

TYPE_LABELS = {
    "sensor": "Pan sensor readings",
    "weather": "Weather / forecast data",
    "operations": "Operations + harvest outcomes",
    "combined": "Combined master dataset",
}


# ---------------------------------------------------------------------------
# Input sanitisation helpers
# ---------------------------------------------------------------------------
_STRIP_RE = re.compile(r"[<>\"'`;]")


def _sanitise_str(value: str, max_len: int = 256) -> str:
    """Strip potentially dangerous characters from user-supplied strings."""
    cleaned = _STRIP_RE.sub("", value.strip())
    return cleaned[:max_len]


def _safe_filename(name: str) -> str:
    """Only allow safe filename characters."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)[:120]


def _load_df(file_path) -> pd.DataFrame:
    try:
        kwargs = {"sep": "\t"} if str(file_path).lower().endswith(".tsv") else {}
        df = pd.read_csv(file_path, **kwargs)
    except Exception as exc:
        raise HTTPException(400, f"Could not parse dataset: {exc}") from exc
    if df.empty:
        raise HTTPException(400, "Empty dataframe — no rows to analyse.")
    if len(df) > _MAX_CSV_ROWS_HARD_LIMIT:
        raise HTTPException(
            400,
            f"Dataset exceeds maximum row limit ({_MAX_CSV_ROWS_HARD_LIMIT:,} rows). "
            "Please split the file into smaller chunks.",
        )
    return df


async def _read_upload(file: UploadFile) -> tuple[str, bytes]:
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(
            400,
            f"Unsupported file type '{ext}'. Only CSV (.csv) and TSV (.tsv) files are accepted.",
        )
    content = await file.read()
    if not content:
        raise HTTPException(400, "Empty file — no data to process.")

    # --- File-size limit (server-side enforcement) ---
    settings = get_settings()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            413,
            f"File too large: {len(content) / (1024 * 1024):.1f} MB exceeds "
            f"the {settings.max_upload_mb} MB limit. "
            "Split the dataset into smaller files.",
        )

    # --- Basic CSV-type validation: sniff the content ---
    first_chunk = content[:4096].decode("utf-8", errors="replace")
    sniff_sep = "\t" if ext == ".tsv" else ","
    lines = [l for l in first_chunk.split("\n") if l.strip()]
    if len(lines) < 1:
        raise HTTPException(400, "File appears to contain no data rows.")
    col_count = len(lines[0].split(sniff_sep))
    if col_count < 2:
        raise HTTPException(
            400,
            "File does not appear to be a valid CSV/TSV: "
            "the header row contains fewer than 2 columns.",
        )
    return ext, content


def _optional_field_mapping(raw: Optional[str]) -> Optional[Dict[str, str]]:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except ValueError:
        raise HTTPException(
            400,
            "field_mapping must be a valid JSON object like "
            '{"canonical_column": "header"}.',
        )
    if not isinstance(parsed, dict):
        raise HTTPException(400, "field_mapping must be a JSON object, not an array.")
    return {str(_sanitise_str(k)): str(v) for k, v in parsed.items()}


def _analysis_dto(analysis: Dict[str, Any], file_name: str) -> DatasetAnalysisOut:
    return DatasetAnalysisOut(
        file_name=file_name,
        dataset_type=analysis.get("dataset_type", ""),
        detection_confidence=float(analysis.get("detection_confidence", 0.0)),
        status=analysis.get("status", "invalid"),
        valid_rows=int(analysis.get("valid_rows", 0)),
        rejected_rows=int(analysis.get("rejected_rows", 0)),
        required_missing=list(analysis.get("required_missing", [])),
        unmapped=list(analysis.get("unmapped", [])),
        mappings=list(analysis.get("mappings", [])),
        renames=analysis.get("renames", {}),
        conversions=list(analysis.get("conversions", [])),
        duplicates=int((analysis.get("duplicates") or {}).get("count", 0)),
        quality=analysis.get("quality", {}),
    )


def _thresholds_dto(thresholds: Dict[str, Any]) -> ThresholdsOut:
    types = {}
    for key, required in REQUIRED_COLUMNS.items():
        types[key] = {
            "key": key,
            "label": TYPE_LABELS.get(key, key),
            "required": list(required),
            "optional": [],
        }
    thr_list: List[ThresholdOut] = []
    for dtype, spec in thresholds.items():
        if dtype not in REQUIRED_COLUMNS or not isinstance(spec, dict):
            continue
        for column, cfg in spec.items():
            if not isinstance(cfg, dict) or (cfg.get("min") is None and cfg.get("max") is None):
                continue
            thr_list.append(ThresholdOut(
                column=f"{dtype}.{column}",
                min=cfg.get("min"),
                max=cfg.get("max"),
                outlier_band=cfg.get("outlier_band"),
                unit=cfg.get("unit", "") if isinstance(cfg.get("unit", ""), str) else "",
                notes=cfg.get("note", ""),
            ))
    return ThresholdsOut(
        meta=thresholds.get("meta", {}),
        file=str(thresholds_signature()),
        types=types,
        aliases=thresholds.get("aliases", {}),
        unit_conversions=thresholds.get("unit_conversions", {}),
        thresholds=thr_list,
    )


@router.get("/thresholds", response_model=ThresholdsOut)
def dataset_thresholds():
    return _thresholds_dto(get_domain_thresholds())


@router.post("/preview", response_model=UploadPreviewOut)
async def preview_upload(
    file: UploadFile = File(..., description="CSV/TSV salt-pan dataset"),
    dataset_type: Optional[str] = Form(None, description="Force a dataset type"),
    field_mapping: Optional[str] = Form(None, description="JSON {canonical_column: header} overrides"),
):
    """Analyse an upload without persisting anything (dry-run review step)."""
    ext, content = await _read_upload(file)
    df = pd.read_csv(io.BytesIO(content),
                     sep="\t" if ext == ".tsv" else ",", on_bad_lines="skip")
    if df.empty:
        raise HTTPException(400, "Empty dataframe — no rows to analyse.")
    field_map = _optional_field_mapping(field_mapping)
    analysis, _ = analyze_dataframe_full(df, dataset_type, field_map)

    required = REQUIRED_COLUMNS[analysis["dataset_type"]]
    extra = [c for c in analysis.get("unmapped", [])]
    return UploadPreviewOut(
        file_name=file.filename or "",
        dataset_type=analysis["dataset_type"],
        detection_confidence=float(analysis.get("detection_confidence", 0.0)),
        required=list(required),
        missing=list(analysis.get("required_missing", [])),
        extra=extra,
        mappings=list(analysis.get("mappings", [])),
        renames=analysis.get("renames", {}),
        conversions=list(analysis.get("conversions", [])),
        duplicates=int((analysis.get("duplicates") or {}).get("count", 0)),
        sample_rows=analysis.get("quality", {}).get("valid_sample", []),
        errors=list(analysis.get("issues", {}).get("errors", [])),
        warnings=list(analysis.get("issues", {}).get("warnings", [])),
    )


@router.post("/upload", response_model=DataSetOut, status_code=201)
async def upload_dataset(
    file: UploadFile = File(..., description="CSV/TSV salt-pan dataset"),
    dataset_type: Optional[str] = Form(None, description="Force a dataset type"),
    field_mapping: Optional[str] = Form(None, description="JSON {canonical_column: header} overrides"),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    ext, content = await _read_upload(file)

    name = _safe_filename(os.path.splitext(file.filename or "dataset")[0])
    stored_name = f"{uuid.uuid4().hex[:8]}_{_safe_filename(file.filename or 'dataset.csv')}"
    destination = settings.raw_data_path / stored_name
    destination.write_bytes(content)

    df = _load_df(destination)
    if dataset_type:
        dataset_type = _sanitise_str(dataset_type, max_len=32)
    field_map = _optional_field_mapping(field_mapping)
    analysis, clean_df = analyze_dataframe_full(df, dataset_type, field_map)

    rejected = rejection_frame(clean_df, analysis)
    artifacts = persist_artifacts(destination, analysis, clean_df, rejected, list(clean_df.columns))

    # Wrap DB write in a transaction — rollback on any failure
    try:
        dataset = DataSet(
            name=name,
            filename=file.filename or stored_name,
            filepath=str(destination),
            rows_count=int(len(df)),
            columns=list(df.columns),
            dataset_type=analysis["dataset_type"],
            status=analysis["status"],
            validation_report={
                **_legacy_report(analysis),
                "analysis": analysis,
                "artifacts": artifacts,
            },
            source="upload",
        )
        db.add(dataset)
        db.commit()
        db.refresh(dataset)
    except Exception:
        db.rollback()
        raise HTTPException(500, "Failed to save dataset record. The file was stored but not registered.")
    return dataset


@router.get("", response_model=List[DataSetOut])
def list_datasets(db: Session = Depends(get_db)):
    return db.query(DataSet).order_by(DataSet.created_at.desc()).all()


@router.get("/{dataset_id}", response_model=DataSetOut)
def get_dataset(dataset_id: int, db: Session = Depends(get_db)):
    ds = db.get(DataSet, dataset_id)
    if not ds:
        raise HTTPException(404, "Dataset not found")
    return ds


@router.get("/{dataset_id}/analysis", response_model=DatasetAnalysisOut)
def get_dataset_analysis(dataset_id: int, db: Session = Depends(get_db)):
    ds = db.get(DataSet, dataset_id)
    if not ds:
        raise HTTPException(404, "Dataset not found")
    report = ds.validation_report or {}
    analysis = report.get("analysis") or (report if report.get("dataset_type") else None)
    if analysis:
        return _analysis_dto(analysis, ds.filename)
    try:
        analysis, _ = analyze_stored_file(ds.filepath)
    except Exception as exc:
        raise HTTPException(400, f"Cannot re-analyse stored dataset: {exc}") from exc
    return _analysis_dto(analysis, ds.filename)


@router.get("/{dataset_id}/preview", response_model=DataSetPreview)
def preview_dataset(dataset_id: int, n: int = 10, stage: str = "raw",
                    db: Session = Depends(get_db)):
    ds = db.get(DataSet, dataset_id)
    if not ds:
        raise HTTPException(404, "Dataset not found")
    try:
        if stage == "clean":
            _, clean_df = analyze_stored_file(ds.filepath)
            df = clean_df
        else:
            df = _load_df(ds.filepath)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, f"Cannot read stored dataset: {exc}") from exc
    return DataSetPreview(
        columns=list(df.columns),
        rows=df.head(max(1, min(n, MAX_PREVIEW_ROWS))).to_dict(orient="records"),
    )


@router.get("/{dataset_id}/invalid_rows")
def download_invalid_rows(dataset_id: int, db: Session = Depends(get_db)):
    ds = db.get(DataSet, dataset_id)
    if not ds:
        raise HTTPException(404, "Dataset not found")
    try:
        df = _load_df(ds.filepath)
    except HTTPException:
        raise
    analysis, clean_df = analyze_dataframe_full(df, ds.dataset_type)
    invalid = rejection_frame(clean_df, analysis)
    if invalid.empty:
        return Response(content="No invalid rows found.\n", media_type="text/plain")
    csv = io.StringIO()
    invalid.to_csv(csv, index=False)
    return Response(
        content=csv.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="invalid_rows_{dataset_id}.csv"'},
    )


@router.post("/{dataset_id}/import", response_model=ImportOut)
def import_dataset(
    dataset_id: int,
    dataset_type: Optional[str] = None,
    field_mapping: Optional[Dict[str, str]] = None,
    db: Session = Depends(get_db),
):
    """Explicit confirm: import validated rows into operational tables.

    Wrapped in a database transaction — either all rows import or none.
    """
    ds = db.get(DataSet, dataset_id)
    if not ds:
        raise HTTPException(404, "Dataset not found")
    try:
        df = _load_df(ds.filepath)
    except HTTPException:
        raise
    analysis, clean_df = analyze_dataframe_full(df, dataset_type or ds.dataset_type, field_mapping)
    if analysis["status"] == "invalid" or analysis["valid_rows"] == 0:
        raise HTTPException(400,
                            f"Cannot import: {analysis.get('valid_rows', 0)} valid rows "
                            f"(status '{analysis['status']}'). Fix the invalid rows first.")
    try:
        summary = import_rows(db, analysis, clean_df, ds.name)
        ds.dataset_type = analysis["dataset_type"]
        ds.status = "imported"
        ds.validation_report = {
            **_legacy_report(analysis),
            "analysis": analysis,
            "import_summary": summary,
        }
        db.commit()
        db.refresh(ds)
    except Exception:
        db.rollback()
        raise HTTPException(500, "Import failed — all changes have been rolled back.")
    return ImportOut(dataset=ds, summary=summary)


@router.post("/{dataset_id}/validate", response_model=DataSetOut)
def revalidate_dataset(dataset_id: int, db: Session = Depends(get_db)):
    ds = db.get(DataSet, dataset_id)
    if not ds:
        raise HTTPException(404, "Dataset not found")
    df = _load_df(ds.filepath)
    report = validate_dataset(df)
    ds.validation_report = report
    ds.status = "valid" if report["valid"] else "invalid"
    db.commit()
    db.refresh(ds)
    return ds


@router.post("/{dataset_id}/promote", response_model=DataSetOut)
def promote_dataset(dataset_id: int, db: Session = Depends(get_db)):
    """Promote this dataset to be the active training source (transactional)."""
    ds = db.get(DataSet, dataset_id)
    if not ds:
        raise HTTPException(404, "Dataset not found")
    if not os.path.exists(ds.filepath):
        raise HTTPException(400, "Stored dataset file is missing")
    settings = get_settings()
    training_path = settings.processed_data_path / "training.csv"
    try:
        df = _load_df(ds.filepath)
        df.to_csv(training_path, index=False)
        ds.status = "promoted"
        ds.validation_report = {**(ds.validation_report or {}),
                                "promoted_to": str(training_path)}
        db.commit()
        db.refresh(ds)
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise HTTPException(500, "Promotion failed — changes rolled back.")
    return ds


@router.get("/{dataset_id}/file")
def dataset_file(dataset_id: int, db: Session = Depends(get_db)):
    ds = db.get(DataSet, dataset_id)
    if not ds:
        raise HTTPException(404, "Dataset not found")
    if not os.path.exists(ds.filepath):
        raise HTTPException(404, "Stored file missing")
    return {"path": ds.filepath, "rows": ds.rows_count}