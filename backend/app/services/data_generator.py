from __future__ import annotations

import datetime as dt
import math
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from app.ml.features import evap_index

# Physical constants
SALT_BULK_DENSITY_KG_M3 = 1200.0     # crystallised salt bulk density
TARGET_THICKNESS_MM = 15.0           # harvest target
DEPOSITION_MM_PER_MM_EVAP = 0.20     # salt gain per mm of brine evaporated (saturated brine)
DISSOLUTION_PER_RAIN = 0.012         # mm thickness dissolved per productive mm of rain
SEA_BRINE_BE = 3.5
SATURATION_BE = 28.0
DEPOSITION_START_BE = 25.0

REGIONS = {
    "PAN-1": {"name": "Tuticorin Salt Pan A", "location": "Tuticorin, Tamil Nadu",
              "area_m2": 2400.0, "lat": 8.7642, "lon": 78.1348, "rain_scale": 1.0, "temp_offset": 1.0},
    "PAN-2": {"name": "Bhavnagar Salt Pan G", "location": "Bhavnagar, Gujarat",
              "area_m2": 5000.0, "lat": 21.7645, "lon": 72.1519, "rain_scale": 0.9, "temp_offset": 0.0},
    "PAN-3": {"name": "Sambhar Salt Works H", "location": "Sambhar Lake, Rajasthan",
              "area_m2": 1200.0, "lat": 26.9063, "lon": 75.1839, "rain_scale": 0.6, "temp_offset": -1.5},
    # PAN-03 is a dedicated, compact demo pan (published Phase-14 example:
    # area 500 m², high salinity endpoint, rain-on-the-way harvest scenario).
    "PAN-03": {"name": "Coastal Demo Pan C", "location": "Kutch Coast Demo Site, Gujarat",
               "area_m2": 500.0, "lat": 23.1594, "lon": 69.8289, "rain_scale": 1.15, "temp_offset": 0.5},
}


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def generate_weather_for_day(day: dt.date, rng: np.random.Generator,
                             temp_offset: float = 0.0, rain_scale: float = 1.0) -> dict:
    """Seasonal, monsoon-aware weather generator for a single day."""
    # Day of year position in a seasonal cycle (peak heat in May/June).
    doy = float(day.timetuple().tm_yday)
    annual = 2 * math.pi * (doy - 120) / 365.0  # peak at ~day 120
    temp_base = 28.0 + 6.0 * math.cos(annual)
    monsoon_phase = _clip(math.sin(2 * math.pi * (doy - 180) / 200.0), 0.0, 1.0)

    temperature_c = _clip(temp_base + temp_offset + rng.normal(0, 1.8), 5.0, 46.0)
    humidity_pct = _clip(52.0 - 18.0 * math.cos(annual) + 22.0 * monsoon_phase
                         + rng.normal(0, 7.0), 15.0, 100.0)
    wind_speed_kmh = _clip(8.0 + 2.0 * monsoon_phase * 14.0 + rng.normal(0, 4.0), 0.0, 70.0)

    rain_prob = 0.07 + 0.62 * monsoon_phase
    rainfall_mm = 0.0
    if rng.random() < rain_prob:
        rainfall_mm = _clip(rng.gamma(shape=1.4, scale=6.0) * rain_scale
                            + (14.0 * rain_scale if rng.random() < 0.12 else 0.0), 0.0, 140.0)
    sunshine_hours = _clip(11.0 - 2.0 * monsoon_phase - 1.2 * (rainfall_mm / 60.0)
                           + rng.normal(0, 1.2), 0.0, 13.0)
    return {
        "temperature_c": round(temperature_c, 2),
        "humidity_pct": round(humidity_pct, 2),
        "wind_speed_kmh": round(wind_speed_kmh, 2),
        "rainfall_mm": round(rainfall_mm, 2),
        "sunshine_hours": round(sunshine_hours, 2),
    }


def advance_pan_state(
    state: dict, weather: dict, dosage: float, rng: np.random.Generator
) -> dict:
    """One day of physical evolution for the twin / generator state machine."""
    rain = float(weather.get("rainfall_mm", 0.0))
    temp = float(weather.get("temperature_c", 28.0))
    hum = float(weather.get("humidity_pct", 65.0))
    wind = float(weather.get("wind_speed_kmh", 10.0))
    sun = float(weather.get("sunshine_hours", 9.0))

    depth = max(float(state["water_depth_cm"]), 0.5)
    den = _clip(float(state["brine_density_be"]), SEA_BRINE_BE, SATURATION_BE + 0.5)
    salt_mm = max(float(state["salt_thickness_mm"]), 0.0)
    dsr = int(state.get("days_since_last_rain", 1))

    # --- evaporation -------------------------------------------------
    evap_water = evap_index(temp, hum, wind, sun, rain)  # mm/day of water
    evap_water = min(evap_water, depth * 10.0 * 0.5)     # can't dry the pan overnight
    depth_cm_after_evap = (depth * 10.0 - evap_water) / 10.0

    vol_before = depth * 10.0          # water depth in mm equivalent
    vol_after = depth_cm_after_evap * 10.0

    # --- density / crystallisation -----------------------------------
    deposited_from_solution_mm = 0.0
    if den >= DEPOSITION_START_BE and vol_after > 0:
        keep_density = _clip((den - DEPOSITION_START_BE) / (SATURATION_BE - DEPOSITION_START_BE), 0.0, 1.0)
        deposited_from_solution_mm = evap_water * DEPOSITION_MM_PER_MM_EVAP * (0.4 + 0.6 * keep_density)
        den_new = _clip(SEA_BRINE_BE + (den - SEA_BRINE_BE) * 1.02, SEA_BRINE_BE, SATURATION_BE)
    else:
        if vol_after > 0:
            den_new = _clip(den * vol_before / max(vol_after, 0.01), SEA_BRINE_BE, SATURATION_BE)
        else:
            den_new = den

    # --- rainfall: dilute + dissolve ----------------------------------
    salt_dissolved_mm = 0.0
    if rain > 1.0:
        vol_wet = vol_after + rain
        den_new = _clip(den_new * vol_after / max(vol_wet, 0.01), SEA_BRINE_BE, SATURATION_BE)
        active_depth_below_salt = max(depth_cm_after_evap, 0.5)
        productive_rain = rain * _clip(3.0 - active_depth_below_salt, 0.3, 1.0)
        salt_dissolved_mm = min(salt_mm, productive_rain * DISSOLUTION_PER_RAIN)
        depth_cm_after_evap = depth_cm_after_evap + rain / 10.0
        dsr = 0
    else:
        dsr = dsr + 1

    salt_mm_new = max(salt_mm + deposited_from_solution_mm - salt_dissolved_mm, 0.0)

    # Top-up with seawater when brine is too shallow.
    min_depth = max(1.0, 12.0 - 4.0 * _clip((salt_mm_new / TARGET_THICKNESS_MM), 0.0, 1.0))
    refreshed_from_freshwater = False
    if depth_cm_after_evap < min_depth:
        deficit = min_depth - depth_cm_after_evap
        den_new = (den_new * depth_cm_after_evap + SEA_BRINE_BE * deficit) / min_depth
        depth_cm_after_evap = min_depth
        if den_new < 9.0:  # a genuine re-set with fresh seawater
            refreshed_from_freshwater = True
            if salt_mm_new > 0:
                salt_mm_new = 0.0

    # Buffering: brine sitting on solid salt re-saturates by dissolving the bed.
    # This keeps crystallisers near saturation during rain instead of collapsing.
    if salt_mm_new > 0.0 and den_new < 26.0 and not refreshed_from_freshwater and rain <= 60:
        delta = 26.0 - den_new
        dissolve_mm = min(salt_mm_new, delta * max(depth_cm_after_evap, 1.0) * 0.08)
        salt_mm_new = max(0.0, salt_mm_new - dissolve_mm)
        if salt_mm_new > 0.0:
            den_new = 26.0

    new_state = dict(state)
    new_state.update({
        "water_depth_cm": round(depth_cm_after_evap, 2),
        "brine_density_be": round(den_new, 2),
        "salt_thickness_mm": round(salt_mm_new, 2),
        "days_since_last_rain": dsr,
        "last_rain_mm": round(rain, 1),
        "dosage_used": round(dosage, 3),
    })
    return new_state


def generate_dataset(
    start: Optional[dt.date] = None,
    end: Optional[dt.date] = None,
    pan_ids: Optional[List[str]] = None,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate a physically plausible daily salt-pan management dataset."""
    start = start or dt.date(2021, 1, 1)
    end = end or dt.date(2024, 4, 30)
    pan_ids = pan_ids or list(REGIONS.keys())
    rng = np.random.default_rng(seed)

    n_days = (end - start).days + 1
    rows: List[dict] = []
    for pan_key in pan_ids:
        meta = REGIONS[pan_key]
        state = {
            "water_depth_cm": 14.0,
            "brine_density_be": SEA_BRINE_BE,
            "salt_thickness_mm": 0.0,
            "days_since_last_rain": 12,
            "last_rain_date": str(start - dt.timedelta(days=12)),
            "last_harvest_date": str(start - dt.timedelta(days=30)),
        }
        prior7: List[float] = [0.0] * 7
        last_ready = False
        for i in range(n_days):
            day = start + dt.timedelta(days=i)
            weather = generate_weather_for_day(day, rng, meta["temp_offset"], meta["rain_scale"])
            # A fraction of pans are pumped/refreshed with dosing for realism.
            dosage = 0.0
            state = advance_pan_state(state, weather, dosage, rng)

            next7 = sum(
                generate_weather_for_day(start + dt.timedelta(days=i + k), rng,
                                         meta["temp_offset"], meta["rain_scale"])["rainfall_mm"]
                for k in range(1, 8)
            )
            next7_rain = next7
            # Feasible forecast ~ actual + realistic error
            forecast_error = rng.normal(0.0, 0.12 * max(next7_rain, 5.0))
            forecast_7d = max(0.0, next7_rain + forecast_error)
            prob = _clip(8 + next7_rain * 0.85 + rng.normal(0, 6), 0, 98)

            den = state["brine_density_be"]
            salt_mm = state["salt_thickness_mm"]
            dsr = state["days_since_last_rain"]

            # --- readiness label -------------------------------------
            density_component = _clip((den - DEPOSITION_START_BE + 1.0) / 4.0, 0.0, 1.0)
            thickness_component = _clip(salt_mm / TARGET_THICKNESS_MM, 0.0, 1.0)
            ready = 0.5 * density_component + 0.5 * thickness_component
            if dsr < 5 and ready > 0.4:
                ready *= (0.65 + 0.35 * dsr / 5.0)
            ready = _clip(ready + rng.normal(0, 0.04), 0.0, 1.0)

            # --- climate risk label -----------------------------------
            exposed = _clip(salt_mm / TARGET_THICKNESS_MM, 0.0, 1.0)
            risk = 0.04 + 0.55 * _clip(next7_rain / 80.0, 0.0, 1.0) \
                + 0.26 * exposed + 0.12 * _clip((den - 20.0) / 8.0, 0.0, 1.0)
            risk = _clip(risk + rng.normal(0, 0.05), 0.0, 1.0)

            is_ready = ready >= 0.7 and dsr >= 2 and den >= DEPOSITION_START_BE
            harvest_now = is_ready and not last_ready
            last_ready = is_ready

            yield_kg = 0.0
            action = ""
            if harvest_now:
                action = "harvest"
                yield_kg = round(salt_mm / 1000.0 * SALT_BULK_DENSITY_KG_M3 * meta["area_m2"], 1)
                # Harvest resets the bed.
                state["salt_thickness_mm"] = 0.4
                state.update({
                    "brine_density_be": _clip(SEA_BRINE_BE + (den - SEA_BRINE_BE) * 0.55, SEA_BRINE_BE, SATURATION_BE),
                    "water_depth_cm": 10.0,
                    "last_harvest_date": str(day),
                })
                salt_mm = 0.4

            rows.append({
                "pan_id": pan_key,
                "date": day.isoformat(),
                "season": "summer" if 2 <= day.month <= 6 else ("monsoon" if 7 <= day.month <= 9 else "other"),
                "temperature_c": weather["temperature_c"],
                "humidity_pct": weather["humidity_pct"],
                "wind_speed_kmh": weather["wind_speed_kmh"],
                "rainfall_mm": weather["rainfall_mm"],
                "sunshine_hours": weather["sunshine_hours"],
                "water_depth_cm": state["water_depth_cm"],
                "brine_density_be": state["brine_density_be"],
                "salt_thickness_mm": state["salt_thickness_mm"],
                "days_since_last_rain": state["days_since_last_rain"],
                "precipitation_7d_forecast_mm": round(forecast_7d, 2),
                "precipitation_probability_pct": round(prob, 1),
                "next7d_rain_mm": round(next7_rain, 2),
                "harvest_readiness": round(ready, 4),
                "climate_risk": round(risk, 4),
                "harvest_ready_flag": int(is_ready),
                "yield_kg": round(yield_kg, 1),
                "action_recorded": action,
                "area_m2": meta["area_m2"],
                "latitude": meta["lat"],
                "longitude": meta["lon"],
            })
            prior7 = prior7[1:] + [weather["rainfall_mm"]]

    df = pd.DataFrame(rows)
    return df


def dataset_to_file(df: pd.DataFrame, path) -> str:
    import os
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    df.to_csv(path, index=False)
    return str(path)


def latest_pan_state(df: pd.DataFrame, pan_id: str) -> Dict[str, float]:
    """State of the last observation for a pan -> seeds the digital twin."""
    sub = df[df["pan_id"] == pan_id].sort_values("date")
    row = sub.iloc[-1]
    return {
        "water_depth_cm": float(row["water_depth_cm"]),
        "brine_density_be": float(row["brine_density_be"]),
        "salt_thickness_mm": float(row["salt_thickness_mm"]),
        "days_since_last_rain": int(row["days_since_last_rain"]),
        "last_rain_date": str(row["date"]) if float(row["rainfall_mm"]) > 0 else None,
        "last_harvest_date": sub.loc[sub["action_recorded"] == "harvest", "date"].tolist()[-1] if (
            (sub["action_recorded"] == "harvest").any()) else None,
        "estimated_salt_mass_kg": round(float(row["salt_thickness_mm"]) / 1000.0
                                        * SALT_BULK_DENSITY_KG_M3 * float(row["area_m2"]), 1),
    }