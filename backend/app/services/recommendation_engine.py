from __future__ import annotations

from typing import Dict, List, Optional

from app.models import SaltPan, Prediction
from app.services.digital_twin import normalise_state, progress_to_harvest


def _top_shap_text(shap_values: Optional[Dict[str, float]], kind: str, n: int = 3) -> str:
    if not shap_values:
        return ""
    items = sorted(shap_values.items(), key=lambda kv: abs(kv[1]), reverse=True)
    parts = [f"{k} {('+' if v >= 0 else '')}{v:.2f}" for k, v in items[:n]]
    return f"model inputs driving {kind}: " + ", ".join(parts)


def generate_recommendations(
    pan: SaltPan,
    timeline: List[dict],
    shap: Optional[Dict[str, Dict[str, float]]] = None,
    prediction: Optional[Prediction] = None,
    rainfall_mm_override: Optional[float] = None,
) -> List[dict]:
    """Rule-based decision support on top of ML scores, written for farmers."""
    if not timeline:
        return []
    state = normalise_state(pan.twin_state)
    progress = progress_to_harvest(pan)

    day0 = timeline[0]
    readiness0 = float(day0["readiness"])
    risk0 = float(day0["risk"])
    max_risk = max(float(p["risk"]) for p in timeline)
    max_risk_day = max(timeline, key=lambda p: p["risk"])
    max_rain_day = max(timeline, key=lambda p: p["rainfall_mm"])
    min_readiness = min(float(p["readiness"]) for p in timeline)
    rain_arrives = next((p for p in timeline if p["rainfall_mm"] > 0.5), None)
    harvest_setback = max(0.0, readiness0 - min_readiness)

    den = state["brine_density_be"]
    thick = state["salt_thickness_mm"]
    depth = state["water_depth_cm"]
    shap_ready = (shap or {}).get("harvest_readiness") or {}
    shap_risk = (shap or {}).get("climate_risk") or {}

    recs: List[dict] = []

    # 1) Harvest now because high risk + ready crop
    if max_risk > 0.65 and readiness0 >= 0.55:
        recs.append({
            "recommendation_type": "harvest_now",
            "title": "Harvest now before the rain",
            "message": (
                f"Your salt bed is {int(readiness0 * 100)}% harvest-ready but climate risk peaks at "
                f"{int(max_risk * 100)}% on {max_risk_day['date']} ({max_risk_day['rainfall_mm']} mm forecast). "
                f"Harvesting now protects the crop; rain would dissolve up to "
                f"{int(thick * 0.5)} mm of the ~{thick} mm layer."
            ),
            "rationale": f"Risk on {max_risk_day['date']} exceeds the safe threshold while readiness is high. " +
                         _top_shap_text(shap_risk, "climate risk") + ". " +
                         _top_shap_text(shap_ready, "harvest readiness"),
            "expected_benefit": f"Protects up to {int(state.get('estimated_salt_mass_kg', 0))} kg of salt",
            "risk_level": "high",
            "priority": 1,
        })

    # 2) Schedule soon (readiness high, risk moderate/low)
    elif readiness0 >= 0.55:
        recs.append({
            "recommendation_type": "harvest_soon",
            "title": "Schedule harvest in the next 1–2 days",
            "message": (
                f"Readiness is {int(readiness0 * 100)}% and the 7-day risk window stays at "
                f"{int(max_risk * 100)}%. This is a good harvest window - organise labour and "
                f"transport for the next clear days."
            ),
            "rationale": _top_shap_text(shap_ready, "harvest readiness"),
            "expected_benefit": "Captures the crop before events push readiness down by "
                                f"{int(harvest_setback * 100)}%",
            "risk_level": "medium",
            "priority": 2,
        })

    # 3) Heavy rain days ahead / protection needed
    if max_risk > 0.55 or (rain_arrives and rain_arrives["rainfall_mm"] > 10):
        rain_day = max_rain_day
        recs.append({
            "recommendation_type": "protect_pan",
            "title": "Protect the pan from incoming rain",
            "message": (
                f"{rain_day['rainfall_mm']} mm rain is forecast on {rain_day['date']}. "
                f"Cover any harvested stockpiles with tarpaulin, open drain outlets so rainwater "
                f"leaves quickly, and stop adding brine to the crystallising beds until it passes."
            ),
            "rationale": f"Forecast rainfall of {rain_day['rainfall_mm']} mm on {rain_day['date']} driving risk to "
                         f"{int(max_risk * 100)}%. " + _top_shap_text(shap_risk, "climate risk"),
            "expected_benefit": "Prevents dilution and re-dissolution of the salt layer",
            "risk_level": "high" if max_risk > 0.65 else "medium",
            "priority": 3,
        })

    # 4) Not yet ready - keep crystallising
    if readiness0 < 0.55 and risk0 < 0.6:
        recs.append({
            "recommendation_type": "continue_evaporation",
            "title": "Keep the brine crystallising",
            "message": (
                f"The bed is at {int(readiness0 * 100)}% readiness (density {den}°Bé, "
                f"thickness {thick} mm). Keep brine shallow and let evaporation continue; "
                f"re-check density daily. No rain action needed for now."
            ),
            "rationale": f"Readiness beneath target. " + _top_shap_text(shap_ready, "harvest readiness"),
            "expected_benefit": f"Gains roughly {max(0.0, 100 - int(readiness0 * 100))}% toward harvest maturity",
            "risk_level": "low",
            "priority": 4,
        })

    # 5) Dilute water sitting on top - pump it off
    if den < 18 and depth > 8 and readiness0 < 0.5 and risk0 < 0.6:
        recs.append({
            "recommendation_type": "pump_excess",
            "title": "Pump away the dilute top water",
            "message": (
                f"Brine density is only {den}°Bé at {depth} cm depth. Pump the diluted surface water "
                f"into the reserve condensers so evaporation can concentrate what remains."
            ),
            "rationale": "Low brine density means evaporation is barely crystallising any salt.",
            "expected_benefit": "Faster climb to the ≥25°Bé crystallisation zone",
            "risk_level": "low",
            "priority": 5,
        })

    # 6) Save concentrated brine before rain
    if rain_arrives and rain_arrives["rainfall_mm"] > 8 and 18 <= den < 28:
        recs.append({
            "recommendation_type": "store_brine",
            "title": "Store the concentrated brine before the rain",
            "message": (
                f"{rain_arrives['rainfall_mm']} mm is expected on {rain_arrives['date']}. "
                f"Transfer the {den}°Bé mother brine into covered reserve beds so the storm "
                f"cannot dilute the weeks of concentration you already paid for."
            ),
            "rationale": "Rain-related dilution is the main source of recovered-work loss.",
            "expected_benefit": f"Protects ~{int(depth * den)} degree-cm of brine work",
            "risk_level": "medium",
            "priority": 6,
        })

    if not recs:
        recs.append({
            "recommendation_type": "monitor",
            "title": "Pan is on track — keep monitoring",
            "message": (
                f"Readiness {int(readiness0 * 100)}%, risk {int(max_risk * 100)}% over the horizon. "
                f"No urgent action needed; refresh the forecast daily."
            ),
            "rationale": _top_shap_text(shap_ready, "harvest readiness"),
            "expected_benefit": "Stay ahead of sudden weather changes",
            "risk_level": "low",
            "priority": 7,
        })

    recs.sort(key=lambda r: r["priority"])
    return recs