from __future__ import annotations

import datetime as dt
import math
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.models import DigitalTwinState, OperationEvent, Pan, SensorReading, WeatherReading
from app.services.data_generator import SALT_BULK_DENSITY_KG_M3, TARGET_THICKNESS_MM, advance_pan_state


# Legacy pan metadata carried inside the twin state JSON.
PAN_META_KEYS = ("location", "status", "demo_today", "last_update", "demo_latitude", "demo_longitude")
_SOURCE_KEY = "_source"


def default_twin_state() -> dict:
    return {
        "water_depth_cm": 12.0,
        "brine_density_be": 21.0,
        "salt_thickness_mm": 4.0,
        "days_since_last_rain": 6,
        "last_rain_date": None,
        "last_harvest_date": None,
        "estimated_salt_mass_kg": None,
    }


def normalise_state(state: Optional[dict]) -> dict:
    base = default_twin_state()
    if not state:
        return base
    merged = {**base, **state}
    for k in ("water_depth_cm", "brine_density_be", "salt_thickness_mm"):
        try:
            merged[k] = float(merged.get(k, 0.0))
        except (TypeError, ValueError):
            merged[k] = 0.0
    try:
        merged["days_since_last_rain"] = int(float(merged.get("days_since_last_rain", 0)))
    except (TypeError, ValueError):
        merged["days_since_last_rain"] = 0
    merged["salt_thickness_mm"] = max(0.0, merged["salt_thickness_mm"])
    merged["estimated_salt_mass_kg"] = salt_mass_kg(
        merged["salt_thickness_mm"], area_m2=merged.get("pan_area_m2"))
    return merged


def salt_mass_kg(thickness_mm: float, area_m2: Optional[float] = None) -> float:
    area = area_m2 if area_m2 else 2400.0
    return round(thickness_mm / 1000.0 * SALT_BULK_DENSITY_KG_M3 * area, 1)


def progress_to_harvest(state: dict) -> float:
    st = normalise_state(state)
    den = st["brine_density_be"]
    thick = st["salt_thickness_mm"]
    den_p = max(0.0, min((den - 20.0) / 7.0, 1.0))
    thick_p = max(0.0, min(thick / TARGET_THICKNESS_MM, 1.0))
    return round(0.45 * den_p + 0.55 * thick_p, 3)


def step_twin(state: dict, weather_day: dict, rng=None) -> dict:
    """Advance a digital-twin state by one simulated day."""
    import numpy as np

    rng = rng or np.random.default_rng(0)
    st = normalise_state(state)
    weather = {
        "temperature_c": float(weather_day.get("temperature_c", 28.0)),
        "humidity_pct": float(weather_day.get("humidity_pct", 60.0)),
        "wind_speed_kmh": float(weather_day.get("wind_speed_kmh", 10.0)),
        "sunshine_hours": float(weather_day.get("sunshine_hours", 9.0)),
        "rainfall_mm": float(weather_day.get("rainfall_mm", 0.0)),
    }
    new_state = advance_pan_state(st, weather, 0.0, rng)
    new_state["estimated_salt_mass_kg"] = salt_mass_kg(new_state["salt_thickness_mm"],
                                                       st.get("pan_area_m2"))
    return normalise_state(new_state)


def run_twin_timeline(state: dict, forecast_days: List[dict],
                      start_date: Optional[str] = None, seed: int = 7) -> List[dict]:
    """Project the twin state day-by-day over a forecast timeline."""
    import numpy as np

    rng = np.random.default_rng(seed)
    result: List[dict] = []
    st = normalise_state(state)
    base = dt.date.fromisoformat(start_date) if start_date else dt.date.today()
    for i, w in enumerate(forecast_days):
        day = base + dt.timedelta(days=i)
        st = advance_pan_state(st, w, 0.0, rng)
        snapshot = normalise_state(st)
        snapshot["date"] = day.isoformat()
        snapshot["weather"] = w
        result.append(snapshot)
    return result


# ------------------------------------------------------------------ persistence

def get_twin_state(db: Session, pan: Pan) -> dict:
    row = (db.query(DigitalTwinState)
           .filter(DigitalTwinState.pan_id == pan.id)
           .order_by(DigitalTwinState.timestamp.desc())
           .first())
    if not row:
        st = default_twin_state()
        st["pan_area_m2"] = pan.area_m2
        return st
    return dict(row.state_json or {})


def latest_forecast_days(db: Session, pan: Pan, days: int = 7) -> List[dict]:
    """Reconstruct provider-style day dicts from the newest forecast batch."""
    rows = (db.query(WeatherReading)
            .filter(WeatherReading.pan_id == pan.id)
            .order_by(WeatherReading.forecast_generated_at.desc())
            .all())
    if not rows:
        return []
    latest_at = rows[0].forecast_generated_at
    batch = [r for r in rows if r.forecast_generated_at == latest_at]
    batch.sort(key=lambda r: r.forecast_for or dt.date.max)
    out: List[dict] = []
    for r in batch:
        day = {
            "date": r.forecast_for.isoformat() if r.forecast_for else "",
            "temperature_c": r.temperature_c,
            "humidity_pct": r.humidity_pct,
            "wind_speed_kmh": round(r.wind_speed_ms * 3.6, 1),
            "rainfall_mm": r.forecast_rain_mm,
            "precipitation_probability_pct": r.rain_probability_pct,
            "sunshine_hours": round(r.solar_radiation_wm2 / 100.0, 1),
        }
        if r.actual_rainfall_mm is not None:
            day["actual_rainfall_mm"] = r.actual_rainfall_mm
        out.append(day)
    return out[:days]


def _derive_columns(state: dict, pan: Pan, forecast_days: List[dict]) -> dict:
    st = normalise_state(state)
    area = float(pan.area_m2 or 1000.0)
    safe_depth = float(pan.safe_depth_cm or 12.0)
    depth = st["water_depth_cm"]
    den = st["brine_density_be"]

    forecast_days = forecast_days or []
    day0 = forecast_days[0] if forecast_days else {}
    rain_mm_total = float(sum(d.get("rainfall_mm", 0.0) for d in forecast_days))
    predicted_depth_after_rain_cm = round(depth + rain_mm_total / 10.0, 2)
    den_after_rain = den * depth / max(predicted_depth_after_rain_cm, 0.1)
    den_after_rain = max(0.0, min(den_after_rain, 30.0))

    return {
        "brine_volume_m3": round(depth / 100.0 * area, 2),
        "estimated_salt_mass_kg": float(st.get("estimated_salt_mass_kg") or 0.0),
        "evaporation_mm_day": round(float(evap_mm_day(day0)), 2),
        "predicted_rain_volume_m3": round(rain_mm_total / 1000.0 * area, 2),
        "predicted_depth_after_rain_cm": predicted_depth_after_rain_cm,
        "predicted_salinity_after_rain_g_l": round(den_after_rain * 9.5, 1),
        "overflow_risk": round(max(0.0, min(
            (predicted_depth_after_rain_cm - safe_depth) / max(safe_depth, 0.1), 1.0)), 3),
        "harvest_readiness": float(st.get("_harvest_readiness") or 0.0),
        "climate_risk": float(st.get("_climate_risk") or 0.0),
    }


def evap_mm_day(day: dict) -> float:
    from app.ml.features import evap_index

    return evap_index(
        float(day.get("temperature_c", 28.0)),
        float(day.get("humidity_pct", 60.0)),
        float(day.get("wind_speed_kmh", 10.0)),
        float(day.get("sunshine_hours", 9.0)),
        float(day.get("rainfall_mm", 0.0)),
    )


def apply_reading_to_state(state: dict, reading) -> dict:
    """Merge a validated sensor reading into a twin state dict.

    `reading` needs (at least) `salinity_g_l` and `water_depth_cm` plus the
    standard sensor attribute names; salinity in g/L is converted to the
    internal brine density in degrees Baume (÷ 9.5, the convention used by
    `_derive_columns`).
    """
    st = {**default_twin_state(), **(state or {})}
    if getattr(reading, "salinity_g_l", None) is not None:
        den = float(reading.salinity_g_l) / 9.5
        st["brine_density_be"] = round(max(3.5, min(den, 30.0)), 2)
        st["salinity_g_l"] = round(float(reading.salinity_g_l), 1)
    if getattr(reading, "water_depth_cm", None) is not None:
        st["water_depth_cm"] = round(float(reading.water_depth_cm), 2)
    if getattr(reading, "brine_temperature_c", None) is not None:
        st["brine_temperature_c"] = round(float(reading.brine_temperature_c), 2)
    if getattr(reading, "air_temperature_c", None) is not None:
        st["air_temperature_c"] = round(float(reading.air_temperature_c), 2)
    if getattr(reading, "humidity_pct", None) is not None:
        st["humidity_pct"] = round(float(reading.humidity_pct), 2)
    if getattr(reading, "ec_ms_cm", None) is not None:
        st["ec_ms_cm"] = round(float(reading.ec_ms_cm), 1)
    if getattr(reading, "sensor_quality", None) is not None:
        st["sensor_quality"] = round(float(reading.sensor_quality), 1)
    st["estimated_salt_mass_kg"] = salt_mass_kg(st["salt_thickness_mm"],
                                                st.get("pan_area_m2"))
    return st


def _latest_brine_temp(db: Session, pan: Pan) -> Optional[float]:
    row = (db.query(SensorReading)
           .filter(SensorReading.pan_id == pan.id)
           .order_by(SensorReading.timestamp.desc()).first())
    if row and row.brine_temperature_c:
        return float(row.brine_temperature_c)
    return None


def _latest_forecast_source(db: Session, pan: Pan) -> str:
    row = (db.query(WeatherReading)
           .filter(WeatherReading.pan_id == pan.id)
           .order_by(WeatherReading.forecast_generated_at.desc())
           .first())
    return row.source if row and row.source else "none"


def _latest_operation(db: Session, pan: Pan) -> Optional[dict]:
    ev = (db.query(OperationEvent)
          .filter(OperationEvent.pan_id == pan.id)
          .order_by(OperationEvent.event_timestamp.desc())
          .first())
    if ev:
        return {
            "event_type": ev.event_type,
            "timestamp": ev.event_timestamp.isoformat(),
            "recommendation_id": ev.recommendation_id,
        }
    return None


def twin_summary(db: Session, pan: Pan,
                 forecast_days: Optional[List[dict]] = None) -> dict:
    """Full operational digital-twin snapshot for one pan.

    Combines the internal twin state with the latest forecast to expose the
    current salinity/depth/temperature, brine volume and dissolved salt mass,
    next-24h and horizon rainfall with probability, post-rain projections,
    evaporation, harvest-readiness, climate risk, last operation and the last
    update timestamp.
    """
    st = normalise_state(get_twin_state(db, pan))
    forecast = list(forecast_days) if forecast_days is not None \
        else latest_forecast_days(db, pan, 7)
    derived = _derive_columns(st, pan, forecast)
    day0 = forecast[0] if forecast else {}

    den = st["brine_density_be"]
    salinity_g_l = round(float(st.get("salinity_g_l") or den * 9.5), 1)
    temp = float(st.get("brine_temperature_c") or _latest_brine_temp(db, pan) or 28.0)

    last_op = _latest_operation(db, pan)
    if not last_op:
        for marker, label in (("last_harvest_date", "harvest"),
                              ("last_rain_date", "rain_event")):
            if st.get(marker):
                last_op = {"event_type": label, "timestamp": str(st[marker])}
                break

    return {
        "pan_id": pan.id,
        "pan_ref": pan.pan_code,
        "timestamp": dt.datetime.utcnow().isoformat(),
        "last_update": str(st.get("last_update") or dt.date.today().isoformat()),
        "source": str(st.get(_SOURCE_KEY) or "manual"),
        "forecast_source": _latest_forecast_source(db, pan),
        "salinity_g_l": salinity_g_l,
        "water_depth_cm": round(st["water_depth_cm"], 2),
        "brine_temperature_c": round(temp, 2),
        "brine_volume_m3": derived["brine_volume_m3"],
        "estimated_salt_mass_kg": derived["estimated_salt_mass_kg"],
        "forecast_rainfall_mm": round(float(day0.get("rainfall_mm", 0.0)), 2),
        "forecast_rainfall_7d_mm": round(
            float(sum(d.get("rainfall_mm", 0.0) for d in forecast)), 2),
        "rain_probability_pct": round(
            float(day0.get("precipitation_probability_pct", 0.0)), 1),
        "predicted_depth_after_rain_cm": derived["predicted_depth_after_rain_cm"],
        "predicted_salinity_after_rain_g_l": derived["predicted_salinity_after_rain_g_l"],
        "evaporation_mm_day": derived["evaporation_mm_day"],
        "harvest_readiness": round(float(st.get("_harvest_readiness")
                                         or derived["harvest_readiness"]), 3),
        "climate_risk": round(float(st.get("_climate_risk")
                                    or derived["climate_risk"]), 3),
        "overflow_risk": derived["overflow_risk"],
        "last_operation": last_op,
        "demo_today": st.get("demo_today"),
        "state": st,
    }


def record_state(db: Session, pan: Pan, state: dict,
                 source: str = "manual", forecast_days: Optional[List[dict]] = None,
                 readiness: Optional[float] = None, risk: Optional[float] = None) -> dict:
    """Merge + normalise a twin state, persist a DigitalTwinState snapshot."""
    base = default_twin_state()
    latest = {**base, **(get_twin_state(db, pan) or {})}
    st = {**latest, _SOURCE_KEY: source, "pan_area_m2": pan.area_m2}
    st.update(state or {})
    st = normalise_state(st)
    if readiness is not None:
        st["_harvest_readiness"] = round(float(readiness), 4)
    if risk is not None:
        st["_climate_risk"] = round(float(risk), 4)
    st["last_update"] = dt.date.today().isoformat()
    if "location" not in st:
        st["location"] = pan.name

    forecast_days = forecast_days if forecast_days is not None else latest_forecast_days(db, pan)
    derived = _derive_columns(st, pan, forecast_days)

    row = DigitalTwinState(
        pan_id=pan.id,
        timestamp=dt.datetime.utcnow(),
        brine_volume_m3=derived["brine_volume_m3"],
        estimated_salt_mass_kg=derived["estimated_salt_mass_kg"],
        evaporation_mm_day=derived["evaporation_mm_day"],
        predicted_rain_volume_m3=derived["predicted_rain_volume_m3"],
        predicted_depth_after_rain_cm=derived["predicted_depth_after_rain_cm"],
        predicted_salinity_after_rain_g_l=derived["predicted_salinity_after_rain_g_l"],
        harvest_readiness=derived["harvest_readiness"],
        climate_risk=derived["climate_risk"],
        overflow_risk=derived["overflow_risk"],
        state_json=st,
    )
    db.add(row)
    db.flush()
    return st


# ------------------------------------------------------------------ feedback

def apply_outcome_to_twin(state: dict, outcome_data: dict) -> dict:
    """Feed verified physical outcomes back into a twin's state dict."""
    st = normalise_state(state)
    if outcome_data.get("actual_rainfall_mm"):
        rain = float(outcome_data["actual_rainfall_mm"])
        if rain > 1.0:
            vol = st["water_depth_cm"] * 10.0
            st["brine_density_be"] = round(
                max(3.5, st["brine_density_be"] * vol / (vol + rain)), 2)
            st["water_depth_cm"] = round(st["water_depth_cm"] + rain / 10.0, 2)
            st["salt_thickness_mm"] = max(
                0.0, round(st["salt_thickness_mm"] - rain * 0.012, 2))
            st["days_since_last_rain"] = 0
            st["last_rain_date"] = outcome_data.get("outcome_date") or dt.date.today().isoformat()
    if outcome_data.get("action_taken") == "harvest":
        st["salt_thickness_mm"] = 0.4
        st["brine_density_be"] = round(max(3.5, st["brine_density_be"] * 0.6), 2)
        st["water_depth_cm"] = 10.0
        st["last_harvest_date"] = outcome_data.get("harvest_date",
                                                    outcome_data.get("outcome_date"))
    if outcome_data.get("brine_density_be"):
        st["brine_density_be"] = float(outcome_data["brine_density_be"])
    if outcome_data.get("salt_thickness_mm") is not None:
        st["salt_thickness_mm"] = float(outcome_data["salt_thickness_mm"])
    st["estimated_salt_mass_kg"] = salt_mass_kg(st["salt_thickness_mm"],
                                                st.get("pan_area_m2"))
    return st


def horizon_summary(projection: List[dict]) -> dict:
    """Summary of a twin projection used for recommendations/evaluations."""
    if not projection:
        return {}
    latest = projection[-1]
    min_den = min((p["brine_density_be"] for p in projection), default=latest["brine_density_be"])
    min_den = min(min_den, latest["brine_density_be"])
    return {
        "days_in_horizon": len(projection),
        "final_salt_thickness_mm": latest["salt_thickness_mm"],
        "final_brine_density_be": latest["brine_density_be"],
        "final_water_depth_cm": latest["water_depth_cm"],
        "min_brine_density_be": round(min_den, 2),
        "final_est_mass_kg": latest.get("estimated_salt_mass_kg"),
    }