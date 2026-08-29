from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from app.ml.features import FEATURE_COLUMNS, features_dict
from app.models import SaltPan
from app.services.data_generator import advance_pan_state
from app.services.digital_twin import normalise_state


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(x)))


def _predict_row(model, fd: Dict[str, float]) -> float:
    return float(model.predict(pd.DataFrame([fd]))[0])


def _sum_precip(days: List[dict], i: int, span: int) -> float:
    return float(sum(d.get("rainfall_mm", 0.0) for d in days[i:i + span]))


def _mean_prob(days: List[dict], i: int, span: int) -> float:
    probs = [d.get("precipitation_probability_pct", 0.0) for d in days[i:i + span]]
    return float(np.mean(probs)) if probs else 0.0


def scored_timeline(
    pan: SaltPan,
    forecast_days: List[dict],
    models: Dict[str, object],  # {"harvest_readiness": model, "climate_risk": model}
    start_date: Optional[str] = None,
) -> List[dict]:
    """Day-by-day readiness + risk over a forecast using twin physics + ML."""
    horizon = len(forecast_days)
    base = dt.date.fromisoformat(start_date) if start_date else dt.date.today()
    rng = np.random.default_rng(horizon * 13 + pan.id)
    state = normalise_state(pan.twin_state)
    points: List[dict] = []
    for i, w in enumerate(forecast_days):
        w = dict(w)
        for k, v in list(w.items()):
            try:
                w[k] = float(v)
            except (TypeError, ValueError):
                w[k] = str(v)
        state = advance_pan_state(state, w, 0.0, rng)
        state = normalise_state(state)

        readiness = 0.0
        risk = 0.0
        if models.get("harvest_readiness") is not None:
            fd = features_dict("harvest_readiness", state, w, 0.0, 0.0)
            readiness = _clip(_predict_row(models["harvest_readiness"], fd), 0.0, 1.0)
        if models.get("climate_risk") is not None:
            precip7 = _sum_precip(forecast_days, i, min(7, horizon - i))
            prob = _mean_prob(forecast_days, i, min(7, horizon - i))
            fd = features_dict("climate_risk", state, w, precip7, prob)
            risk = _clip(_predict_row(models["climate_risk"], fd), 0.0, 1.0)

        points.append({
            "date": (base + dt.timedelta(days=i)).isoformat(),
            "label": (base + dt.timedelta(days=i)).strftime("%d %b"),
            "temperature_c": w["temperature_c"],
            "rainfall_mm": w["rainfall_mm"],
            "humidity_pct": w["humidity_pct"],
            "wind_speed_kmh": w["wind_speed_kmh"],
            "sunshine_hours": w.get("sunshine_hours", 0.0),
            "precipitation_probability_pct": w.get("precipitation_probability_pct", 0.0),
            "brine_density_be": state["brine_density_be"],
            "salt_thickness_mm": state["salt_thickness_mm"],
            "water_depth_cm": state["water_depth_cm"],
            "days_since_last_rain": state["days_since_last_rain"],
            "readiness": round(readiness, 4),
            "risk": round(risk, 4),
        })
    return points


def local_shap_values(model, feature_vector: List[float], feature_names: List[str]) -> Dict[str, float]:
    try:
        import shap
    except Exception:
        return {}
    explainer = shap.TreeExplainer(model)
    try:
        values = explainer.shap_values(np.asarray([feature_vector]))
    except Exception:
        values = [0.0] * len(feature_names)
    if isinstance(values, list):
        values = np.asarray(values[0]) if values else np.zeros(len(feature_names))
    values = np.asarray(values)
    if values.ndim == 3:
        values = values[:, :, 0]
    arr = values[0] if values.ndim == 2 else values
    out: Dict[str, float] = {}
    for name, v in zip(feature_names, arr):
        out[name] = round(float(v), 5)
    return out


def day0_features(pan: SaltPan, forecast_days: List[dict], kind: str) -> Dict[str, float]:
    state = normalise_state(pan.twin_state)
    w = dict(forecast_days[0])
    for k, v in list(w.items()):
        try:
            w[k] = float(v)
        except (TypeError, ValueError):
            w[k] = str(v)
    precip7 = _sum_precip(forecast_days, 0, min(7, len(forecast_days)))
    prob = _mean_prob(forecast_days, 0, min(7, len(forecast_days)))
    return features_dict(kind, state, w, precip7, prob)