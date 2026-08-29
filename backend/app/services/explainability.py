"""Phase 10: model explainability written for a farmer, not a lab report.

Local attributions come from SHAP's TreeExplainer (works for both the
GradientBoosting scorers and the Phase-6 Random Forest models). Each returned
factor keeps the technical feature name for traceability but *leads* with a
plain-language explanation, so the UI never shows a bare feature name as the
headline.

Feature-glossary conversions promoted as canonical (specified by requirement):
  forecast_rain_24h_mm      -> "High rainfall expected during the next 24 hours"
  predicted_salinity_after_rain -> "Rain is expected to dilute the brine"
"""
from __future__ import annotations

from typing import Dict, List, Optional

from app.services.digital_twin import normalise_state

# Canonical human explanations for every technical feature a model might ask
# about. Unknown names fall back to a readable title-cased label so raw
# snake_case identifiers are never presented as the primary explanation.
FEATURE_GLOSSARY: Dict[str, str] = {
    "forecast_rain_24h_mm": "High rainfall expected during the next 24 hours",
    "predicted_salinity_after_rain": "Rain is expected to dilute the brine",
    "precipitation_7d_forecast_mm": "Heavy rain is forecast across the coming week",
    "precipitation_probability_pct": "The chance of rain is high right now",
    "temperature_c": "Temperatures are high, driving evaporation",
    "humidity_pct": "The air is humid, slowing evaporation",
    "wind_speed_kmh": "Winds are picking up across the beds",
    "sunshine_hours": "Long sunshine hours are helping the brine concentrate",
    "days_since_last_rain": "It has been dry for a long stretch",
    "water_depth_cm": "The brine is sitting deep in the pan",
    "brine_density_be": "The brine is well concentrated",
    "salt_thickness_mm": "The salt bed is thick",
    "season_code": "The current season favours this outcome",
}

EXPLAINER_METHOD = "shap.TreeExplainer"

# Rain above this day-0 total warrants the "high rainfall" framing.
HIGH_RAIN_24H_MM = 3.0
# Salinity drop (g/L) below which a storm is not considered a dilution threat.
MIN_DILUTION_G_L = 2.0


def explain_feature(feature: str) -> str:
    """Human-readable explanation for a technical feature name."""
    return FEATURE_GLOSSARY.get(
        feature, feature.replace("_", " ").capitalize()
    )


def shap_top_factors(
    shap_values: Optional[Dict[str, float]], n: int = 3
) -> List[dict]:
    """Top-*n* local SHAP drivers converted into human-readable factors.

    Each factor carries the contributing feature, its signed SHAP value, the
    share of total attribution magnitude and a plain-language explanation.
    """
    if not shap_values:
        return []
    items = sorted(shap_values.items(), key=lambda kv: abs(kv[1]), reverse=True)[:n]
    total = sum(abs(v) for v in shap_values.values()) or 1.0
    factors: List[dict] = []
    for feature, value in items:
        factors.append({
            "feature": feature,
            "contribution": round(float(value), 4),
            "weight_pct": round(100.0 * abs(value) / total, 1),
            "explanation": explain_feature(feature),
        })
    return factors


def context_factors(state: dict, forecast_days: List[dict]) -> List[dict]:
    """Weather-lived context factors derived from the twin + forecast.

    These are the two facts a farmer wants spelled out regardless of which raw
    model feature fired the SHAP signal: how much rain is coming within 24h and
    whether the brine is expected to be diluted by it.
    """
    days = list(forecast_days or [])
    if not days:
        return []
    return _context_water(state, days)


def _context_water(state: dict, days: List[dict]) -> List[dict]:
    rain24 = float(days[0].get("rainfall_mm", 0.0) or 0.0)
    rain_total = float(sum(d.get("rainfall_mm", 0.0) or 0.0 for d in days))
    st = normalise_state(state)
    depth = max(float(st["water_depth_cm"]), 0.1)
    den = float(st["brine_density_be"])
    salinity_after = den * depth / max(depth + rain_total / 10.0, 0.1) * 9.5
    salinity_now = den * 9.5

    factors = [{
        "feature": "forecast_rain_24h_mm",
        "value": round(rain24, 1),
        "explanation": (
            "High rainfall expected during the next 24 hours"
            if rain24 >= HIGH_RAIN_24H_MM
            else "Little or no rain expected in the next 24 hours"
        ),
    }]
    if rain_total >= HIGH_RAIN_24H_MM and (salinity_now - salinity_after) >= MIN_DILUTION_G_L:
        factors.append({
            "feature": "predicted_salinity_after_rain",
            "value": round(salinity_after, 1),
            "explanation": "Rain is expected to dilute the brine",
        })
    else:
        factors.append({
            "feature": "predicted_salinity_after_rain",
            "value": round(salinity_after, 1),
            "explanation": "Rain is not expected to dilute the brine noticeably",
        })
    return factors


def build_explanation(
    state: dict,
    forecast_days: List[dict],
    models: Dict[str, object],
    shap: Optional[Dict[str, Dict[str, float]]],
) -> dict:
    """Full Phase-10 explainability bundle for a prediction run."""
    out: dict = {
        "method": EXPLAINER_METHOD,
        "context": context_factors(state, forecast_days),
    }
    for kind in ("harvest_readiness", "climate_risk"):
        values = (shap or {}).get(kind) or {}
        out[kind] = {"factors": shap_top_factors(values, n=3)}
    return out