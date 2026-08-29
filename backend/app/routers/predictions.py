from __future__ import annotations

import datetime as dt
from typing import List, Optional

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import MLModel, Prediction, SaltPan, WeatherForecast
from app.schemas import PredictRequest
from app.services.predictor import day0_features, local_shap_values, scored_timeline
from app.services.weather_provider import weather_provider

router = APIRouter(prefix="/api/predictions", tags=["predictions"])


def latest_model(db: Session, kind: str) -> MLModel:
    m = (db.query(MLModel).filter(MLModel.kind == kind)
         .order_by(MLModel.created_at.desc()).first())
    if not m:
        from app.services.seeding import seed_all
        seed_all(db)
        m = (db.query(MLModel).filter(MLModel.kind == kind)
             .order_by(MLModel.created_at.desc()).first())
    if not m:
        raise HTTPException(400, f"No {kind} model available. Train or seed the demo first.")
    return m


def coherent_forecast(db: Session, pan: SaltPan, days: int) -> list:
    """Demo pans (with demo_today) get a seasonal mock forecast matching their
    twin timeline; live pans get a real forecast with mock fallback."""
    demo_today = pan.twin_state.get("demo_today")
    if demo_today:
        start = dt.date.fromisoformat(str(demo_today))
        result = weather_provider.get_forecast(pan.latitude, pan.longitude,
                                               start=start, days=days, source="mock")
        rec = WeatherForecast(pan_id=pan.id, source=str(result["source"]),
                              data=list(result["days"]))
        db.add(rec)
        db.commit()
        return list(result["days"])

    cached = (db.query(WeatherForecast)
              .filter(WeatherForecast.pan_id == pan.id, WeatherForecast.source != "simulation")
              .order_by(WeatherForecast.generated_at.desc()).first())
    if cached and len(cached.data) >= days:
        return cached.data[:days]
    result = weather_provider.get_forecast(pan.latitude, pan.longitude,
                                           start=dt.date.today(), days=days)
    rec = WeatherForecast(pan_id=pan.id, source=str(result["source"]), data=list(result["days"]))
    db.add(rec)
    db.commit()
    return rec.data


def resolve_forecast(db: Session, pan: SaltPan, horizon_days: int) -> List[dict]:
    return coherent_forecast(db, pan, horizon_days)


@router.post("/run")
def run_prediction(body: PredictRequest, db: Session = Depends(get_db)):
    settings = get_settings()
    pan = db.get(SaltPan, body.pan_id)
    if not pan:
        raise HTTPException(404, "Salt pan not found")

    forecast_days = resolve_forecast(db, pan, body.horizon_days)
    from app.ml.model_store import load_model

    models = {}
    for kind in ("harvest_readiness", "climate_risk"):
        m = latest_model(db, kind)
        try:
            models[kind] = load_model(kind, settings.models_path, version=m.version)["model"]
        except FileNotFoundError as exc:
            raise HTTPException(400, f"Missing artifact for {kind}. Retrain the model.") from exc

    start_date = pan.twin_state.get("demo_today") or dt.date.today().isoformat()
    timeline = scored_timeline(pan, forecast_days, models, start_date=start_date)

    day0 = timeline[0]
    max_risk = max(float(p["risk"]) for p in timeline)
    min_ready = min(float(p["readiness"]) for p in timeline)
    shap = {}
    for kind in ("harvest_readiness", "climate_risk"):
        fd = day0_features(pan, forecast_days, kind)
        shap[kind] = local_shap_values(models[kind], list(fd.values()), list(fd.keys()))

    proj_yield = round(pan.twin_state.get("estimated_salt_mass_kg", 0) or 0, 1)
    features = {**day0_features(pan, forecast_days, "harvest_readiness"),
                "projected_yield_kg": proj_yield,
                "max_risk_horizon": max_risk,
                "min_readiness_horizon": min_ready}

    pred = Prediction(
        pan_id=pan.id,
        prediction_type="combined",
        scenario=body.scenario,
        score=float(day0["readiness"]),
        horizon_days=body.horizon_days,
        prediction_date=dt.date.today().isoformat(),
        forecast_date=day0["date"],
        features=features,
        shap_values=shap,
        series=timeline,
    )
    db.add(pred)
    db.commit()
    db.refresh(pred)

    return {
        "id": pred.id,
        "pan_id": pan.id,
        "pan_ref": pan.pan_id,
        "state": pan.twin_state,
        "day0": day0,
        "max_risk": round(max_risk, 4),
        "min_readiness": round(min_ready, 4),
        "projected_yield_kg": proj_yield,
        "shap": shap,
        "series": timeline,
        "created_at": pred.created_at.isoformat(),
        "scenario": body.scenario,
    }


@router.get("")
def list_predictions(pan_id: Optional[int] = None, limit: int = 50, db: Session = Depends(get_db)):
    q = db.query(Prediction).order_by(Prediction.created_at.desc())
    if pan_id:
        q = q.filter(Prediction.pan_id == pan_id)
    return [{
        "id": p.id, "pan_id": p.pan_id, "model_id": p.model_id,
        "prediction_type": p.prediction_type, "scenario": p.scenario,
        "score": p.score, "horizon_days": p.horizon_days,
        "prediction_date": p.prediction_date, "forecast_date": p.forecast_date,
        "features": p.features, "shap_values": p.shap_values,
        "series": p.series, "created_at": p.created_at.isoformat(),
    } for p in q.limit(limit).all()]


@router.get("/{prediction_id}")
def get_prediction(prediction_id: int, db: Session = Depends(get_db)):
    p = db.get(Prediction, prediction_id)
    if not p:
        raise HTTPException(404, "Prediction not found")
    return {
        "id": p.id, "pan_id": p.pan_id, "model_id": p.model_id,
        "prediction_type": p.prediction_type, "scenario": p.scenario,
        "score": p.score, "horizon_days": p.horizon_days,
        "prediction_date": p.prediction_date, "forecast_date": p.forecast_date,
        "features": p.features, "shap_values": p.shap_values,
        "series": p.series, "created_at": p.created_at.isoformat(),
    }