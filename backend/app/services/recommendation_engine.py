from __future__ import annotations

from typing import Dict, List, Optional

from app.services.digital_twin import normalise_state, progress_to_harvest


def _top_shap_text(shap_values: Optional[Dict[str, float]], kind: str, n: int = 3) -> str:
    if not shap_values:
        return ""
    items = sorted(shap_values.items(), key=lambda kv: abs(kv[1]), reverse=True)
    parts = [f"{k} {('+' if v >= 0 else '')}{v:.2f}" for k, v in items[:n]]
    return f"model inputs driving {kind}: " + ", ".join(parts)


def _confidence(readiness: float, risk: float) -> int:
    conf = 0.5 + readiness - max(0.0, risk)
    return int(round(max(35, min(97, conf * 100))))


def generate_recommendations(
    state: dict,
    timeline: List[dict],
    shap: Optional[Dict[str, Dict[str, float]]] = None,
    prediction: object = None,
    rainfall_mm_override: Optional[float] = None,
) -> List[dict]:
    """Rule-based decision support on top of ML scores, written for farmers.

    Returns structured recommendation dicts with `reasons` and `instructions`
    lists (the normalized payload) plus legacy display fields.
    """
    if not timeline:
        return []
    st = normalise_state(state)
    progress = progress_to_harvest(state)

    day0 = timeline[0]
    readiness0 = float(day0["readiness"])
    risk0 = float(day0["risk"])
    max_risk = max(float(p["risk"]) for p in timeline)
    max_risk_day = max(timeline, key=lambda p: p["risk"])
    max_rain_day = max(timeline, key=lambda p: p["rainfall_mm"])
    min_readiness = min(float(p["readiness"]) for p in timeline)
    rain_arrives = next((p for p in timeline if p["rainfall_mm"] > 0.5), None)
    harvest_setback = max(0.0, readiness0 - min_readiness)

    den = st["brine_density_be"]
    thick = st["salt_thickness_mm"]
    depth = st["water_depth_cm"]
    est_mass = int(st.get("estimated_salt_mass_kg") or 0)
    shap_ready = (shap or {}).get("harvest_readiness") or {}
    shap_risk = (shap or {}).get("climate_risk") or {}

    def base(code: str, title: str, risk_level: str, priority: int) -> dict:
        return {
            "recommendation_type": code,
            "title": title,
            "risk_level": risk_level,
            "priority": priority,
            "confidence_pct": _confidence(readiness0, max_risk),
            "reasons": [],
            "instructions": [],
        }

    recs: List[dict] = []
    shap_ready_text = _top_shap_text(shap_ready, "harvest readiness")
    shap_risk_text = _top_shap_text(shap_risk, "climate risk")

    # 1) Harvest now because high risk + ready crop
    if max_risk > 0.65 and readiness0 >= 0.55:
        r = base("harvest_now", "Harvest now before the rain", "high", 1)
        r["reasons"] = [
            f"Your salt bed is {int(readiness0 * 100)}% harvest-ready but climate risk peaks at "
            f"{int(max_risk * 100)}% on {max_risk_day['date']} "
            f"({max_risk_day['rainfall_mm']} mm forecast).",
            f"Rain on {max_risk_day['date']} would dissolve up to {int(thick * 0.5)} mm of the "
            f"~{thick} mm salt layer.",
            shap_risk_text or shap_ready_text or "Decision thresholds from the climate-risk model.",
        ]
        r["instructions"] = [
            f"Harvest today or before {max_risk_day['date']}.",
            "Mobilise labour and transport immediately.",
            "Move harvested salt under cover before the rain arrives.",
        ]
        r["expected_benefit"] = f"Protects up to {est_mass} kg of salt"
        r["message"] = (
            f"Harvest now: readiness {int(readiness0 * 100)}%, peak risk {int(max_risk * 100)}% "
            f"on {max_risk_day['date']}. Rain on the bed dissolves the {thick} mm layer."
        )
        recs.append(r)

    # 2) Schedule soon (readiness high, risk moderate/low)
    elif readiness0 >= 0.55:
        r = base("harvest_soon", "Schedule harvest in the next 1-2 days", "medium", 2)
        r["reasons"] = [
            f"Readiness is {int(readiness0 * 100)}% with the 7-day risk window peaking at "
            f"{int(max_risk * 100)}%.",
            "This is a good harvest window; labour and transport should be organised now.",
            shap_ready_text or "Crop maturity is within the harvest band.",
        ]
        r["instructions"] = [
            "Plan the harvest for the next clear, dry day.",
            "Line up labour, baskets and transport in advance.",
            "Re-check the forecast each morning before cutting.",
        ]
        r["expected_benefit"] = f"Captures the crop before events push readiness down by {int(harvest_setback * 100)}%"
        r["message"] = (
            f"Schedule harvest in the next 1-2 days: readiness {int(readiness0 * 100)}%, "
            f"peak risk {int(max_risk * 100)}%."
        )
        recs.append(r)

    # 3) Heavy rain days ahead / protection needed
    if max_risk > 0.55 or (rain_arrives and rain_arrives["rainfall_mm"] > 10):
        rain_day = max_rain_day
        r = base("protect_pan", "Protect the pan from incoming rain",
                 "high" if max_risk > 0.65 else "medium", 3)
        r["reasons"] = [
            f"{rain_day['rainfall_mm']} mm rain is forecast on {rain_day['date']}.",
            f"Forecast rain drives climate risk to {int(max_risk * 100)}%.",
            shap_risk_text or "Rain is the top driver of salt-bed loss this cycle.",
        ]
        r["instructions"] = [
            "Cover harvested stockpiles with tarpaulin.",
            "Open drain outlets so rainwater leaves the beds quickly.",
            "Stop adding brine to crystallising beds until the event passes.",
        ]
        r["expected_benefit"] = "Prevents dilution and re-dissolution of the salt layer"
        r["message"] = (
            f"Protect the pan from incoming rain: {rain_day['rainfall_mm']} mm on {rain_day['date']} "
            f"(risk {int(max_risk * 100)}%)."
        )
        recs.append(r)

    # 4) Not yet ready - keep crystallising
    if readiness0 < 0.55 and risk0 < 0.6:
        r = base("continue_evaporation", "Keep the brine crystallising", "low", 4)
        r["reasons"] = [
            f"The bed is at {int(readiness0 * 100)}% readiness "
            f"(density {den}°Bé, thickness {thick} mm).",
            "No rain action is required in the current window.",
            shap_ready_text or "Evaporation continues to thicken the salt layer.",
        ]
        r["instructions"] = [
            "Keep brine shallow and let evaporation continue.",
            "Re-check density daily.",
            "Re-run the forecast when the weather changes.",
        ]
        r["expected_benefit"] = f"Gains roughly {max(0, 100 - int(readiness0 * 100))}% toward harvest maturity"
        r["message"] = (
            f"Keep the brine crystallising: readiness {int(readiness0 * 100)}% "
            f"at {den}°Bé / {thick} mm."
        )
        recs.append(r)

    # 5) Dilute water sitting on top - pump it off
    if den < 18 and depth > 8 and readiness0 < 0.5 and risk0 < 0.6:
        r = base("pump_excess", "Pump away the dilute top water", "low", 5)
        r["reasons"] = [
            f"Brine density is only {den}°Bé at {depth} cm depth.",
            "Low density means evaporation is barely crystallising any salt.",
            "The dilute layer sits above the denser brine where salt forms.",
        ]
        r["instructions"] = [
            "Pump the diluted surface water into the reserve condensers.",
            "Let evaporation concentrate what remains.",
            "Monitor density daily until the crystallisation zone (>= 25°Bé).",
        ]
        r["expected_benefit"] = "Faster climb to the >=25°Bé crystallisation zone"
        r["message"] = f"Pump away the dilute top water: density {den}°Bé at {depth} cm depth."
        recs.append(r)

    # 6) Save concentrated brine before rain
    if rain_arrives and rain_arrives["rainfall_mm"] > 8 and 18 <= den < 28:
        r = base("store_brine", "Store the concentrated brine before the rain", "medium", 6)
        r["reasons"] = [
            f"{rain_arrives['rainfall_mm']} mm is expected on {rain_arrives['date']}.",
            f"The mother brine is {den}°Bé and would be diluted by the storm.",
            "Rain dilution is the main source of recovered-work loss.",
        ]
        r["instructions"] = [
            "Transfer the mother brine into covered reserve beds.",
            "Fill reserve capacity before the storm arrives.",
            "Return the brine to the crystallisers after the event.",
        ]
        r["expected_benefit"] = f"Protects ~{int(depth * den)} degree-cm of brine work"
        r["message"] = (
            f"Store the concentrated brine before the rain: {rain_arrives['rainfall_mm']} mm on "
            f"{rain_arrives['date']}, brine {den}°Bé."
        )
        recs.append(r)

    if not recs:
        r = base("monitor", "Pan is on track - keep monitoring", "low", 7)
        r["reasons"] = [
            f"Readiness is {int(readiness0 * 100)}% and risk {int(max_risk * 100)}% across the horizon.",
            "No urgent action is needed.",
            shap_ready_text or "Conditions are within the safe operating envelope.",
        ]
        r["instructions"] = [
            "Keep refreshing the forecast daily.",
            "Continue standard crystallisation checks.",
            "Review the twin state again next shift.",
        ]
        r["expected_benefit"] = "Stay ahead of sudden weather changes"
        r["message"] = (
            f"Pan is on track: readiness {int(readiness0 * 100)}%, "
            f"risk {int(max_risk * 100)}%."
        )
        recs.append(r)

    for rec in recs:
        while len(rec["reasons"]) < 3:
            rec["reasons"].append("")
        while len(rec["instructions"]) < 3:
            rec["instructions"].append("")
        rec["rationale"] = ". ".join(x for x in rec["reasons"] if x)
        rec["reason_1"], rec["reason_2"], rec["reason_3"] = (rec["reasons"] + [""] * 3)[:3]
        rec["instruction_1"], rec["instruction_2"], rec["instruction_3"] = (
            rec["instructions"] + [""] * 3)[:3]

    recs.sort(key=lambda r: r["priority"])
    return recs