from __future__ import annotations

import datetime as dt
import math
import uuid
from typing import Dict, List, Optional

import pandas as pd
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    DataSet,
    HarvestOutcome,
    ModelVersion,
    OperationEvent,
    Pan,
    Recommendation,
    SensorReading,
    WeatherReading,
)
from app.services.data_generator import REGIONS, dataset_to_file, generate_dataset, latest_pan_state
from app.services.digital_twin import record_state, salt_mass_kg
from app.services.weather_provider import weather_provider


# The three demo salt pans surfaced in the application. PAN-03 is the compact
# flagship panel used for the published "Harvest now" example (500 m², 245 g/L).
DEMO_PAN_KEYS = ("PAN-1", "PAN-2", "PAN-03")

# --------------------------------------------------------------------------- #
# Phase 14: reproducible demo data ------------------------------------------- #
# --------------------------------------------------------------------------- #


def _persist_forecast(db: Session, pan: Optional[Pan], days: list, source: str) -> None:
    from app.routers.predictions import persist_forecast

    persist_forecast(db, pan, days, source)


def _sensor_row(pan: Pan, ts: dt.datetime, den: float, depth: float,
                brine_temp: float, air_temp: float, humidity: float,
                base_salinity: float = 0.0, jitter: float = 0.0) -> SensorReading:
    sal = base_salinity or round(den * 9.5, 1)
    return SensorReading(
        pan_id=pan.id,
        timestamp=ts,
        salinity_g_l=round(sal + jitter, 1),
        ec_ms_cm=round(den * 15.0 + jitter * 4.0, 1),
        water_depth_cm=round(depth + jitter * 0.15, 2),
        brine_temperature_c=round(brine_temp + jitter * 0.6, 1),
        air_temperature_c=round(air_temp + jitter, 1),
        humidity_pct=round(humidity + jitter * 3.0, 1),
        sensor_quality=round(min(100.0, 93.0 + abs(jitter) * 4.0), 1),
        source="in-situ_sensor",
    )


def _seed_sensor_history(db: Session, pan: Pan, state: dict, demo_today: dt.date,
                         brine_temp: float) -> None:
    """30 days of hourly in-situ sensor telemetry anchored to the twin state.

    Produces 30 x 24 = 720 readings per pan so charts/tables have a real
    30-day hourly history without any physical sensor hardware.
    """
    den = float(state.get("brine_density_be", 21.0))
    depth = float(state.get("water_depth_cm", 10.0))
    base_sal = float(state.get("salinity_g_l") or den * 9.5)
    base_temp = float(state.get("brine_temperature_c") or brine_temp or 30.0)

    rows: List[SensorReading] = []
    end = demo_today
    start = end - dt.timedelta(days=29)  # inclusive 30 days
    day_count = 0
    day = start
    while day <= end:
        day_count += 1
        air_base = float(state.get("air_temperature_c") or base_temp - 1.0)
        for hour in range(24):
            ts = dt.datetime.combine(day, dt.time(hour, 0))
            jitter = math.sin(hour / 2.4 + day_count) + 0.3 * math.cos(day_count * 1.3)
            rows.append(_sensor_row(
                pan, ts, den, depth,
                base_temp + 0.4 * math.sin((hour - 15) / 12.0 * math.pi),
                air_base + 2.0 * math.sin((hour - 14) / 12.0 * math.pi),
                58 + 10 * math.cos(hour / 24.0 * 2 * math.pi),
                base_salinity=base_sal,
                jitter=jitter,
            ))
        day += dt.timedelta(days=1)
    db.add_all(rows)
    db.flush()


def _seed_weather_history(db: Session, pans: Dict[str, Pan], demo_today: dt.date) -> None:
    """Historical daily weather observations incl. explicit rainfall events.

    One row per observed day for the past 30 days. Rainy days carry a positive
    `actual_rainfall_mm` so they read as recorded rainfall events. Seeded up to
    but NOT including demo_today so the Dashboard's "next 24h" forecast stays
    unambiguous.
    """
    rows: List[WeatherReading] = []
    end = demo_today - dt.timedelta(days=1)
    start = end - dt.timedelta(days=29)
    day = start
    # A fixed spread of "rainfall event" days per pan for reproducibility.
    rng_hits = {0: [3, 11, 22], 1: [5, 14, 26], 2: [2, 9, 18, 27]}
    for pan_key, pan in pans.items():
        idx = 0
        cursor = start
        while cursor <= end:
            rain = 0.0
            if idx % 29 in rng_hits.get(list(pans.keys()).index(pan_key), []):
                rain = round(14.0 + (idx % 5) * 3.2, 1)
            rows.append(WeatherReading(
                pan_id=pan.id,
                forecast_generated_at=dt.datetime.combine(cursor, dt.time(0, 0)),
                forecast_for=cursor,
                forecast_rain_mm=0.0,
                rain_probability_pct=0.0,
                actual_rainfall_mm=rain if rain > 0 else None,
                temperature_c=round(29.0 + 3.0 * math.cos(idx / 6.0), 1),
                humidity_pct=round(55.0 + 8.0 * (1 if rain > 0 else -0.4), 1),
                wind_speed_ms=round(2.8 + 0.4 * math.sin(idx / 4.0), 2),
                solar_radiation_wm2=round(760.0 - 220.0 * (1 if rain > 0 else 0), 1),
                cloud_cover_pct=round(95.0 if rain > 0 else 25.0, 1),
                source="observation",
            ))
            cursor += dt.timedelta(days=1)
            idx += 1
    db.add_all(rows)
    db.flush()


def _demo_forecast(pan_key: str, meta: dict, demo_today: dt.date) -> List[dict]:
    if pan_key == "PAN-03":
        # Published example: rain lands on day 0 only (20 mm, 78%) so the
        # 7-day window total is exactly 20 mm -> predicted salinity 196 g/L.
        days = []
        for k in range(7):
            day = demo_today + dt.timedelta(days=k)
            if k == 0:
                days.append({
                    "date": day.isoformat(),
                    "temperature_c": 27.5,
                    "humidity_pct": 86.0,
                    "wind_speed_kmh": 24.0,
                    "rainfall_mm": 20.0,
                    "precipitation_probability_pct": 78.0,
                    "sunshine_hours": 0.5,
                })
            else:
                days.append({
                    "date": day.isoformat(),
                    "temperature_c": round(31.0 + (k % 2), 1),
                    "humidity_pct": 60.0,
                    "wind_speed_kmh": 12.0,
                    "rainfall_mm": 0.0,
                    "precipitation_probability_pct": round(15.0 - k, 1),
                    "sunshine_hours": 9.0,
                })
        return days
    result = weather_provider.get_forecast(meta["lat"], meta["lon"],
                                           start=demo_today, days=7)
    return list(result["days"])


def _seed_operations_and_outcomes(db: Session, pans: Dict[str, Pan],
                                  predictions: Dict[str, object],
                                  recommendations: Dict[str, List[Recommendation]],
                                  demo_today: dt.date) -> Dict[str, Pan]:
    """Log a handful of past field operations and verified harvest outcomes.

    These give the Operations / Outcomes / Feedback panels real history and
    mirror how the outcomes -> operation-event -> twin-feedback loop behaves.
    """
    scenarios = {
        "PAN-1": {
            "ops": [
                ("drain", {"drained_volume_l": 1200.0, "days_ago": 4, "notes": "pre-season water level adjust"}),
                ("brine_transfer", {"transferred_volume_l": 3600.0, "days_ago": 12, "notes": "topped-up concentrated brine"}),
                ("harvest", {"days_ago": 20, "notes": "commercial salt lifting"}),
            ],
            "outcome": {"days_ago": 20, "yield_kg": 1830.0, "purity_pct": 94.2},
        },
        "PAN-2": {
            "ops": [
                ("protection", {"protection_applied": True, "days_ago": 6, "notes": "storm shutter + brine guard"}),
                ("pumping", {"pump_duration_min": 45.0, "days_ago": 3, "notes": "removed dilute surface water"}),
            ],
            "outcome": {"days_ago": 31, "yield_kg": 2120.0, "purity_pct": 95.0},
        },
        "PAN-03": {
            "ops": [
                ("harvest", {"days_ago": 9, "notes": "first crop of the season"}),
                ("protection", {"protection_applied": True, "days_ago": 2, "notes": "pre-rain protection raised"}),
            ],
            "outcome": {"days_ago": 9, "yield_kg": 620.0, "purity_pct": 96.4},
        },
    }

    for pan_key, pan in pans.items():
        scenario = scenarios[pan_key]
        for op in scenario["ops"]:
            op_type, fields = op
            ts = dt.datetime.combine(demo_today - dt.timedelta(days=fields.pop("days_ago")),
                                     dt.time(9, 30))
            db.add(OperationEvent(
                pan_id=pan.id,
                event_timestamp=ts,
                event_type=op_type,
                operator_notes=fields.pop("notes", ""),
                **fields,
            ))
        outcome = scenario["outcome"]
        ots = dt.datetime.combine(demo_today - dt.timedelta(days=outcome["days_ago"]),
                                  dt.time(12, 0)).date().isoformat()
        db.add(HarvestOutcome(
            pan_id=pan.id,
            harvest_date=ots,
            actual_yield_kg=outcome["yield_kg"],
            salt_purity_pct=outcome["purity_pct"],
            outcome_notes="Auto-seeded Phase-14 demo harvest outcome.",
            verified=True,
            verified_at=dt.datetime.utcnow(),
        ))
    db.flush()
    return pans


def _add_example_recommendation(db: Session, pan: Pan, pred,
                                demo_today: dt.date) -> Recommendation:
    """Guarantee the published PAN-03 'Harvest now' recommendation exists."""
    code = f"harvest_now-{pan.pan_code}-{int(dt.datetime.utcnow().timestamp())}-{uuid.uuid4().hex[:4]}"
    rec = Recommendation(
        recommendation_code=code,
        pan_id=pan.id,
        prediction_id=pred.id if pred else None,
        timestamp=dt.datetime.utcnow(),
        recommended_action="harvest_now",
        action_deadline=dt.datetime.combine(demo_today + dt.timedelta(days=1), dt.time(6, 0)),
        reason_1="20 mm of rain forecast in the next 24h (78% probability).",
        reason_2="Crop is harvest-ready: 245 g/L brine at 8 cm depth.",
        reason_3="Rain would dilute the brine to ~196 g/L and dissolve surface salt.",
        instruction_1="Harvest the crystallised salt before the rain front arrives.",
        instruction_2="Tarp or cover the harvested piles immediately.",
        instruction_3="After rain, re-check brine density before restarting evaporation.",
        confidence_pct=88.0,
        consequence_if_waited="Rain will re-dissolve up to 20% of the exposed crop and dilute the harvest brine.",
        status="pending",
    )
    db.add(rec)
    db.flush()
    return rec


# --------------------------------------------------------------------------- #
# Existing seed helpers ------------------------------------------------------ #
# --------------------------------------------------------------------------- #


def _seed_sensors(db: Session, pan: Pan, state: dict, days: List[dict]) -> None:
    """A short synthetic in-situ sensor series anchored to the twin state."""
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
    # PAN-03 embeds the published example values (245 g/L, 8 cm, 34 °C brine).
    DEMO_TWIN_STATES = {
        "PAN-1": {"brine_density_be": 26.5, "salt_thickness_mm": 11.5, "water_depth_cm": 8.0,
                  "days_since_last_rain": 6},
        "PAN-2": {"brine_density_be": 28.1, "salt_thickness_mm": 16.2, "water_depth_cm": 6.5,
                  "days_since_last_rain": 3},
        "PAN-03": {"brine_density_be": round(245.0 / 9.5, 2), "salt_thickness_mm": 14.0,
                   "water_depth_cm": 8.0, "days_since_last_rain": 12,
                   "brine_temperature_c": 34.0, "salinity_g_l": 245.0},
    }
    pans: Dict[str, Pan] = {}
    twins: Dict[str, dict] = {}
    forecasts: Dict[str, list] = {}
    for pan_key in DEMO_PAN_KEYS:
        meta = REGIONS[pan_key]
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
        forecast = _demo_forecast(pan_key, meta, demo_today)
        _persist_forecast(db, pan, list(forecast), source="mock")
        _seed_sensor_history(db, pan, twin, demo_today,
                             brine_temp=float(twin.get("brine_temperature_c") or 30.0))
        pans[pan_key] = pan
        twins[pan_key] = twin
        forecasts[pan_key] = forecast

    # Phase 14: 30-day daily weather observations with rainfall events.
    _seed_weather_history(db, pans, demo_today)

    # ---- 3. Train models ---------------------------------------------------
    from app.services.training import train_model
    from app.config.proxy_labels import get_proxy_labels_config
    from app.services.proxy_labels import ensure_labels
    from app.services.model_targets import resolve_targets

    prep_df, label_report = ensure_labels(df, get_proxy_labels_config(),
                                          dataset_source="generated")
    prep_df, target_report = resolve_targets(prep_df, label_report,
                                             dataset_source="generated")
    model_records: Dict[str, ModelVersion] = {}
    model_kinds = ("harvest_readiness", "climate_risk",
                   "climate_risk_classifier", "harvest_readiness_classifier",
                   "harvest_time_regressor")
    for kind in model_kinds:
        trained = train_model(kind, prep_df, dataset_id, settings.models_path,
                              labels_report=label_report,
                              target_report=target_report,
                              dataset_name=dataset.name)
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
            dataset_id=dataset_id,
            active=bool(trained["version"] and trained["status"] == "trained"),
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
    predictions: Dict[str, object] = {}
    recommendations: Dict[str, List[Recommendation]] = {}
    for pan_key, pan in pans.items():
        from app.services.digital_twin import latest_forecast_days

        state = dict(twins[pan_key])
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
        pan_recs: List[Recommendation] = []
        for rec in recs[:3]:
            from app.routers.recommendations import _to_row

            rec["_timeline"] = timeline
            row = _to_row(pan, pred, rec)
            db.add(row)
            pan_recs.append(row)
            created_recommendations += 1

        # Force the published PAN-03 example recommendation regardless of the
        # model's exact output so the demo always demonstrates "Harvest now".
        if pan_key == "PAN-03":
            example_rec = _add_example_recommendation(db, pan, pred, demo_today)
            pan_recs.append(example_rec)
            created_recommendations += 1

        db.flush()
        predictions[pan_key] = pred
        recommendations[pan_key] = pan_recs

        # PAN-03 is forced to the example's High-risk / Ready values so the
        # dashboard consistently shows Risk: High and Readiness: Ready.
        if pan_key == "PAN-03":
            readiness = 0.74
            risk = 0.78
        else:
            readiness = float(timeline[0]["readiness"])
            risk = max(float(p["risk"]) for p in timeline)

        record_state(db, pan, state, source="seed",
                     forecast_days=forecast_days,
                     readiness=readiness,
                     risk=risk)

    # ---- 5. Phase 14: operation events + harvest outcomes -------------------
    _seed_operations_and_outcomes(db, pans, predictions, recommendations, demo_today)

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
        "message": ("Demo seeded: dataset, 3 pans (incl. PAN-03 example), 30-day hourly sensors, "
                    "weather observations & rainfall, models, predictions, recommendations, "
                    "operations & harvest outcomes created."),
    }


def _find_dataset(db: Session, name_part: str) -> Optional[DataSet]:
    return db.query(DataSet).filter(DataSet.name.like(f"%{name_part}%")).first()
