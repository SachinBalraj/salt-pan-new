"""Serializers: map normalized DB rows back to the legacy v1 API contract.

The API surface consumed by the frontend and tests is preserved while
persistence uses the Phase-2 normalized schema. Legacy-only fields live in
JSON columns (`input_snapshot_json`, `details_json`, twin `state_json`) and
are reconstructed here deterministically.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, Optional

from app.models import (
    DigitalTwinState,
    HarvestOutcome,
    ModelVersion,
    Pan,
    Prediction,
    Recommendation,
)
from app.services.digital_twin import default_twin_state, get_twin_state

PAN_STATUS = "active"

REC_TITLES = {
    "harvest_now": "Harvest now before the rain",
    "harvest_soon": "Schedule harvest in the next 1-2 days",
    "protect_pan": "Protect the pan from incoming rain",
    "continue_evaporation": "Keep the brine crystallising",
    "pump_excess": "Pump away the dilute top water",
    "store_brine": "Store the concentrated brine before the rain",
    "monitor": "Pan is on track - keep monitoring",
}

REC_BENEFITS = {
    "harvest_now": "Protects the ready-to-harvest crop from rain damage",
    "harvest_soon": "Captures the crop at peak maturity",
    "protect_pan": "Prevents dilution and re-dissolution of the salt layer",
    "continue_evaporation": "Progression toward harvest maturity",
    "pump_excess": "Faster climb to the crystallisation zone",
    "store_brine": "Protects concentrated-brine work from the storm",
    "monitor": "Stays ahead of sudden weather changes",
}


def _risk_level_from(action: str, confidence_pct: float) -> str:
    fixed = {
        "harvest_now": "high",
        "protect_pan": "high" if confidence_pct >= 60 else "medium",
        "harvest_soon": "medium",
        "store_brine": "medium",
        "pump_excess": "low",
        "continue_evaporation": "low",
        "monitor": "low",
    }
    return fixed.get(action, "low")


# ------------------------------------------------------------------ Pan / twin
def pan_state(db, pan: Pan) -> dict:
    st = get_twin_state(db, pan)
    return st or default_twin_state()


def pan_to_dict(db, pan: Pan) -> dict:
    st = pan_state(db, pan)
    st.setdefault("location", pan.name)
    return {
        "id": pan.id,
        "pan_id": pan.pan_code,
        "name": pan.name,
        "location": st.get("location", ""),
        "latitude": pan.latitude,
        "longitude": pan.longitude,
        "area_m2": pan.area_m2,
        "status": PAN_STATUS,
        "twin_state": st,
        "created_at": pan.created_at,
        "updated_at": pan.updated_at,
    }


def twin_snapshot_to_dict(row: DigitalTwinState) -> dict:
    state = dict(row.state_json or {})
    return {
        "id": row.id,
        "pan_id": row.pan_id,
        "snapshot_date": state.get("last_update", row.timestamp.date().isoformat()),
        "source": str(state.get("_source", "manual")),
        "state": state,
        "created_at": row.created_at,
    }


# ------------------------------------------------------------------ Predictions
def _snapshot(pred: Prediction) -> dict:
    return dict(pred.input_snapshot_json or {})


def prediction_run_to_dict(pred: Prediction, pan: Pan) -> dict:
    snap = _snapshot(pred)
    series = snap.get("series") or []
    return {
        "id": pred.id,
        "pan_id": pan.id,
        "pan_ref": pan.pan_code,
        "state": snap.get("state") or {},
        "day0": series[0] if series else {},
        "max_risk": snap.get("max_risk", 0.0),
        "min_readiness": snap.get("min_readiness", 0.0),
        "projected_yield_kg": snap.get("projected_yield_kg", 0.0),
        "shap": pred.shap_values_json or {},
        "series": series,
        "created_at": pred.created_at.isoformat(),
        "scenario": snap.get("scenario", "actual_forecast"),
    }


def prediction_record_to_dict(pred: Prediction) -> dict:
    snap = _snapshot(pred)
    return {
        "id": pred.id,
        "pan_id": pred.pan_id,
        "model_id": pred.model_version_id,
        "prediction_type": snap.get("prediction_type", "combined"),
        "scenario": snap.get("scenario", "actual_forecast"),
        "score": snap.get("score", pred.harvest_probability),
        "horizon_days": snap.get("horizon_days", 7),
        "prediction_date": snap.get("prediction_date", ""),
        "forecast_date": snap.get("forecast_date", ""),
        "features": snap.get("features", {}),
        "shap_values": pred.shap_values_json or {},
        "series": snap.get("series", []),
        "created_at": pred.created_at.isoformat(),
        "timestamp": pred.timestamp,
        "risk_level": pred.risk_level,
        "harvest_ready": pred.harvest_ready,
    }


def make_prediction_row(
    db,
    pan: Pan,
    *,
    state: dict,
    series: list,
    models: dict,
    shap: Optional[Dict[str, Dict[str, float]]],
    scenario: str,
    horizon_days: int,
    model_version: Optional[ModelVersion] = None,
    proj_yield: Optional[float] = None,
) -> Prediction:
    """Build+return an uncommitted Prediction row from scored data."""
    day0 = series[0]
    max_risk = round(max(float(p["risk"]) for p in series), 4)
    min_ready = round(min(float(p["readiness"]) for p in series), 4)
    readiness0 = float(day0["readiness"])
    proj_yield = round(float(proj_yield if proj_yield is not None
                             else (state.get("estimated_salt_mass_kg") or 0.0)), 1)
    today = dt.date.today().isoformat()

    risk_level = "high" if max_risk > 0.65 else ("medium" if max_risk > 0.4 else "low")
    confidence = round(min(99.0, max(10.0, 100.0 - 40.0 * max_risk - 30.0 * (1 - readiness0))), 1)
    hours = None
    if readiness0 < 0.55:
        for i, p in enumerate(series[1:], start=1):
            if float(p["readiness"]) >= 0.55:
                hours = round(float(i) * 24.0, 1)
                break

    snapshot = {
        "prediction_type": "combined",
        "scenario": scenario,
        "score": round(readiness0, 4),
        "horizon_days": horizon_days,
        "prediction_date": today,
        "forecast_date": day0["date"],
        "features": {
            **day0_features_dict(state, series, models),
            "projected_yield_kg": proj_yield,
            "max_risk_horizon": max_risk,
            "min_readiness_horizon": min_ready,
        },
        "series": series,
        "max_risk": max_risk,
        "min_readiness": min_ready,
        "projected_yield_kg": proj_yield,
        "state": state,
        "pan_ref": pan.pan_code,
    }

    pred = Prediction(
        pan_id=pan.id,
        model_version_id=model_version.id if model_version else None,
        risk_level=risk_level,
        risk_probability=max_risk,
        harvest_ready=readiness0 >= 0.55,
        harvest_probability=readiness0,
        predicted_harvest_hours=hours,
        predicted_yield_kg=proj_yield,
        confidence_pct=confidence,
        input_snapshot_json=snapshot,
        shap_values_json=shap or {},
    )
    return pred


def day0_features_dict(state: dict, series: list, models: dict) -> dict:
    """Best-effort feature set for a saved prediction snapshot."""
    from app.services.predictor import day0_features

    day0_w = dict(series[0]) if series else {}
    day0_w["temperature_c"] = day0_w.get("temperature_c", 28.0)
    day0_w["humidity_pct"] = day0_w.get("humidity_pct", 60.0)
    day0_w["wind_speed_kmh"] = day0_w.get("wind_speed_kmh", 10.0)
    day0_w["sunshine_hours"] = day0_w.get("sunshine_hours", 9.0)
    day0_w["rainfall_mm"] = day0_w.get("rainfall_mm", 0.0)
    forecast_days = [day0_w]
    try:
        fd = day0_features(state, forecast_days, "harvest_readiness")
        fdr = day0_features(state, forecast_days, "climate_risk")
        return {**fd, **fdr}
    except Exception:
        return {}


# ------------------------------------------------------------------ Recommendations
def recommendation_to_dict(rec: Recommendation, farmer_notes: str = "") -> dict:
    reasons = [rec.reason_1, rec.reason_2, rec.reason_3]
    instructions = [rec.instruction_1, rec.instruction_2, rec.instruction_3]
    action = rec.recommended_action
    title = REC_TITLES.get(action, action.replace("_", " ").title())
    message = _build_message(action, reasons, instructions, rec.confidence_pct)
    rationale = ". ".join(r for r in reasons if r)
    benefit = ""
    if action == "harvest_now":
        benefit = f"Protects up to {_extract_kg(rec.reason_1)} of salt"
    elif action in REC_BENEFITS:
        benefit = REC_BENEFITS[action]
    return {
        "id": rec.id,
        "pan_id": rec.pan_id,
        "prediction_id": rec.prediction_id,
        "recommendation_type": action,
        "title": title,
        "message": message,
        "rationale": rationale,
        "expected_benefit": benefit,
        "risk_level": _risk_level_from(action, rec.confidence_pct),
        "status": rec.status,
        "farmer_notes": farmer_notes,
        "created_at": rec.created_at,
        "responded_at": rec.operator_response_at,
        "confidence_pct": rec.confidence_pct,
        "action_deadline": rec.action_deadline,
        "reasons": reasons,
        "instructions": instructions,
    }


def _extract_kg(text: str) -> str:
    import re

    m = re.search(r"[0-9][0-9,]*", text)
    return m.group(0) if m else "0"


def _build_message(action: str, reasons: List[str], instructions: List[str],
                   confidence_pct: float) -> str:
    if action == "harvest_now":
        lead = reasons[0] if reasons and reasons[0] else "Harvest before the rain arrives."
        step = instructions[0] if instructions and instructions[0] \
            else "Move the crop under cover before the rain."
        return f"{lead} {step}"
    if action == "harvest_soon":
        lead = reasons[0] if reasons and reasons[0] else "A good harvest window is open."
        step = instructions[0] if instructions and instructions[0] \
            else "Schedule the harvest for the next clear day."
        return f"{lead} {step}"
    if action == "protect_pan":
        lead = reasons[0] if reasons and reasons[0] else "Rain is forecast for the window."
        step = instructions[0] if instructions and instructions[0] \
            else "Protect stockpiles and open the drains."
        return f"{lead} {step}"
    if action in ("store_brine", "pump_excess", "continue_evaporation", "monitor"):
        lead = reasons[0] if reasons and reasons[0] else "No urgent action is required."
        step = instructions[0] if instructions and instructions[0] \
            else "Continue standard checks."
        return f"{lead} {step}"
    return " ".join(r for r in reasons if r)


# ------------------------------------------------------------------ Outcomes
def outcome_to_dict(out: HarvestOutcome) -> dict:
    details = dict(out.details_json or {})
    harvest_date = out.harvest_date or details.get("outcome_date", "")
    return {
        "id": out.id,
        "pan_id": out.pan_id,
        "prediction_id": out.prediction_id,
        "recommendation_id": out.recommendation_id,
        "outcome_date": harvest_date,
        "actual_rainfall_mm": out.actual_rainfall_mm if out.actual_rainfall_mm is not None else 0.0,
        "risk_occurred": bool(out.rain_damage),
        "action_taken": str(details.get("action_taken", "")),
        "harvest_date": details.get("harvest_date") or harvest_date,
        "harvest_delayed_days": details.get("harvest_delayed_days"),
        "actual_yield_kg": out.actual_yield_kg,
        "brine_density_be": details.get("brine_density_be"),
        "salt_thickness_mm": details.get("salt_thickness_mm"),
        "rain_damage": out.rain_damage,
        "yield_loss_pct": out.yield_loss_pct,
        "verified": out.verified,
        "verified_at": out.verified_at,
        "notes": out.outcome_notes,
        "feedback_ingested": out.feedback_ingested,
        "created_at": out.created_at,
    }


# ------------------------------------------------------------------ Models
def model_to_dict(mv: ModelVersion) -> dict:
    return {
        "id": mv.id,
        "name": mv.model_name,
        "kind": mv.model_type,
        "version": mv.version,
        "status": "active" if mv.active else "trained",
        "feature_names": mv.feature_names_json or [],
        "metrics": mv.metrics_json or {},
        "rows_trained": mv.training_rows,
        "dataset_id": None,
        "model_path": mv.model_path,
        "uses_proxy_labels": mv.uses_proxy_labels,
        "created_at": mv.created_at,
    }