from __future__ import annotations

import datetime as dt
import math

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import Prediction, SaltPan, WeatherForecast
from app.schemas import SimulationRequest
from app.services.predictor import scored_timeline
from app.services.weather_provider import weather_provider

router = APIRouter(prefix="/api/simulations", tags=["simulations"])

SALT_BULK_KG_M3 = 1200.0


def _forecast_days(db: Session, pan: SaltPan, days: int) -> tuple:
    from app.routers.predictions import coherent_forecast

    data = coherent_forecast(db, pan, days)
    src = "mock" if pan.twin_state.get("demo_today") else "open_meteo/mock"
    return data, src


def _models(db: Session, settings):
    from app.ml.model_store import load_model
    from app.routers.predictions import latest_model

    models = {}
    for kind in ("harvest_readiness", "climate_risk"):
        m = latest_model(db, kind)
        models[kind] = load_model(kind, settings.models_path, version=m.version)["model"]
    return models


@router.post("/what-if-rain")
def what_if_rain(body: SimulationRequest, db: Session = Depends(get_db)):
    settings = get_settings()
    pan = db.get(SaltPan, body.pan_id)
    if not pan:
        raise HTTPException(404, "Salt pan not found")

    horizon = body.horizon_days
    forecast_days, source = _forecast_days(db, pan, horizon)
    rain_days = weather_provider.simulate_rain(
        forecast_days,
        rainfall_mm=body.scenario.rainfall_mm,
        day_offset=body.scenario.day_offset,
        dry_days_after=body.scenario.dry_days_after,
    )
    models = _models(db, settings)
    start_date = pan.twin_state.get("demo_today") or dt.date.today().isoformat()

    baseline = scored_timeline(pan, forecast_days, models, start_date=start_date)
    rain_timeline = scored_timeline(pan, rain_days, models, start_date=start_date)

    # ---- impact analysis ------------------------------------------------
    event_idx = min(body.scenario.day_offset, horizon - 1)
    base_on_event = baseline[event_idx]
    rain_on_event = rain_timeline[event_idx]
    impact_day = max((p for p in rain_timeline if p["rainfall_mm"] > 0.5), key=lambda p: p["rainfall_mm"],
                     default=rain_timeline[event_idx]) if any(p["rainfall_mm"] > 0.5 for p in rain_timeline) \
        else rain_timeline[event_idx]

    readiness_drop = round(max(0.0, base_on_event["readiness"] - rain_on_event["readiness"]), 4)
    thick_drop = round(max(0.0, base_on_event["salt_thickness_mm"] - rain_on_event["salt_thickness_mm"]), 2)
    density_drop = round(max(0.0, base_on_event["brine_density_be"] - rain_on_event["brine_density_be"]), 2)

    dissolved_thickness = thick_drop
    yield_loss_kg = round(dissolved_thickness / 1000.0 * SALT_BULK_KG_M3 * pan.area_m2, 1)
    # Recovery takes ~0.9 mm of deposit per fully dry day near saturation.
    deposit_rate_mm_day = 0.9
    days_setback = int(math.ceil(max(0.0, dissolved_thickness) / deposit_rate_mm_day))
    latest_base = baseline[-1]
    latest_rain = rain_timeline[-1]
    if days_setback == 0 and latest_rain["readiness"] < latest_base["readiness"]:
        delta = latest_base["readiness"] - latest_rain["readiness"]
        days_setback = int(math.ceil(delta / max(0.05, 0.06)))

    rain_days_count = sum(1 for p in rain_timeline if p["rainfall_mm"] > 1.0)

    max_risk_base = max(p["risk"] for p in baseline)
    max_risk_rain = max(p["risk"] for p in rain_timeline)

    impact = {
        "rainfall_mm": body.scenario.rainfall_mm,
        "rain_day": impact_day["date"],
        "readiness_drop_on_day": readiness_drop,
        "max_risk_baseline": round(max_risk_base, 4),
        "max_risk_after_rain": round(max_risk_rain, 4),
        "risk_increase": round(max(0.0, max_risk_rain - max_risk_base), 4),
        "brine_density_drop_be": density_drop,
        "salt_thickness_loss_mm": thick_drop,
        "projected_yield_loss_kg": yield_loss_kg,
        "days_setback_estimate": days_setback,
        "readiness_before": base_on_event["readiness"],
        "readiness_after": rain_on_event["readiness"],
        "event_date": rain_on_event["date"],
        "risk_critical": max_risk_rain > 0.65,
    }

    # Persist the rain scenario as an auditable prediction.
    db.add(Prediction(
        pan_id=pan.id,
        prediction_type="combined",
        scenario="rain_simulation",
        score=float(rain_timeline[0]["readiness"]),
        horizon_days=horizon,
        prediction_date=dt.date.today().isoformat(),
        forecast_date=start_date,
        features={**impact},
        series=rain_timeline,
    ))
    db.commit()

    return {
        "pan_id": pan.id,
        "pan_ref": pan.pan_id,
        "scenario_name": f"What if {body.scenario.rainfall_mm} mm rain on day "
                         f"{body.scenario.day_offset + 1}?",
        "forecast_source": source,
        "baseline": baseline,
        "rain_scenario": rain_timeline,
        "impact": impact,
        "days": rain_days,
    }