from __future__ import annotations

import json
from pathlib import Path
from typing import List

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import DataSet, ModelVersion
from app.schemas import LabelStatusOut, ModelOut, TrainRequest
from app.services.model_targets import resolve_targets
from app.services.proxy_labels import ensure_labels, labels_status_summary
from app.services.serializers import model_to_dict
from app.services.training import train_model

router = APIRouter(prefix="/api/models", tags=["ml models"])

ALL_KINDS = [
    "harvest_readiness",
    "climate_risk",
    "climate_risk_classifier",
    "harvest_readiness_classifier",
    "harvest_time_regressor",
]


@router.get("", response_model=List[ModelOut])
def list_models(db: Session = Depends(get_db)):
    return [model_to_dict(m, db) for m in db.query(ModelVersion)
            .order_by(ModelVersion.created_at.desc()).all()]


@router.get("/latest", response_model=List[ModelOut])
def latest_models(db: Session = Depends(get_db)):
    """Newest ModelVersion per kind, including deferred regressor rows."""
    rows = db.query(ModelVersion).order_by(
        ModelVersion.model_type, ModelVersion.created_at.asc()).all()
    by_kind: dict = {}
    for m in rows:
        if m.model_type == "harvest_time_regressor" and m.version == 0:
            by_kind.setdefault(m.model_type, m)
            continue
        prev = by_kind.get(m.model_type)
        if prev is None or m.id > prev.id:
            by_kind[m.model_type] = m
    ordered = sorted(by_kind.values(), key=lambda m: m.id)
    return [model_to_dict(m, db) for m in ordered]


@router.get("/label-status", response_model=LabelStatusOut)
def label_status(db: Session = Depends(get_db)):
    """Proxy vs field label provenance for registered models + warning banner."""
    models = db.query(ModelVersion).order_by(ModelVersion.created_at.desc()).all()
    return labels_status_summary(db_models=models)


@router.get("/{model_id}", response_model=ModelOut)
def get_model(model_id: int, db: Session = Depends(get_db)):
    m = db.get(ModelVersion, model_id)
    if not m:
        raise HTTPException(404, "Model not found")
    return model_to_dict(m, db)


@router.get("/{model_id}/shap")
def model_shap(model_id: int, db: Session = Depends(get_db)):
    m = db.get(ModelVersion, model_id)
    if not m:
        raise HTTPException(404, "Model not found")
    meta_path = Path(m.model_path).with_suffix(".meta.json") if m.model_path else None
    if meta_path and meta_path.exists():
        meta = json.loads(meta_path.read_text())
        return {"model_id": m.id, "kind": m.model_type,
                "shap_importance": meta.get("shap_importance", [])}
    return {"model_id": m.id, "kind": m.model_type, "shap_importance": []}


@router.post("/{model_id}/activate", response_model=ModelOut)
def activate_model(model_id: int, db: Session = Depends(get_db)):
    m = db.get(ModelVersion, model_id)
    if not m:
        raise HTTPException(404, "Model not found")
    if m.version == 0:
        raise HTTPException(400,
                            "Cannot activate a deferred model (no trained artefact).")
    db.query(ModelVersion).filter(
        ModelVersion.model_type == m.model_type,
        ModelVersion.id != m.id,
    ).update({ModelVersion.active: False})
    m.active = True
    db.commit()
    db.refresh(m)
    return model_to_dict(m, db)


@router.post("/train", response_model=List[ModelOut], status_code=201)
def train(body: TrainRequest, db: Session = Depends(get_db)):
    settings = get_settings()
    if body.kind not in (ALL_KINDS + ["all"]):
        raise HTTPException(400, f"kind must be one of {ALL_KINDS + ['all']}")
    kinds = ALL_KINDS if body.kind == "all" else [body.kind]

    df: pd.DataFrame | None = None
    ds: DataSet | None = None
    if body.dataset_id:
        ds = db.get(DataSet, body.dataset_id)
        if not ds:
            raise HTTPException(404, "Dataset not found")
        df = pd.read_csv(ds.filepath)
    else:
        ds = db.query(DataSet).filter(DataSet.status == "promoted").order_by(
            DataSet.created_at.desc()).first()
        if not ds:
            ds = db.query(DataSet).order_by(DataSet.created_at.desc()).first()
        if not ds:
            raise HTTPException(400, "No dataset available. Upload one or re-seed the demo.")
        df = pd.read_csv(ds.filepath)

    # Phase 5: resolve missing real labels (field values kept, proxy synthesised
    # and documented). Phase 6: resolve supervised targets (risk_level /
    # harvest_ready / verified hours_to_harvest) on the labelled frame.
    from app.config.proxy_labels import get_proxy_labels_config

    label_report = None
    target_report = None
    try:
        df, label_report = ensure_labels(df, get_proxy_labels_config(),
                                         dataset_source=ds.source)
        df, target_report = resolve_targets(df, label_report,
                                            dataset_source=ds.source)
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(400, f"Label preparation failed: {exc}") from exc

    created: List[ModelVersion] = []
    for kind in kinds:
        try:
            trained = train_model(kind, df, ds.id, settings.models_path,
                                  labels_report=label_report,
                                  target_report=target_report,
                                  dataset_name=ds.name)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        split = trained.get("split") or {}
        trs, tre = split.get("train_dates") or [None, None]
        mv = ModelVersion(
            model_name=trained["model_name"],
            model_type=kind,
            algorithm=trained.get("algorithm", ""),
            target_column=trained.get("target", ""),
            version=trained["version"],
            model_path=trained["artifact_path"],
            training_rows=int(trained["rows_trained"]),
            test_rows=int(trained.get("test_rows", 0)),
            training_start_date=trs,
            training_end_date=tre,
            split_json=split,
            metrics_json=trained["metrics"],
            feature_names_json=trained["feature_names"],
            uses_proxy_labels=bool(trained["uses_proxy_labels"]),
            training_errors_json=trained.get("training_errors", []),
            dataset_id=ds.id,
            active=bool(trained["version"] and trained["status"] == "trained"),
        )
        db.add(mv)
        created.append(mv)
    db.commit()
    for m in created:
        db.refresh(m)
    return [model_to_dict(m, db) for m in created]