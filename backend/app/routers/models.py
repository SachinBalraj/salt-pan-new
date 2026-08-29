from __future__ import annotations

import json
from pathlib import Path
from typing import List

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import DataSet, MLModel
from app.schemas import ModelOut, TrainRequest
from app.services.training import train_model

router = APIRouter(prefix="/api/models", tags=["ml models"])


@router.get("", response_model=List[ModelOut])
def list_models(db: Session = Depends(get_db)):
    return db.query(MLModel).order_by(MLModel.created_at.desc()).all()


@router.get("/{model_id}", response_model=ModelOut)
def get_model(model_id: int, db: Session = Depends(get_db)):
    m = db.get(MLModel, model_id)
    if not m:
        raise HTTPException(404, "Model not found")
    return m


@router.get("/{model_id}/shap")
def model_shap(model_id: int, db: Session = Depends(get_db)):
    m = db.get(MLModel, model_id)
    if not m:
        raise HTTPException(404, "Model not found")
    meta_path = Path(m.artifact_path).with_suffix(".meta.json") if m.artifact_path else None
    if meta_path and meta_path.exists():
        meta = json.loads(meta_path.read_text())
        return {"model_id": m.id, "kind": m.kind, "shap_importance": meta.get("shap_importance", [])}
    return {"model_id": m.id, "kind": m.kind, "shap_importance": []}


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

    created: List[MLModel] = []
    for kind in kinds:
        try:
            trained = train_model(kind, df, ds.id, settings.models_path)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        m = MLModel(
            name=trained["model_name"],
            kind=kind,
            version=trained["version"],
            status="trained",
            artifact_path=trained["artifact_path"],
            feature_names=trained["feature_names"],
            metrics=trained["metrics"],
            rows_trained=trained["rows_trained"],
            dataset_id=ds.id,
        )
        db.add(m)
        created.append(m)
    db.commit()
    for m in created:
        db.refresh(m)
    return created