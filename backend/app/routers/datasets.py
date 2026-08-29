from __future__ import annotations

import os
import re
import uuid
from typing import Dict, List

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import DataSet
from app.schemas import DataSetOut, DataSetPreview
from app.services.dataset_validator import validate_dataset

router = APIRouter(prefix="/api/datasets", tags=["datasets"])

ALLOWED_EXTS = {".csv", ".tsv"}
MAX_UPLOAD_FIRST_BYTES = 1024 * 1024  # we only sniff; full file read later


def _safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


@router.post("/upload", response_model=DataSetOut, status_code=201)
async def upload_dataset(
    file: UploadFile = File(..., description="CSV/TSV salt-pan dataset"),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(400, f"Unsupported file type '{ext}'. Upload a .csv or .tsv file.")

    content = await file.read()
    if not content:
        raise HTTPException(400, "Empty file.")

    name = _safe_filename(os.path.splitext(file.filename or "dataset")[0])
    stored_name = f"{uuid.uuid4().hex[:8]}_{_safe_filename(file.filename or 'dataset.csv')}"
    destination = settings.raw_data_path / stored_name
    destination.write_bytes(content)

    try:
        if ext == ".tsv":
            df = pd.read_csv(destination, sep="\t")
        else:
            df = pd.read_csv(destination)
    except Exception as exc:
        raise HTTPException(400, f"Could not parse dataset: {exc}") from exc

    report = validate_dataset(df)

    dataset = DataSet(
        name=name,
        filename=file.filename or stored_name,
        filepath=str(destination),
        rows_count=int(len(df)),
        columns=list(df.columns),
        status="valid" if report["valid"] else "invalid",
        validation_report=report,
        source="upload",
    )
    db.add(dataset)
    db.commit()
    db.refresh(dataset)
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


@router.get("/{dataset_id}/preview", response_model=DataSetPreview)
def preview_dataset(dataset_id: int, n: int = 10, db: Session = Depends(get_db)):
    ds = db.get(DataSet, dataset_id)
    if not ds:
        raise HTTPException(404, "Dataset not found")
    try:
        df = pd.read_csv(ds.filepath)
    except Exception as exc:
        raise HTTPException(400, f"Cannot read stored dataset: {exc}") from exc
    return DataSetPreview(
        columns=list(df.columns),
        rows=df.head(max(1, min(n, 50))).to_dict(orient="records"),
    )


@router.post("/{dataset_id}/validate", response_model=DataSetOut)
def revalidate_dataset(dataset_id: int, db: Session = Depends(get_db)):
    ds = db.get(DataSet, dataset_id)
    if not ds:
        raise HTTPException(404, "Dataset not found")
    try:
        df = pd.read_csv(ds.filepath)
    except Exception as exc:
        raise HTTPException(400, f"Cannot read stored dataset: {exc}") from exc
    report = validate_dataset(df)
    ds.validation_report = report
    ds.status = "valid" if report["valid"] else "invalid"
    db.commit()
    db.refresh(ds)
    return ds


@router.post("/{dataset_id}/promote", response_model=DataSetOut)
def promote_dataset(dataset_id: int, db: Session = Depends(get_db)):
    """Promote this dataset to be the active training source."""
    ds = db.get(DataSet, dataset_id)
    if not ds:
        raise HTTPException(404, "Dataset not found")
    if not os.path.exists(ds.filepath):
        raise HTTPException(400, "Stored dataset file is missing")
    settings = get_settings()
    training_path = settings.processed_data_path / "training.csv"
    df = pd.read_csv(ds.filepath)
    df.to_csv(training_path, index=False)
    ds.status = "promoted"
    ds.validation_report = {**(ds.validation_report or {}),
                            "promoted_to": str(training_path)}
    db.commit()
    db.refresh(ds)
    return ds


@router.get("/{dataset_id}/file")
def dataset_file(dataset_id: int, db: Session = Depends(get_db)):
    ds = db.get(DataSet, dataset_id)
    if not ds:
        raise HTTPException(404, "Dataset not found")
    if not os.path.exists(ds.filepath):
        raise HTTPException(404, "Stored file missing")
    return {"path": ds.filepath, "rows": ds.rows_count}