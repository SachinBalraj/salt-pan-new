from __future__ import annotations

import datetime as dt
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ModelVersion, Pan, Recommendation, SensorReading
from app.schemas import DigitalTwinOut, SensorIngestOut, SensorReadingCreate
from app.services.digital_twin import (
    apply_reading_to_state,
    get_twin_state,
    record_state,
    twin_summary,
)
from app.services.predictor import day0_features, local_shap_values, scored_timeline
from app.services.recommendation_engine import generate_recommendations
from app.services.serializers import (
    make_prediction_row,
    prediction_run_to_dict,
    recommendation_to_dict,
)

router = APIRouter(prefix="/api/sensors", tags=["sensor readings"])


def _resolve_pan(db: Session, body: SensorReadingCreate) -> Pan:
    pan = None
    if body.pan_id is not None:
        pan = db.get(Pan, body.pan_id)
    elif body.pan_code:
        pan = db.query(Pan).filter(Pan.pan_code == body.pan_code).first()
    if not pan:
        raise HTTPException(404, "Salt pan not found")
    return pan


def _save_reading(db: Session, pan: Pan, body: SensorReadingCreate) -> SensorReading:
    ts = dt.datetime.utcnow()
    if body.recorded_at:
        try:
            parsed = dt.datetime.fromisoformat(body.recorded_at.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(dt.timezone.utc).replace(tzinfo=None)
            ts = parsed
        except ValueError:
            raise HTTPException(400, "recorded_at must be an ISO-8601 timestamp")
    reading = SensorReading(
        pan_id=pan.id,
        timestamp=ts,
        salinity_g_l=float(body.salinity_g_l or 0.0),
        ec_ms_cm=float(body.ec_ms_cm or 0.0),
        water_depth_cm=float(body.water_depth_cm or 0.0),
        brine_temperature_c=float(body.brine_temperature_c or 0.0),
        air_temperature_c=float(body.air_temperature_c or 0.0),
        humidity_pct=float(body.humidity_pct or 0.0),
        sensor_quality=float(body.sensor_quality or 100.0),
        source="in-situ_sensor",
    )
    db.add(reading)
    db.flush()
    return reading


def _expire_pending(db: Session, pan_id: int) -> None:
    (db.query(Recommendation)
     .filter(Recommendation.pan_id == pan_id,
             Recommendation.status == "pending")
     .update({"status": "expired"}, synchronize_session=False))


def _run_prediction(db: Session, pan: Pan, state: dict, forecast_days: list):
    """Scored readiness/risk timeline + SHAP, mirrored from /api/predictions/run."""
    from app.config import get_settings
    from app.routers.predictions import load_models

    settings = get_settings()
    models, model_versions = load_models(db, settings)
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
        scenario="sensor_triggered",
        horizon_days=len(forecast_days),
        model_version=model_versions["harvest_readiness"],
    )
    db.add(pred)
    db.flush()
    return pred, models, timeline, shap


def _refresh_recommendations(db: Session, pan: Pan, state: dict,
                             timeline: list, shap: dict, prediction):
    from app.routers.recommendations import _to_row

    _expire_pending(db, pan.id)
    new_recs: List[dict] = []
    for rec in generate_recommendations(state, timeline, shap=shap,
                                        prediction=prediction)[:3]:
        rec["_timeline"] = timeline
        row = _to_row(pan, prediction, rec)
        db.add(row)
        db.flush()
        new_recs.append(recommendation_to_dict(row))
    return new_recs


@router.post("/readings", response_model=SensorIngestOut, status_code=201)
def ingest_reading(body: SensorReadingCreate, db: Session = Depends(get_db)):
    """Pan-sensor taps, end to end:

    1. validate the reading (schema: range checks + pan reference),
    2. save the reading,
    3. resolve the latest weather forecast for the pan,
    4. update the digital twin with the measured state,
    5. run a prediction when an active model exists,
    6. refresh (generate-or-update) the pan's recommendations.
    """
    # 1 + 2. Validate + save
    pan = _resolve_pan(db, body)
    reading = _save_reading(db, pan, body)

    # 3. Latest forecast
    from app.routers.predictions import resolve_forecast

    forecast_days = resolve_forecast(db, pan, 7)

    # 4. Update the digital twin from the reading
    state = apply_reading_to_state(get_twin_state(db, pan), body)

    active = db.query(ModelVersion).filter(ModelVersion.active.is_(True)).first()
    pred = None
    recommendations: List[dict] = []
    if active:
        # 5. Prediction (scored timeline) + 6. generate/update recommendations
        pred, _models, timeline, shap = _run_prediction(db, pan, state, forecast_days)
        recommendations = _refresh_recommendations(db, pan, state, timeline, shap, pred)
        record_state(db, pan, state, source="sensor",
                     forecast_days=forecast_days,
                     readiness=float(timeline[0]["readiness"]),
                     risk=max(float(p["risk"]) for p in timeline))
    else:
        # No active model: telemetry still drives the twin.
        record_state(db, pan, state, source="sensor", forecast_days=forecast_days)

    db.commit()
    return SensorIngestOut(
        reading_id=reading.id,
        pan_id=pan.id,
        pan_ref=pan.pan_code,
        status="ok",
        digital_twin=twin_summary(db, pan, forecast_days=forecast_days),
        prediction=prediction_run_to_dict(pred, pan) if pred else None,
        recommendations=recommendations,
        active_model=active is not None,
    )