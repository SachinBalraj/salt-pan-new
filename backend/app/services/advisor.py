"""Phase-11 rule-based recommendation + safety engine.

The advisor fuses four sources into a single typed *facts* record:

* the digital-twin state (depth, density, salt bed, safe depth, storage),
* the Random-Forest predictions (harvest readiness, climate-risk timeline),
* the Phase-9 what-if rain simulator (post-rain depth / salinity / delay),
* the Phase-10 SHAP explanations (human factors, used for context only here).

It then evaluates the YAML `recommendation_rules.yaml` rule set in priority
order. The first matching rule wins and becomes the *primary* recommendation;
all matches are returned so the farmer sees the full safety picture. Physical
actions are never triggered directly - every recommendation is persisted with
`requires_farmer_confirmation: true` and only becomes an operator record after
the farmer accepts it via `POST /api/recommendations/{id}/accept`.
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.config.recommendation_rules import (
    get_rules,
    get_thresholds,
    rules_signature,
)
from app.models import Pan, Prediction, Recommendation
from app.services.digital_twin import get_twin_state
from app.services.explainability import build_explanation
from app.services.predictor import day0_features, local_shap_values, scored_timeline
from app.services.serializers import make_prediction_row
from app.services.simulator import simulate_rain

# ------------------------------------------------------------------ conditions
_OPS = ("==", "!=", ">=", "<=", ">", "<")


def _split_condition(text: str) -> tuple:
    body = str(text).strip()
    for op in _OPS:
        if op in body:
            left, _, right = body.partition(op)
            return left.strip(), op, right.strip()
    raise ValueError(f"Unsupported condition (no operator): {text!r}")


def _coerce(token: str) -> Any:
    """Parse a condition token into a typed literal or a fact reference."""
    t = token.strip()
    low = t.lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return float(t)
    except ValueError:
        return t


def _resolve(value: Any, facts: Dict[str, Any]) -> Any:
    if isinstance(value, str) and value in facts:
        return facts[value]
    return value


def evaluate_condition(condition: str, facts: Dict[str, Any]) -> bool:
    fact, op, raw = _split_condition(condition)
    left = _resolve(_coerce(fact), facts)
    right = _resolve(_coerce(raw), facts)
    if op == "!=" and left is not None and right is not None:
        return left != right
    if left is None or right is None:
        return False
    if op == "==":
        return left == right
    if op == ">=":
        return left >= right
    if op == "<=":
        return left <= right
    if op == ">":
        return left > right
    if op == "<":
        return left < right
    return False  # pragma: no cover - all ops handled above


def matched_rules(facts: Dict[str, Any], rules: Optional[List[dict]] = None) -> List[dict]:
    """All rules whose conditions hold, in priority (declared) order."""
    rules = rules if rules is not None else get_rules()
    out = []
    for rule in sorted(rules, key=lambda r: int(r.get("priority", 99))):
        conditions = rule.get("conditions") or []
        if all(evaluate_condition(c, facts) for c in conditions):
            out.append(rule)
    return out


# ------------------------------------------------------------------ facts
def _salinity(state: dict) -> float:
    try:
        return float(state.get("salinity_g_l") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def build_facts(pan: Pan, state: dict, timeline: List[dict],
                rain_sim: dict, day0: dict, forecast_days: List[dict],
                thresholds: dict) -> Dict[str, Any]:
    """Collapse twin + ML + what-if + forecast into one typed fact record."""
    density = float(state.get("brine_density_be") or 0.0)
    sal = _salinity(state) or round(density * 9.5, 1)
    depth = float(state.get("water_depth_cm") or 0.0)
    safe_depth = float(pan.safe_depth_cm or 12.0)
    storage = bool(pan.safe_storage_available)
    readiness0 = float(timeline[0]["readiness"])
    max_risk = max(float(p["risk"]) for p in timeline)
    ready_threshold = float(thresholds.get("harvest_ready_threshold", 0.55))
    risk_high = float(thresholds.get("risk_high", 0.65))
    risk_medium = float(thresholds.get("risk_medium", 0.40))
    sal_min = float(thresholds.get("harvest_salinity_min_g_l", 230.0))
    sal_max = float(thresholds.get("harvest_salinity_max_g_l", 300.0))
    rain_day_mm = float(thresholds.get("rain_day_mm", 0.5))

    rain_24h = float(day0.get("rainfall_mm", 0.0))
    rain_prob = float(day0.get("precipitation_probability_pct", 0.0))
    rain_7d = round(sum(float(p.get("rainfall_mm", 0.0)) for p in timeline), 1)
    rain_days = [p for p in timeline if float(p.get("rainfall_mm", 0.0)) >= rain_day_mm]
    first_rain = min(rain_days, key=lambda p: str(p["date"])) if rain_days else None
    next_rain_date = str(first_rain["date"]) if first_rain else None

    sal_after = float(rain_sim.get("predicted_salinity_after_g_l", sal))
    depth_after = float(rain_sim.get("predicted_depth_after_rain_cm", depth))
    sal_drop = round(sal - sal_after, 1)

    if max_risk >= risk_high:
        risk_level = "HIGH"
    elif max_risk >= risk_medium:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    return {
        # twin state
        "salinity_g_l": round(sal, 1),
        "brine_density_be": round(density, 2),
        "water_depth_cm": round(depth, 2),
        "salt_thickness_mm": round(float(state.get("salt_thickness_mm") or 0.0), 2),
        "days_since_last_rain": int(state.get("days_since_last_rain") or 0),
        "estimated_salt_mass_kg": state.get("estimated_salt_mass_kg"),
        "safe_depth_cm": safe_depth,
        "safe_storage_available": storage,
        # ml predictions
        "harvest_readiness": round(readiness0, 4),
        "harvest_ready": readiness0 >= ready_threshold,
        "max_risk": round(max_risk, 4),
        "risk_level": risk_level,
        # forecast
        "rain_24h_mm": round(rain_24h, 1),
        "rain_7d_mm": rain_7d,
        "rain_probability_pct": round(rain_prob, 1),
        "next_rain_date": next_rain_date,
        "horizon_days": len(timeline) or 7,
        # what-if rain simulation
        "predicted_depth_after_rain_cm": round(depth_after, 2),
        "predicted_salinity_after_rain_g_l": round(sal_after, 1),
        "salinity_drop_g_l": sal_drop,
        "predicted_harvest_delay_hours": float(rain_sim.get("predicted_harvest_delay_hours", 0.0)),
        "rain_risk_after": str(rain_sim.get("risk_after", "LOW")),
        # derived
        "salinity_in_harvest_range": sal_min <= sal <= sal_max,
        "brine_concentrated": 18.0 <= density <= 28.0,
        "depth_overflow": depth_after > safe_depth,
    }


# ------------------------------------------------------------------ deadlines
def _to_datetime(value: Any) -> dt.datetime:
    try:
        return dt.datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return dt.datetime.utcnow()


def action_deadline(facts: Dict[str, Any], thresholds: dict) -> dt.datetime:
    """The farmer-facing deadline: the target rain day (or soonest sensible
    day) at the configured time of day (e.g. 18:00)."""
    deadline_time = str(thresholds.get("deadline_time", "18:00"))
    try:
        hour, minute = (int(deadline_time.split(":")[0]), int(deadline_time.split(":")[1]))
    except (ValueError, IndexError):
        hour, minute = 18, 0
    now = dt.datetime.utcnow()
    target_day = facts.get("next_rain_date")
    if target_day:
        base = dt.date.fromisoformat(str(target_day))
    else:
        base = dt.date.today()
    deadline = dt.datetime.combine(base, dt.time(min(hour, 23), min(minute, 59)))
    return deadline if deadline > now else deadline + dt.timedelta(days=1)


def _clock(d: dt.datetime) -> str:
    h = d.hour % 12 or 12
    return f"{h}:{d.minute:02d} {d.strftime('%p')}"


def _when(d: dt.datetime) -> str:
    base = f"{_clock(d)}"
    if d.date() != dt.date.today():
        return f"{d.date():%b %d} at {base}"
    return f"before {base}"


# ------------------------------------------------------------------ narrative
HUMAN_IN_LOOP_NOTE = (
    "The model never operates pumps, gates or drainage automatically. "
    "Every physical action requires farmer confirmation."
)


def _fmt(x: Any, places: int = 0) -> str:
    try:
        return f"{float(x):.{places}f}"
    except (TypeError, ValueError):
        return str(x)


def _render_reasons(action: str, facts: Dict[str, Any], thresholds: dict) -> List[str]:
    sal = facts["salinity_g_l"]
    sal_min = _fmt(thresholds.get("harvest_salinity_min_g_l", 230.0))
    sal_max = _fmt(thresholds.get("harvest_salinity_max_g_l", 300.0))
    rain = facts["rain_24h_mm"]
    prob = facts["rain_probability_pct"]
    sal_after = facts["predicted_salinity_after_rain_g_l"]
    depth_after = facts["predicted_depth_after_rain_cm"]
    safe = facts["safe_depth_cm"]
    density = facts["brine_density_be"]
    next_rain = facts["next_rain_date"] or "the forecast window"

    if action == "HARVEST_NOW":
        return [
            f"Current salinity ({_fmt(sal)} g/L) is in the configured harvest-ready range ({sal_min}-{sal_max} g/L).",
            f"The probability of rainfall is {_fmt(prob)}%.",
            f"{_fmt(rain)} millimetres of rain may reduce salinity from {_fmt(sal)} to {_fmt(sal_after)} g/L.",
        ]
    if action == "TRANSFER_BRINE":
        return [
            f"The brine is concentrated (density {_fmt(density, 1)}°Bé) and ready to store.",
            f"Rain risk is HIGH ({_fmt(rain)} mm forecast nearby).",
            "Safe storage is currently available.",
        ]
    if action == "PROTECT_OR_DRAIN":
        return [
            f"The water depth after rain ({_fmt(depth_after)} cm) would exceed the safe depth of {_fmt(safe)} cm.",
            f"{_fmt(rain)} mm of rain is forecast for {next_rain}.",
            f"Without action salinity would fall to {_fmt(sal_after)} g/L.",
        ]
    # WAIT_AND_RECHECK
    return [
        f"Rain risk is LOW over the next {_fmt(facts['horizon_days'])} days.",
        "The crop is not yet ready for harvest.",
        f"Current salinity is {_fmt(sal)} g/L; the harvest band starts at {sal_min} g/L.",
    ]


def _render_steps(action: str, facts: Dict[str, Any], thresholds: dict) -> List[str]:
    sal_min = _fmt(thresholds.get("harvest_salinity_min_g_l", 230.0))
    if action == "HARVEST_NOW":
        return [
            "Begin harvesting the crystallised salt on the confirmed area.",
            "Move the collected salt to protected storage before the rain.",
            "Close the inlet gate before the rainfall arrives.",
            "Recheck salinity and water depth after the rain.",
        ]
    if action == "TRANSFER_BRINE":
        return [
            "Open the outlet valve to route brine into the reserve beds.",
            "Confirm the pump start and monitor the transferred volume.",
            "Seal the reserve beds once the transfer completes.",
            "Stop the pump and confirm completion on the dashboard.",
        ]
    if action == "PROTECT_OR_DRAIN":
        return [
            "Open the drain outlets to release excess water before the event.",
            "Cover stockpiles and any harvested salt with tarpaulin.",
            "Stop adding new brine until the weather clears.",
            "Confirm the position is ready and recheck after the rain.",
        ]
    return [
        "Record a field salinity and depth reading daily.",
        "Refresh the forecast each morning.",
        "Generate a new prediction if the forecast changes materially.",
        f"Plan the harvest when salinity crosses {sal_min} g/L.",
    ]


def _render_consequence(action: str, facts: Dict[str, Any]) -> str:
    sal = facts["salinity_g_l"]
    sal_drop = facts["salinity_drop_g_l"]
    delay = facts["predicted_harvest_delay_hours"]
    depth_after = facts["predicted_depth_after_rain_cm"]
    safe = facts["safe_depth_cm"]
    if action == "HARVEST_NOW":
        return (f"If you wait, the incoming rain can cost up to {_fmt(sal_drop)} g/L of "
                f"salinity and delay the harvest by up to {_fmt(delay)} hours.")
    if action == "TRANSFER_BRINE":
        return (f"Keeping the concentrated brine exposed to rain undoes the concentration "
                f"work: salinity falls towards {_fmt(facts['predicted_salinity_after_rain_g_l'])} g/L.")
    if action == "PROTECT_OR_DRAIN":
        return (f"Without protection the pan floods to {_fmt(depth_after)} cm (safe limit "
                f"{_fmt(safe)} cm) and the salt bed re-dissolves.")
    return "The main risk is a fast-changing forecast; the next check is the safety net."


def _render_instruction(action: str, pan: Pan, facts: Dict[str, Any],
                        deadline: dt.datetime) -> str:
    ref = pan.pan_code
    if action == "HARVEST_NOW":
        return f"Harvest {ref} {_when(deadline)}."
    if action == "TRANSFER_BRINE":
        return f"Transfer the concentrated brine from {ref} to safe storage {_when(deadline)}."
    if action == "PROTECT_OR_DRAIN":
        return f"Protect {ref} or drain the excess water {_when(deadline)}."
    return f"Keep monitoring {ref}; recheck the forecast {_when(deadline)}."


def render_card(pan: Pan, pred: Prediction, rule: dict, facts: Dict[str, Any],
                thresholds: dict, confidence_pct: float) -> dict:
    action = rule["action"]
    deadline = action_deadline(facts, thresholds)
    reasons = _render_reasons(action, facts, thresholds)
    steps = _render_steps(action, facts, thresholds)
    instruction = _render_instruction(action, pan, facts, deadline)
    return {
        "id": pred.id,
        "pan_id": pan.id,
        "pan_ref": pan.pan_code,
        "prediction_id": pred.id,
        "recommendation_type": action,
        "rule_id": rule.get("id"),
        "class": rule.get("class", "advisory"),
        "title": rule.get("name", action.replace("_", " ").title()),
        "instruction": instruction,
        "action_deadline": deadline.isoformat(),
        "reasons": reasons,
        "instructions": steps,
        "confidence_pct": confidence_pct,
        "consequence_if_waited": _render_consequence(action, facts),
        "risk_level": facts["risk_level"].lower(),
        "requires_farmer_confirmation": bool(rule.get("requires_farmer_confirmation", True)),
        "safety_note": HUMAN_IN_LOOP_NOTE,
        "status": "pending",
        "created_at": dt.datetime.utcnow().isoformat(),
    }


def persist_card(db: Session, pan: Pan, pred: Prediction, card: dict,
                 timeline: List[dict]) -> Recommendation:
    deadline = card.get("action_deadline")
    try:
        deadline_dt = dt.datetime.fromisoformat(str(deadline))
    except (TypeError, ValueError):
        from app.routers.recommendations import _deadline

        deadline_dt = _deadline(card["recommendation_type"], timeline)
    reasons = card["reasons"]
    steps = card["instructions"]
    rec = Recommendation(
        recommendation_code=f"{card['recommendation_type'][:18]}-{pan.pan_code}",
        pan_id=pan.id,
        prediction_id=pred.id,
        timestamp=dt.datetime.utcnow(),
        recommended_action=card["recommendation_type"],
        action_deadline=deadline_dt,
        reason_1=reasons[0] if reasons else "",
        reason_2=reasons[1] if len(reasons) > 1 else "",
        reason_3=reasons[2] if len(reasons) > 2 else "",
        instruction_1=steps[0] if steps else "",
        instruction_2=steps[1] if len(steps) > 1 else "",
        instruction_3=steps[2] if len(steps) > 2 else "",
        confidence_pct=card["confidence_pct"],
        consequence_if_waited=card.get("consequence_if_waited", ""),
        status="pending",
    )
    db.add(rec)
    return rec


# ------------------------------------------------------------------ orchestration
def run_advice(db: Session, pan: Pan, horizon_days: int = 7) -> dict:
    """Full advisor pipeline: forecast -> score -> explain -> simulate -> rule
    evaluation -> persist prediction + recommendations -> bundle. Returns a
    dict (no FastAPI dependency) so it can be driven by any router."""
    from app.config import get_settings
    from app.routers.predictions import load_models, resolve_forecast

    settings = get_settings()
    thresholds = get_thresholds()

    state = get_twin_state(db, pan)
    f_days = resolve_forecast(db, pan, horizon_days)
    models, _versions = load_models(db, settings)

    start_date = state.get("demo_today") or dt.date.today().isoformat()
    timeline = scored_timeline(state, f_days, models, start_date=start_date)

    shap = {}
    for kind in ("harvest_readiness", "climate_risk"):
        fd = day0_features(state, f_days, kind)
        shap[kind] = local_shap_values(models[kind], list(fd.values()), list(fd.keys()))

    explain = build_explanation(state, f_days, models, shap)
    pred = make_prediction_row(
        db, pan, state=state, series=timeline, models=models, shap=shap,
        explain=explain, scenario="actual_forecast", horizon_days=horizon_days,
        model_version=_versions["harvest_readiness"],
    )
    db.add(pred)
    db.flush()

    day0 = dict(timeline[0])
    # the event the farmer must plan for: the largest rain within the horizon.
    event_mm = max([float(p.get("rainfall_mm", 0.0)) for p in timeline] or [0.0])
    event_mm = max(event_mm, float(day0.get("rainfall_mm", 0.0)))
    rain_sim = simulate_rain(db, pan, event_mm)

    facts = build_facts(pan, state, timeline, rain_sim, day0, f_days, thresholds)
    rules = matched_rules(facts)

    max_risk = facts["max_risk"]
    readiness0 = facts["harvest_readiness"]
    confidence = round(min(99.0, max(10.0, 100.0 - 40.0 * max_risk - 30.0 * (1 - readiness0))), 1)

    cards: List[dict] = []
    for rule in rules:
        card = render_card(pan, pred, rule, facts, thresholds, confidence)
        rec = persist_card(db, pan, pred, card, timeline)
        card["id"] = rec.id
        cards.append(card)
    db.commit()
    for card in cards:
        c = db.get(Recommendation, card["id"])
        card["created_at"] = c.created_at.isoformat() if c else card["created_at"]

    return {
        "pan_id": pan.id,
        "pan_ref": pan.pan_code,
        "forecast_source": str(f_days[0].get("source", "mock")),
        "forecast_date": day0.get("date"),
        "rules_signature": rules_signature(),
        "day0": {
            "date": day0.get("date"),
            "rainfall_mm": day0.get("rainfall_mm"),
            "precipitation_probability_pct": day0.get("precipitation_probability_pct"),
        },
        "max_risk": max_risk,
        "risk_level": facts["risk_level"],
        "harvest_readiness": readiness0,
        "harvest_ready": facts["harvest_ready"],
        "what_if": rain_sim,
        "facts": facts,
        "explain": explain,
        "recommendations": cards,
        "human_in_the_loop": {
            "requires_farmer_confirmation": bool(cards) and all(
                c["requires_farmer_confirmation"] for c in cards
            ),
            "note": HUMAN_IN_LOOP_NOTE,
        },
        "created_at": dt.datetime.utcnow().isoformat(),
    }