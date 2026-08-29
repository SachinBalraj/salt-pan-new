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
from app.schemas import ModelOut, TrainRequest
from app.services.serializers import model_to_dict
from app.services.training import train_model

router = APIRouter(prefix="/api/models", tags=["ml models"])


@router.get("", response_model=List[ModelOut])
def list_models(db: Session = Depends(get_db)):
    return [model_to_dict(m) for m in db.query(ModelVersion)
            .order_by(ModelVersion.created_at.desc()).all()]


@router.get("/{model_id}", response_model=ModelOut)
def get_model(model_id: int, db: Session = Depends(get_db)):
    m = db.get(ModelVersion, model_id)
    if not m:
        raise HTTPException(404, "Model not found")
    return model_to_dict(m)


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


@router.post("/train", response_model=List[ModelOut], status_code=201)
def train(body: TrainRequest, db: Session = Depends(get_db)):
    settings = get_settings()
    kinds = ["harvest_readiness", "climate_risk"] if body.kind == "all" else [body.kind]
    if body.kind not in ("all", "harvest_readiness", "climate_risk"):
        raise HTTPException(400, "kind must be 'harvest_readiness', 'climate_risk' or 'all'")

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

    created: List[ModelVersion] = []
    for kind in kinds:
        try:
            trained = train_model(kind, df, ds.id, settings.models_path)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        mv = ModelVersion(
            model_name=trained["model_name"],
            model_type=kind,
            version=trained["version"],
            model_path=trained["artifact_path"],
            training_rows=int(trained["rows_trained"]),
            metrics_json=trained["metrics"],
            feature_names_json=trained["feature_names"],
            uses_proxy_labels=True,
            active=True,
        )
        db.add(mv)
        created.append(mv)
    db.commit()
    for m in created:
        db.refresh(m)
    return [model_to_dict(m) for m in created]