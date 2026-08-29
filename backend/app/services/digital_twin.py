from __future__ import annotations

import datetime as dt
import math
from typing import Dict, List, Optional

from app.models import SaltPan
from app.services.data_generator import (
    SALT_BULK_DENSITY_KG_M3,
    TARGET_THICKNESS_MM,
    advance_pan_state,
)


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
    merged["estimated_salt_mass_kg"] = salt_mass_kg(merged["salt_thickness_mm"], area_m2=None)
    return merged


def salt_mass_kg(thickness_mm: float, area_m2: Optional[float] = None) -> float:
    area = area_m2 if area_m2 else 2400.0
    return round(thickness_mm / 1000.0 * SALT_BULK_DENSITY_KG_M3 * area, 1)


def progress_to_harvest(pan: SaltPan) -> float:
    st = normalise_state(pan.twin_state)
    den = st["brine_density_be"]
    thick = st["salt_thickness_mm"]
    den_p = max(0.0, min((den - 20.0) / 7.0, 1.0))
    thick_p = max(0.0, min(thick / TARGET_THICKNESS_MM, 1.0))
    return round(0.45 * den_p + 0.55 * thick_p, 3)


def step_twin(pan: SaltPan, weather_day: dict, rng=None) -> dict:
    """Advance a pan's digital twin by one simulated day."""
    import numpy as np

    rng = rng or np.random.default_rng(0)
    st = normalise_state(pan.twin_state)
    weather = {
        "temperature_c": float(weather_day.get("temperature_c", 28.0)),
        "humidity_pct": float(weather_day.get("humidity_pct", 60.0)),
        "wind_speed_kmh": float(weather_day.get("wind_speed_kmh", 10.0)),
        "sunshine_hours": float(weather_day.get("sunshine_hours", 9.0)),
        "rainfall_mm": float(weather_day.get("rainfall_mm", 0.0)),
    }
    new_state = advance_pan_state(st, weather, 0.0, rng)
    new_state["estimated_salt_mass_kg"] = salt_mass_kg(new_state["salt_thickness_mm"],
                                                       getattr(pan, "area_m2", None))
    return normalise_state(new_state)


def run_twin_timeline(pan: SaltPan, forecast_days: List[dict],
                      start_date: Optional[str] = None) -> List[dict]:
    """Project the twin state day-by-day over a forecast timeline."""
    import numpy as np

    rng = np.random.default_rng(len(forecast_days) * 7 + pan.id)
    result: List[dict] = []
    state = normalise_state(pan.twin_state)
    base = dt.date.fromisoformat(start_date) if start_date else dt.date.today()
    for i, w in enumerate(forecast_days):
        day = base + dt.timedelta(days=i)
        state = advance_pan_state(state, w, 0.0, rng)
        snapshot = normalise_state(state)
        snapshot["date"] = day.isoformat()
        snapshot["weather"] = w
        result.append(snapshot)
    return result


def apply_outcome_to_twin(pan: SaltPan, outcome_data: dict) -> dict:
    """Feed verified physical outcomes back into the digital twin's state."""
    st = normalise_state(pan.twin_state)
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
    st["estimated_salt_mass_kg"] = salt_mass_kg(st["salt_thickness_mm"], pan.area_m2)
    return st


def horizon_summary(projection: List[dict]) -> dict:
    """Summary of a twin projection used for recommendations/evaluations."""
    if not projection:
        return {}
    latest = projection[-1]
    highs = max((p["climate_risk"] for p in projection), default=0.0) if "climate_risk" in projection[0] else None
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