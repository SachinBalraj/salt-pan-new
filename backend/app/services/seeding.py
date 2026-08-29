from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

import pandas as pd
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import DataSet, ModelVersion, Pan, SensorReading, WeatherReading
from app.services.data_generator import REGIONS, dataset_to_file, generate_dataset, latest_pan_state
from app.services.digital_twin import record_state, salt_mass_kg
from app.services.weather_provider import weather_provider


def _persist_forecast(db: Session, pan: Optional[Pan], days: list, source: str) -> None:
    from app.routers.predictions import persist_forecast

    persist_forecast(db, pan, days, source)


def _seed_sensors(db: Session, pan: Pan, state: dict, days: List[dict]) -> None:
    """A short synthetic in-situ sensor series anchored to the twin state."""
    import math

    area = float(pan.area_m2 or 1000.0)
    volume_l = max(state.get("water_depth_cm", 0.0), 0.0) / 100.0 * area * 1000.0
    for i, day in enumerate(days[:7]):
        drift = math.sin(i * 0.9)
        db.add(SensorReading(
            pan_id=pan.id,
            timestamp=dt.datetime.utcnow() - dt.timedelta(hours=6 * (7 - i)),
            salinity_g_l=round(max(0.0, float(state.get("brine_density_be", 0.0)) * 9.5 + drift), 1),
            ec_ms_cm=round(float(state.get("brine_density_be", 0.0)) * 15.0 + drift * 4.0, 1),
            water_depth_cm=round(float(state.get("water_depth_cm", 0.0)) + drift * 0.2, 2),
            brine_temperature_c=round(float(day.get("temperature_c", 28.0)) - 1.0, 1),
            air_temperature_c=round(float(day.get("temperature_c", 28.0)), 1),
            humidity_pct=round(float(day.get("humidity_pct", 60.0)), 1),
            sensor_quality=round(94.0 + drift * 3.0, 1),
            source="in-situ_sensor",
        ))
    db.flush()
    _ = volume_l


def seed_all(db: Session) -> dict:
    """Create a fully working demo on a fresh database."""
    settings = get_settings()
    if db.query(Pan).count() > 0:
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
    pans: Dict[str, Pan] = {}
    twins: Dict[str, dict] = {}
    for pan_key, meta in REGIONS.items():
        twin = latest_pan_state(df, pan_key)
        twin.update(DEMO_TWIN_STATES.get(pan_key, {}))
        twin["estimated_salt_mass_kg"] = salt_mass_kg(twin["salt_thickness_mm"], meta["area_m2"])
        twin["last_rain_date"] = (demo_today - dt.timedelta(days=twin["days_since_last_rain"])).isoformat()
        twin["demo_today"] = demo_today.isoformat()
        twin["location"] = meta["location"]
        twin["status"] = "active"
        twin["pan_area_m2"] = meta["area_m2"]
        pan = Pan(
            pan_code=pan_key,
            name=meta["name"],
            latitude=meta["lat"],
            longitude=meta["lon"],
            area_m2=meta["area_m2"],
            safe_depth_cm=12.0,
            safe_storage_available=True,
        )
        db.add(pan)
        db.flush()
        forecast = weather_provider.get_forecast(pan.latitude, pan.longitude,
                                                 start=demo_today, days=7)
        _persist_forecast(db, pan, list(forecast["days"]), source=str(forecast["source"]))
        _seed_sensors(db, pan, twin, list(forecast["days"]))
        pans[pan_key] = pan
        twins[pan_key] = twin

    # ---- 3. Train models ---------------------------------------------------
    from app.services.training import train_model

    model_records: Dict[str, ModelVersion] = {}
    for kind in ("harvest_readiness", "climate_risk"):
        trained = train_model(kind, df, dataset_id, settings.models_path)
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
        db.flush()
        model_records[kind] = mv

    # ---- 4. First predictions + recommendations ----------------------------
    from app.ml.model_store import load_model
    from app.services.predictor import day0_features, local_shap_values, scored_timeline
    from app.services.recommendation_engine import generate_recommendations
    from app.services.serializers import make_prediction_row

    loaded = {}
    for kind in ("harvest_readiness", "climate_risk"):
        loaded[kind] = load_model(kind, settings.models_path,
                                  version=model_records[kind].version)["model"]

    created_predictions = 0
    created_recommendations = 0
    for pan in pans.values():
        from app.services.digital_twin import latest_forecast_days

        state = dict(twins[pan.pan_code])
        forecast_days = latest_forecast_days(db, pan, 7) or []
        timeline = scored_timeline(state, forecast_days, loaded,
                                   start_date=demo_today.isoformat())

        shap = {}
        for kind in ("harvest_readiness", "climate_risk"):
            fd = day0_features(state, forecast_days, kind)
            shap[kind] = local_shap_values(loaded[kind], list(fd.values()), list(fd.keys()))

        pred = make_prediction_row(
            db, pan,
            state=state,
            series=timeline,
            models=loaded,
            shap=shap,
            scenario="actual_forecast",
            horizon_days=7,
            model_version=model_records["harvest_readiness"],
        )
        db.add(pred)
        db.flush()
        created_predictions += 1

        recs = generate_recommendations(state, timeline, shap=shap, prediction=pred)
        for rec in recs[:3]:
            from app.routers.recommendations import _to_row

            rec["_timeline"] = timeline
            db.add(_to_row(pan, pred, rec))
            created_recommendations += 1

        record_state(db, pan, state, source="seed",
                     forecast_days=forecast_days,
                     readiness=float(timeline[0]["readiness"]),
                     risk=max(float(p["risk"]) for p in timeline))

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


def _find_dataset(db: Session, name_part: str) -> Optional[DataSet]:
    return db.query(DataSet).filter(DataSet.name.like(f"%{name_part}%")).first()