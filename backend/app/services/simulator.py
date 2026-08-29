"""Phase-9 what-if simulator: single-event rain impact for one salt pan.

The physics is deliberately transparent and deterministic (no trained models
required, so the simulator works for any registered pan):

* post-rain depth: current depth + rainfall / 10  (mm -> cm)
* post-rain salinity: mass-conserving dilution, salinity * depth / depth_after
  (identical to the digital-twin projections in `_derive_columns`)
* harvest delay: the longer of (salt dissolved by the storm — via the same
  `advance_pan_state` physics as the twin — re-grown at a dry deposition rate)
  and (the rainwater column evaporated at a pan-field rate)

Risk is a weighted blend of three dimensionless drivers, each 0..1:

    deluge   = rainfall / (2.5 * depth)          how large the event is vs the pan
    dilution = (salinity - salinity_after) / salinity
    flood    = (depth_after - safe_depth) / safe_depth

    score = 0.50 * deluge + 0.30 * dilution + 0.20 * flood   (clamped 0..1)

mapped to LOW (< 0.25) / MEDIUM (< 0.50) / HIGH (>= 0.50). The primary
recommended action mirrors the DSS advisory rules (harvest > store > protect >
monitor) keyed off the post-event risk and the current brine state.
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Optional

import numpy as np
from sqlalchemy.orm import Session

from app.models import Pan
from app.services.data_generator import advance_pan_state
from app.services.digital_twin import get_twin_state, normalise_state

RISK_LOW = "LOW"
RISK_MED = "MEDIUM"
RISK_HIGH = "HIGH"

# mm of salt deposit re-grown per fully dry day near saturation.
DEPOSIT_RATE_MM_DAY = 0.9
# pan-field evaporation rate used to guesstimate rain-column clearance (mm/day).
EVAP_RATE_MM_DAY = 7.0

RISK_DRIVER_WEIGHTS = {"deluge": 0.50, "dilution": 0.30, "flood": 0.20}


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def risk_to_text(score: float) -> str:
    if score >= 0.50:
        return RISK_HIGH
    if score >= 0.25:
        return RISK_MED
    return RISK_LOW


def rain_risk_score(salinity_g_l: float, depth_cm: float,
                    safe_depth_cm: float, rainfall_mm: float) -> float:
    """Deterministic 0..1 rain risk for a single event (see module docstring)."""
    depth = max(float(depth_cm), 0.1)
    safe = max(float(safe_depth_cm), 0.1)
    sal = max(float(salinity_g_l), 0.0)
    depth_after = max(depth + float(rainfall_mm) / 10.0, 0.1)
    sal_after = sal * depth / depth_after

    deluge = _clip(float(rainfall_mm) / (2.5 * depth), 0.0, 1.0)
    dilution = _clip((sal - sal_after) / sal, 0.0, 1.0) if sal > 0 else 0.0
    flood = _clip((depth_after - safe) / safe, 0.0, 1.0)

    return round(_clip(
        RISK_DRIVER_WEIGHTS["deluge"] * deluge
        + RISK_DRIVER_WEIGHTS["dilution"] * dilution
        + RISK_DRIVER_WEIGHTS["flood"] * flood,
        0.0, 1.0,
    ), 4)


def rain_dilution(salinity_g_l: float, depth_cm: float, rainfall_mm: float) -> dict:
    """Post-rain depth and salinity (identical conventions to the twin)."""
    depth_after = max(depth_cm + rainfall_mm / 10.0, 0.1)
    sal_after = salinity_g_l * depth_cm / depth_after
    return {
        "depth_after_cm": round(depth_after, 2),
        "salinity_after_g_l": round(max(0.0, min(sal_after, 350.0)), 1),
    }


def dissolved_salt_mm(state: dict, rainfall_mm: float, rng=None) -> float:
    """Salt-layer thickness dissolved by the storm (mm), via twin physics."""
    st = normalise_state(state)
    rng = rng or np.random.default_rng(0)
    rain_day = {
        "temperature_c": 28.0,
        "humidity_pct": 95.0,
        "wind_speed_kmh": 6.0,
        "sunshine_hours": 1.0,
        "rainfall_mm": float(rainfall_mm),
    }
    before = st["salt_thickness_mm"]
    after = advance_pan_state(dict(st), rain_day, 0.0, rng)["salt_thickness_mm"]
    return round(max(0.0, before - after), 2)


def harvest_delay_hours(state: dict, rainfall_mm: float) -> float:
    """Whole-day harvest setbacks the storm causes, in hours.

    The pan must (1) rebuild any salt the storm dissolved and (2) evaporate the
    rainwater column it dumped on the bed; the delay is the larger of the two.
    """
    dissolved = dissolved_salt_mm(state, rainfall_mm)
    rebuild_days = 0 if dissolved <= 0.01 else math.ceil(dissolved / DEPOSIT_RATE_MM_DAY)
    evap_days = math.ceil(max(0.0, rainfall_mm) / EVAP_RATE_MM_DAY)
    return float(max(rebuild_days, evap_days) * 24)


def recommend_action(salinity_g_l: float,
                     risk_after: str) -> str:
    """Primary advisory for the event, mirroring the DSS harvest>store>protect rules."""
    den = _clip(salinity_g_l / 9.5, 0.0, 30.0)
    crop_ready = salinity_g_l >= 260.0
    brine_concentrated = 18.0 <= den <= 28.0

    if risk_after == RISK_LOW:
        return "monitor"
    if crop_ready:
        return "harvest_now"
    if brine_concentrated:
        return "store_brine"
    return "protect_pan" if risk_after == RISK_HIGH else "monitor"


def simulate_rain(db: Session, pan: Pan, rainfall_mm: float) -> dict:
    """Compute the full before/after rain-impact snapshot for a pan."""
    st = normalise_state(get_twin_state(db, pan))
    area = float(pan.area_m2 or 1000.0)
    safe_depth = float(pan.safe_depth_cm or 12.0)
    depth = st["water_depth_cm"]
    salinity = float(st.get("salinity_g_l") or st["brine_density_be"] * 9.5)

    dilution = rain_dilution(salinity, depth, rainfall_mm)
    risk_before = rain_risk_score(salinity, depth, safe_depth, 0.0)
    risk_after = rain_risk_score(salinity, depth, safe_depth, rainfall_mm)
    risk_before_text = risk_to_text(risk_before)
    risk_after_text = risk_to_text(risk_after)

    delay_hours = harvest_delay_hours(dict(st), rainfall_mm)
    action = recommend_action(salinity, risk_after_text)

    return {
        "pan_id": pan.pan_code,
        "current_salinity_g_l": round(salinity, 1),
        "current_depth_cm": round(depth, 2),
        "current_volume_m3": round(depth / 100.0 * area, 2),
        "rainfall_mm": round(float(rainfall_mm), 1),
        "rain_volume_m3": round(float(rainfall_mm) / 1000.0 * area, 2),
        "predicted_depth_after_rain_cm": dilution["depth_after_cm"],
        "predicted_salinity_after_rain_g_l": dilution["salinity_after_g_l"],
        "risk_before": risk_before_text,
        "risk_after": risk_after_text,
        "predicted_harvest_delay_hours": delay_hours,
        "recommended_action": action,
        "recommendation": _message_for(
            action, salinity, dilution["salinity_after_g_l"],
            risk_before_text, risk_after_text, rainfall_mm,
        ),
    }


def _message_for(action: str, salinity: float, salinity_after: float,
                 risk_before: str, risk_after: str, rainfall_mm: float) -> str:
    if action == "harvest_now":
        return (
            f"Harvest the {round(salinity)} g/L salt bed before the rain: a "
            f"{round(rainfall_mm)} mm event would dilute it to {round(salinity_after)} g/L "
            f"and push risk from {risk_before} to {risk_after}. Protect the ready stockpiles."
        )
    if action == "store_brine":
        return (
            f"Store the concentrated mother brine before the storm: a {round(rainfall_mm)} mm "
            f"event dilutes it to {round(salinity_after)} g/L (risk {risk_after}). Pump it "
            f"into covered reserve beds until the weather clears."
        )
    if action == "protect_pan":
        return (
            f"Protect the pan against the {round(rainfall_mm)} mm event (risk climbs from "
            f"{risk_before} to {risk_after}, salinity would fall to {round(salinity_after)} g/L): "
            f"open drain outlets, cover stockpiles and pause new brine until it passes."
        )
    return (
        f"No urgent action needed at {round(rainfall_mm)} mm: risk stays {risk_after} and the "
        f"brine remains near {round(salinity_after)} g/L after the event. Keep monitoring."
    )