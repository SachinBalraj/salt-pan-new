from __future__ import annotations

import datetime as dt
from typing import List, Optional

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import ModelVersion, Pan, Prediction, WeatherReading
from app.schemas import PredictRequest
from app.services.digital_twin import get_twin_state, latest_forecast_days, record_state
from app.services.predictor import day0_features, local_shap_values, scored_timeline
from app.services.serializers import (
    make_prediction_row,
    prediction_record_to_dict,
    prediction_run_to_dict,
)
from app.services.weather_provider import weather_provider

router = APIRouter(prefix="/api/predictions", tags=["predictions"])


def latest_model(db: Session, kind: str) -> ModelVersion:
    m = (db.query(ModelVersion)
         .filter(ModelVersion.model_type == kind)
         .order_by(ModelVersion.active.desc(), ModelVersion.created_at.desc())
         .first())
    if not m:
        from app.services.seeding import seed_all
        seed_all(db)
        m = (db.query(ModelVersion)
             .filter(ModelVersion.model_type == kind)
             .order_by(ModelVersion.active.desc(), ModelVersion.created_at.desc())
             .first())
    if not m:
        raise HTTPException(400, f"No {kind} model available. Train or seed the demo first.")
    return m


def persist_forecast(db: Session, pan: Optional[Pan], days: list, source: str) -> None:
    gen_at = dt.datetime.utcnow()
    for day in days:
        db.add(WeatherReading(
            pan_id=pan.id if pan else None,
            forecast_generated_at=gen_at,
            forecast_for=_parse_date(day.get("date")),
            forecast_rain_mm=float(day.get("rainfall_mm", 0.0)),
            rain_probability_pct=float(day.get("precipitation_probability_pct", 0.0)),
            temperature_c=float(day.get("temperature_c", 0.0)),
            humidity_pct=float(day.get("humidity_pct", 0.0)),
            wind_speed_ms=round(float(day.get("wind_speed_kmh", 0.0)) / 3.6, 2),
            solar_radiation_wm2=round(float(day.get("sunshine_hours", 0.0)) * 100.0, 1),
            cloud_cover_pct=round(max(0.0, 100.0 - float(day.get("sunshine_hours", 0.0)) * 8.0), 1),
            source=source,
        ))
    db.commit()


def _parse_date(value) -> Optional[dt.date]:
    try:
        return dt.date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _cached_days(db: Session, pan: Pan, days: int) -> Optional[list]:
    cached = latest_forecast_days(db, pan, days)
    if len(cached) >= days:
        return cached
    return None


def coherent_forecast(db: Session, pan: Pan, days: int) -> list:
    """Demo pans (with demo_today) get a seasonal mock forecast matching their
    twin timeline; live pans get a real forecast with mock fallback."""
    state = get_twin_state(db, pan)
    demo_today = state.get("demo_today")
    if demo_today:
        start = dt.date.fromisoformat(str(demo_today))
        result = weather_provider.get_forecast(pan.latitude, pan.longitude,
                                               start=start, days=days, source="mock")
        persist_forecast(db, pan, list(result["days"]), source=str(result["source"]))
        return list(result["days"])

    cached = _cached_days(db, pan, days)
    if cached:
        return cached
    result = weather_provider.get_forecast(pan.latitude, pan.longitude,
                                           start=dt.date.today(), days=days)
    persist_forecast(db, pan, list(result["days"]), source=str(result["source"]))
    return list(result["days"])


def resolve_forecast(db: Session, pan: Pan, horizon_days: int) -> List[dict]:
    return coherent_forecast(db, pan, horizon_days)


def load_models(db: Session, settings):
    from app.ml.model_store import load_model

    models = {}
    model_versions = {}
    for kind in ("harvest_readiness", "climate_risk"):
        m = latest_model(db, kind)
        try:
            models[kind] = load_model(kind, settings.models_path, version=m.version)["model"]
        except FileNotFoundError as exc:
            raise HTTPException(400, f"Missing artifact for {kind}. Retrain the model.") from exc
        model_versions[kind] = m
    return models, model_versions


@router.post("/run")
def run_prediction(body: PredictRequest, db: Session = Depends(get_db)):
    settings = get_settings()
    pan = db.get(Pan, body.pan_id)
    if not pan:
        raise HTTPException(404, "Salt pan not found")

    # Phase 6: no active model, no prediction. A last-resort demo seed (only
    # possible on a completely empty DB) keeps the classic demo workflow intact.
    active = db.query(ModelVersion).filter(ModelVersion.active.is_(True)).first()
    if not active:
        from app.services.seeding import seed_all
        seed_all(db)
        active = db.query(ModelVersion).filter(ModelVersion.active.is_(True)).first()
    if not active:
        raise HTTPException(
            409, "No active model available. Train a model (POST /api/models/train) first.")

    forecast_days = resolve_forecast(db, pan, body.horizon_days)
    models, model_versions = load_models(db, settings)
    state = get_twin_state(db, pan)

    start_date = state.get("demo_today") or dt.date.today().isoformat()
    timeline = scored_timeline(state, forecast_days, models, start_date=start_date)

    shap = {}
    for kind in ("harvest_readiness", "climate_risk"):
        fd = day0_features(state, forecast_days, kind)
        shap[kind] = local_shap_values(models[kind], list(fd.values()), list(fd.keys()))

    pred = make_prediction_row(
        db, pan,
        state=state,
        series=timeline,
        models=models,
        shap=shap,
        scenario=body.scenario,
        horizon_days=body.horizon_days,
        model_version=model_versions["harvest_readiness"],
    )
    db.add(pred)
    db.flush()
    record_state(db, pan, state, source="prediction",
                 forecast_days=forecast_days,
                 readiness=float(timeline[0]["readiness"]),
                 risk=max(float(p["risk"]) for p in timeline))
    db.commit()
    db.refresh(pred)
    return prediction_run_to_dict(pred, pan)


@router.get("")
def list_predictions(pan_id: Optional[int] = None, limit: int = 50, db: Session = Depends(get_db)):
    q = db.query(Prediction).order_by(Prediction.created_at.desc())
    if pan_id:
        q = q.filter(Prediction.pan_id == pan_id)
    return [prediction_record_to_dict(p) for p in q.limit(limit).all()]


@router.get("/{prediction_id}")
def get_prediction(prediction_id: int, db: Session = Depends(get_db)):
    p = db.get(Prediction, prediction_id)
    if not p:
        raise HTTPException(404, "Prediction not found")
    return prediction_record_to_dict(p)