from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

import pandas as pd
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import DataSet, MLModel, Prediction, Recommendation, SaltPan, WeatherForecast
from app.services.data_generator import REGIONS, dataset_to_file, generate_dataset, latest_pan_state
from app.services.weather_provider import weather_provider
from app.services.training import train_model
from app.services.predictor import scored_timeline, day0_features, local_shap_values
from app.services.recommendation_engine import generate_recommendations


def _find_dataset(db: Session, name_part: str) -> Optional[DataSet]:
    return db.query(DataSet).filter(DataSet.name.like(f"%{name_part}%")).first()


def _forecast_days_for(db: Session, pan: SaltPan, start: dt.date, days: int = 7) -> List[dict]:
    f = (db.query(WeatherForecast)
         .filter(WeatherForecast.pan_id == pan.id)
         .order_by(WeatherForecast.generated_at.desc())
         .first())
    if f and f.data:
        return f.data[:days]
    result = weather_provider.get_forecast(pan.latitude, pan.longitude,
                                           start=start, days=days, source="mock")
    db.add(WeatherForecast(pan_id=pan.id, source=str(result["source"]), data=list(result["days"])))
    return list(result["days"])


def seed_all(db: Session) -> dict:
    """Create a fully working demo on a fresh database."""
    settings = get_settings()
    if db.query(SaltPan).count() > 0:
        return {"already_seeded": True, "message": "Database already has salt pans."}

    # ---- 1. Dataset -----------------------------------------------------
    sample_path = settings.samples_path / "salt_pan_dataset.csv"
    if sample_path.exists():
        df = pd.read_csv(sample_path)
    else:
        df = generate_dataset()
        dataset_to_file(df, sample_path)

    training_path = settings.processed_data_path / "training.csv"
    dataset_to_file(df, training_path)

    demo_dates = pd.to_datetime(df["date"])
    demo_today = demo_dates.max().date() + dt.timedelta(days=1)

    dataset = DataSet(
        name="Pipeline sample (generated)",
        filename=sample_path.name,
        filepath=str(sample_path),
        rows_count=int(len(df)),
        columns=list(df.columns),
        status="valid",
        source="generated",
        validation_report={"note": "Auto-generated physically-plausible salt pan dataset.",
                           "date_range": [demo_dates.min().date().isoformat(),
                                          demo_dates.max().date().isoformat()]},
    )
    db.add(dataset)
    db.flush()
    dataset_id = dataset.id

    # ---- 2. Salt pans ----------------------------------------------------
    # Mid-season demo states so the dashboard shows a live, ready-to-work pan.
    DEMO_TWIN_STATES = {
        "PAN-1": {"brine_density_be": 26.5, "salt_thickness_mm": 11.5, "water_depth_cm": 8.0,
                  "days_since_last_rain": 6},
        "PAN-2": {"brine_density_be": 28.1, "salt_thickness_mm": 16.2, "water_depth_cm": 6.5,
                  "days_since_last_rain": 3},
        "PAN-3": {"brine_density_be": 21.4, "salt_thickness_mm": 3.2, "water_depth_cm": 12.0,
                  "days_since_last_rain": 9},
    }
    pans: Dict[str, SaltPan] = {}
    for pan_key, meta in REGIONS.items():
        twin = latest_pan_state(df, pan_key)
        twin.update(DEMO_TWIN_STATES.get(pan_key, {}))
        twin["estimated_salt_mass_kg"] = round(
            twin["salt_thickness_mm"] / 1000.0 * 1200.0 * meta["area_m2"], 1)
        twin["last_rain_date"] = (demo_today - dt.timedelta(days=twin["days_since_last_rain"])).isoformat()
        twin["demo_today"] = demo_today.isoformat()
        twin["last_update"] = demo_today.isoformat()
        pan = SaltPan(
            pan_id=pan_key,
            name=meta["name"],
            location=meta["location"],
            latitude=meta["lat"],
            longitude=meta["lon"],
            area_m2=meta["area_m2"],
            twin_state=twin,
        )
        db.add(pan)
        db.flush()
        # forecast
        forecast = weather_provider.get_forecast(pan.latitude, pan.longitude,
                                                 start=demo_today, days=7)
        db.add(WeatherForecast(pan_id=pan.id, source=str(forecast["source"]),
                               data=list(forecast["days"])))
        pans[pan_key] = pan

    # ---- 3. Train models ---------------------------------------------------
    model_records: Dict[str, MLModel] = {}
    for kind in ("harvest_readiness", "climate_risk"):
        trained = train_model(kind, df, dataset_id, settings.models_path)
        m = MLModel(
            name=trained["model_name"],
            kind=kind,
            version=trained["version"],
            status="trained",
            artifact_path=trained["artifact_path"],
            feature_names=trained["feature_names"],
            metrics=trained["metrics"],
            rows_trained=trained["rows_trained"],
            dataset_id=dataset_id,
        )
        db.add(m)
        db.flush()
        model_records[kind] = m
        db.commit()

    # ---- 4. First predictions + recommendations ----------------------------
    from app.ml.model_store import load_model

    loaded = {}
    for kind in ("harvest_readiness", "climate_risk"):
        payload = load_model(kind, settings.models_path)
        loaded[kind] = payload["model"]

    created_predictions = 0
    created_recommendations = 0
    for pan in pans.values():
        forecast_days = _forecast_days_for(db, pan, demo_today, 7)
        timeline = scored_timeline(pan, forecast_days, loaded, start_date=demo_today.isoformat())

        day0 = timeline[0]
        proj_yield = round(pan.twin_state["estimated_salt_mass_kg"] or 0.0, 1)
        shap = {}
        for kind in ("harvest_readiness", "climate_risk"):
            fd = day0_features(pan, forecast_days, kind)
            shap[kind] = local_shap_values(loaded[kind], list(fd.values()),
                                           list(fd.keys()))

        pred = Prediction(
            pan_id=pan.id,
            model_id=model_records["harvest_readiness"].id,
            prediction_type="combined",
            scenario="actual_forecast",
            score=float(day0["readiness"]),
            horizon_days=7,
            prediction_date=demo_today.isoformat(),
            forecast_date=day0["date"],
            features={**day0_features(pan, forecast_days, "harvest_readiness"),
                      "projected_yield_kg": proj_yield,
                      "max_risk_horizon": round(float(max(p["risk"] for p in timeline)), 4),
                      "min_readiness_horizon": round(float(min(p["readiness"] for p in timeline)), 4)},
            shap_values=shap,
            series=timeline,
        )
        db.add(pred)
        db.flush()
        created_predictions += 1

        recs = generate_recommendations(pan, timeline, shap=shap, prediction=pred)
        for rec in recs[:3]:
            db.add(Recommendation(
                pan_id=pan.id, prediction_id=pred.id,
                recommendation_type=rec["recommendation_type"],
                title=rec["title"], message=rec["message"],
                rationale=rec["rationale"], expected_benefit=rec["expected_benefit"],
                risk_level=rec["risk_level"],
            ))
            created_recommendations += 1
        pan.twin_state["last_update"] = demo_today.isoformat()

    db.commit()
    return {
        "already_seeded": False,
        "dataset_id": dataset_id,
        "rows": int(len(df)),
        "pans": len(pans),
        "models": list(model_records.keys()),
        "predictions": created_predictions,
        "recommendations": created_recommendations,
        "demo_today": demo_today.isoformat(),
        "message": "Demo seeded: dataset, pans, forecast, models, predictions & recommendations created.",
    }