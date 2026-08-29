"""Proxy / simulation label generation for missing real field labels.

Implements the two operating modes required by Phase 5:

* FIELD-DATA mode  - rows carrying a real marker (`label_source == "field"`,
  a per-label `{label}_source` column, or data coming from the verified
  feedback loop) keep their measured values untouched.
* PROXY / SIMULATION mode - every other row (or a whole dataset that has no
  real label provenance) has its target synthesised with the documented
  mass-balance calculations and expert rules in
  `app/config/proxy_labels.yaml`.

Proxy values are ALWAYS stamped with `{label}_source == "proxy"` so they can
never be presented as real field measurements. `uses_proxy_labels` is the
single authoritative flag persisted against a trained model version.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from app.config.proxy_labels import (
    get_proxy_labels_config,
    label_spec,
    proxy_labels_signature,
    warning_banner,
)
from app.ml.features import evap_index

# Every label the system understands.
PROXY_LABELS = [
    "harvest_readiness",
    "climate_risk",
    "days_to_harvest",
    "yield_loss",
    "recommended_action",
]

# Labels that are actually trained into model kinds today.
TRAINED_LABELS = ("harvest_readiness", "climate_risk")

# Default banner constant (also emitted by the frontend warning).
DEFAULT_BANNER = "PROXY/SIMULATED MODEL — NOT YET FIELD VALIDATED"


def _clip(s: Any, lo: float, hi: float) -> "pd.Series":
    return np.clip(pd.to_numeric(s, errors="coerce").fillna(0.0), lo, hi)


def _num(df: pd.DataFrame, col: str, default: float = 0.0) -> "pd.Series":
    if col not in df.columns:
        return pd.Series(default, index=df.index, dtype=float)
    return pd.to_numeric(df[col], errors="coerce").fillna(float(default))


def _str_col(df: pd.DataFrame, col: str, default: str = "") -> "pd.Series":
    if col not in df.columns:
        return pd.Series(default, index=df.index, dtype=object)
    return df[col].fillna(default).astype(str).str.strip().str.lower()


def _rain7(df: pd.DataFrame) -> "pd.Series":
    """Next-7-day rain used by the risk / loss rules."""
    if "precipitation_7d_forecast_mm" in df.columns:
        return _num(df, "precipitation_7d_forecast_mm")
    if "precipitation_7d_forecast_mm" not in df.columns and "next7d_rain_mm" in df.columns:
        return _num(df, "next7d_rain_mm")
    return _num(df, "precipitation_7d_forecast_mm")


# ------------------------------------------------------------------ provenance

def _label_field_mask(df: pd.DataFrame, label: str, config: Dict[str, Any]) -> Tuple[pd.Series, bool]:
    """True where a row carries a REAL field label.

    Precedence:
      1. per-label source column  (e.g. `harvest_readiness_source == "field"`)
      2. generic provenance columns from config (`label_source == "field"`)
      3. mode override: proxy -> always False, field -> always True
      4. otherwise False (default: never claim field provenance)
    """
    n = len(df)
    spec = label_spec(config, label)
    mode = str(spec.get("mode", "auto")).lower()
    if mode == "proxy":
        return pd.Series(False, index=df.index), True
    if mode == "field":
        return pd.Series(True, index=df.index), True

    src_col = f"{label}_source"
    if src_col in df.columns:
        field_vals = {"field", "real", "measured", "observed", "actual"}
        return df[src_col].fillna("").astype(str).str.strip().str.lower().isin(field_vals), True

    provenance = config.get("provenance") or {}
    markers = provenance.get("field_columns") or []
    combined = pd.Series(False, index=df.index)
    found = False
    for marker in markers or []:
        col = marker.get("name") or ""
        value = marker.get("value") or ""
        if col and col in df.columns:
            combined = combined | (df[col].astype(str).str.strip().str.lower() == str(value).lower())
            found = True
    if not found:
        combined = pd.Series(False, index=df.index)
    return combined, True


def _is_feedback(df: pd.DataFrame, dataset_source: Optional[str], config: Dict[str, Any]) -> bool:
    if dataset_source is None:
        return False
    feedback = (config.get("provenance") or {}).get("feedback_source", "feedback")
    return str(dataset_source).lower() == str(feedback).lower()


# ------------------------------------------------------------------ generation

def _gen_harvest_readiness(df: pd.DataFrame, spec: Dict[str, Any]) -> "pd.Series":
    p = spec.get("proxy") or {}
    base = float(p.get("density_base_be", 24.0))
    span = float(p.get("density_span_be", 4.0))
    target = float(p.get("target_thickness_mm", 15.0))
    wd = float(p.get("density_weight", 0.5))
    wt = float(p.get("thickness_weight", 0.5))
    pen_days = float(p.get("recent_rain_penalty_days", 5.0))
    pen_floor = float(p.get("recent_rain_penalty_floor", 0.65))
    pen_slope = float(p.get("recent_rain_penalty_slope", 0.35))

    den = _num(df, "brine_density_be")
    thick = _num(df, "salt_thickness_mm")
    dsr = _num(df, "days_since_last_rain")

    dc = _clip((den - base) / max(span, 1e-6), 0.0, 1.0)
    tc = _clip(thick / max(target, 1e-6), 0.0, 1.0)
    ready = wd * dc + wt * tc
    recent = (dsr < pen_days) & (ready > 0.4)
    ready = ready.where(~recent, ready * (pen_floor + pen_slope * dsr / max(pen_days, 1e-6)))
    return np.clip(ready, 0.0, 1.0).round(4)


def _gen_climate_risk(df: pd.DataFrame, spec: Dict[str, Any]) -> Tuple["pd.Series", "pd.Series"]:
    p = spec.get("proxy") or {}
    intercept = float(p.get("intercept", 0.04))
    rain_w = float(p.get("rain_weight", 0.55))
    rain_ref = float(p.get("rain_reference_mm", 80.0))
    exp_target = float(p.get("exposure_target_mm", 15.0))
    exp_w = float(p.get("exposure_weight", 0.26))
    den_w = float(p.get("density_weight", 0.12))
    den_start = float(p.get("density_start_be", 20.0))
    den_span = float(p.get("density_span_be", 8.0))

    rain7 = _clip(_rain7(df), 0.0, 1e9)
    exposed = _clip(_num(df, "salt_thickness_mm") / max(exp_target, 1e-6), 0.0, 1.0)
    dense = _clip((_num(df, "brine_density_be") - den_start) / max(den_span, 1e-6), 0.0, 1.0)
    risk = intercept + rain_w * _clip(rain7 / max(rain_ref, 1e-6), 0.0, 1.0) \
        + exp_w * exposed + den_w * dense
    risk = np.clip(risk, 0.0, 1.0).round(4)
    return risk, _risk_class(risk, spec)


def _risk_class(risk: pd.Series, spec: Dict[str, Any]) -> pd.Series:
    p = spec.get("proxy") or {}
    low_max = float(p.get("class_low_max", 0.33))
    med_max = float(p.get("class_medium_max", 0.66))
    return risk.map(lambda r: "low" if r < low_max else ("medium" if r < med_max else "high")).astype("object")


def _evap_mm(df: pd.DataFrame) -> "pd.Series":
    temps = _num(df, "temperature_c", 28.0)
    hums = _num(df, "humidity_pct", 60.0)
    winds = _num(df, "wind_speed_kmh", 10.0)
    suns = _num(df, "sunshine_hours", 9.0)
    rains = _num(df, "rainfall_mm")
    return pd.Series(
        [evap_index(t, h, w, s, r) for t, h, w, s, r in zip(temps, hums, winds, suns, rains)],
        index=df.index,
    )


def _gen_days_to_harvest(df: pd.DataFrame, spec: Dict[str, Any]) -> "pd.Series":
    p = spec.get("proxy") or {}
    dep_start = float(p.get("deposition_start_be", 25.0))
    dep_sat = float(p.get("deposition_sat_be", 28.0))
    deposit = float(p.get("deposit_salt_per_evap_mm", 0.20))
    min_gain = float(p.get("evap_min_gain_mm_per_day", 0.02))
    setback_mm = float(p.get("rain_setback_mm_per_day", 20.0))
    setback_max = float(p.get("rain_setback_max_days", 10.0))
    target = float(p.get("target_thickness_mm", 15.0))
    thick = _num(df, "salt_thickness_mm")
    den = _num(df, "brine_density_be")

    keep = _clip((den - dep_start) / max(dep_sat - dep_start, 1e-6), 0.0, 1.0)
    daily_gain = deposit * _evap_mm(df) * (0.4 + 0.6 * keep)

    deficit = np.maximum(target - thick, 0.0)
    estimable = daily_gain >= min_gain
    days = deficit / daily_gain.where(estimable, np.nan)
    days = np.ceil(days).where(deficit > 0, 0.0)

    rain7 = _num(df, "precipitation_7d_forecast_mm") if "precipitation_7d_forecast_mm" in df.columns \
        else np.zeros(len(df))
    setback = np.minimum(np.floor(np.maximum(rain7, 0.0) / max(setback_mm, 1e-6)) + 1.0, setback_max)
    days += setback

    out = days.astype("float64")
    out = out.where(estimable | (deficit <= 0), np.nan)
    return out


def _cfg() -> Dict[str, Any]:
    return get_proxy_labels_config()


def _gen_yield_loss(df: pd.DataFrame, spec: Dict[str, Any]) -> "pd.Series":
    p = spec.get("proxy") or {}
    dissolution = float(p.get("dissolution_per_rain_mm", 0.012))
    max_depth = float(p.get("productive_rain_max_depth_cm", 3.0))
    floor = float(p.get("productive_rain_floor", 0.3))

    thick = _num(df, "salt_thickness_mm")
    depth = _num(df, "water_depth_cm")
    rain7 = _clip(_rain7(df), 0.0, 1e9)

    productive = rain7 * _clip(max_depth - depth, floor, 1.0)
    dissolved = np.minimum(thick, productive * dissolution)
    loss = np.where(thick > 0, 100.0 * dissolved / np.maximum(thick, 1e-9), 0.0)
    return np.clip(loss, 0.0, 100.0).round(2)


def _gen_recommended_action(df: pd.DataFrame, spec: Dict[str, Any], ready: "pd.Series",
                            risk: "pd.Series") -> "pd.Series":
    p = spec.get("proxy") or {}
    hn_risk = float(p.get("harvest_now_risk_min", 0.65))
    hn_ready = float(p.get("harvest_now_readiness_min", 0.55))
    hs_ready = float(p.get("harvest_soon_readiness_min", 0.55))
    prot_risk = float(p.get("protect_risk_min", 0.55))
    prot_rain = float(p.get("protect_rain_mm_min", 10.0))
    evap_risk = float(p.get("evaporate_risk_max", 0.6))
    pump_den = float(p.get("pump_density_max_be", 18.0))
    pump_depth = float(p.get("pump_depth_min_cm", 8.0))
    store_rain = float(p.get("store_rain_mm_min", 8.0))
    store_den_min = float(p.get("store_density_min_be", 18.0))
    store_den_max = float(p.get("store_density_max_be", 28.0))
    arrival_mm = float(p.get("rain_arrival_mm_min", 0.5))

    rain7 = _num(df, "precipitation_7d_forecast_mm") if "precipitation_7d_forecast_mm" in df.columns \
        else np.zeros(len(df))
    rain_arrives = rain7 > arrival_mm
    den = _num(df, "brine_density_be")
    depth = _num(df, "water_depth_cm")

    conditions = [
        (risk > hn_risk) & (ready >= hn_ready),
        ready >= hs_ready,
        (risk > prot_risk) | (rain_arrives & (rain7 > prot_rain)),
        (den < pump_den) & (depth > pump_depth) & (ready < 0.5) & (risk <= evap_risk),
        (ready < hs_ready) & (risk <= evap_risk),
        rain_arrives & (rain7 > store_rain) & (den >= store_den_min) & (den <= store_den_max),
    ]
    choices = ["harvest_now", "harvest_soon", "protect_pan",
               "pump_excess", "continue_evaporation", "store_brine"]
    return pd.Series(np.select(conditions, choices, default="monitor"), index=df.index)


def generate_proxy_labels(df: pd.DataFrame, config: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    """Add every required proxy label + provenance columns to a copy of `df`."""
    config = config or _cfg()
    out = df.copy()
    ready = _gen_harvest_readiness(out, label_spec(config, "harvest_readiness"))
    risk, risk_class = _gen_climate_risk(out, label_spec(config, "climate_risk"))

    # Continuous targets used by the trained kinds.
    out["harvest_readiness"] = ready
    out["climate_risk"] = risk
    out["climate_risk_class"] = risk_class
    out["harvest_readiness_source"] = "proxy"
    out["climate_risk_source"] = "proxy"

    # Extra prototype labels (not yet trained kinds).
    out["days_to_harvest"] = _gen_days_to_harvest(out, label_spec(config, "days_to_harvest"))
    out["days_to_harvest_source"] = "proxy"
    out["yield_loss_pct"] = _gen_yield_loss(out, label_spec(config, "yield_loss"))
    out["yield_loss_source"] = "proxy"
    out["recommended_action"] = _gen_recommended_action(
        out, label_spec(config, "recommended_action"), ready, risk)
    out["recommended_action_source"] = "proxy"
    return out


# ------------------------------------------------------------------ ensure labels

def _action_notna(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().ne("")


def ensure_labels(
    df: pd.DataFrame,
    config: Optional[Dict[str, Any]] = None,
    dataset_source: Optional[str] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Produce a label-complete dataset.

    Returns (augmented_df, report). Rows with real field provenance keep their
    measured values; everything else is filled with documented proxy labels and
    marked `..._source == "proxy"`. Never mutates the caller's frame.
    """
    config = config or _cfg()
    out = df.copy()
    feedback = _is_feedback(out, dataset_source, config)
    proxy_flags: Dict[str, bool] = {}

    labels_cfg = config.get("labels") or {}
    for label in PROXY_LABELS:
        spec = labels_cfg.get(label) or {}
        if not spec.get("enabled", True):
            continue
        target = spec.get("target_column") or label
        class_col = spec.get("class_column")
        is_action = label == "recommended_action"

        proxy = _proxy_for(out, label, spec, config)

        field_vals: Optional[pd.Series] = None
        if feedback:
            if target in out.columns:
                field_vals = out[target]
            elif is_action and "action_recorded" in out.columns:
                field_vals = out["action_recorded"]
        else:
            mask, _ = _label_field_mask(out, label, config)
            if mask.any() and target in out.columns:
                field_vals = out[target].where(mask)

        if field_vals is not None:
            if is_action:
                ok = _action_notna(field_vals)
                final = pd.Series(np.select([ok], [field_vals], default=proxy), index=out.index)
            else:
                ok = pd.to_numeric(field_vals, errors="coerce").notna() & field_vals.notna()
                if ok.any():
                    numeric = pd.to_numeric(field_vals, errors="coerce")
                    final = numeric.where(ok, other=pd.to_numeric(proxy, errors="coerce"))
                else:
                    final = pd.to_numeric(proxy, errors="coerce")
            out[target] = final
            src = pd.Series("proxy", index=out.index, dtype=object)
            src = src.where(~ok, "field")
            out[f"{label}_source"] = src
            proxy_flags[label] = not bool(ok.all())
        else:
            out[target] = proxy
            out[f"{label}_source"] = "proxy"
            proxy_flags[label] = True

        if class_col and label == "climate_risk":
            risk = pd.to_numeric(out[target], errors="coerce")
            out[class_col] = _risk_class(risk, spec).astype("object")

    # Per-label report.
    report_labels: Dict[str, Dict[str, Any]] = {}
    for label in PROXY_LABELS:
        spec = labels_cfg.get(label) or {}
        if not spec.get("enabled", True):
            continue
        target = spec.get("target_column") or label
        if target not in out.columns:
            report_labels[label] = {"mode": "none", "available_rows": 0, "proxy_rows": 0,
                                    "field_rows": 0, "missing_rows": len(out)}
            continue
        is_action = label == "recommended_action"
        src = _str_col(out, f"{label}_source")
        is_proxy = (src == "proxy") | (src == "")
        is_field = (src == "field")
        proxy_rows = int(is_proxy.sum())
        field_rows = int(is_field.sum())
        mode = "proxy" if proxy_rows and not field_rows else \
            ("field" if field_rows and not proxy_rows else "mixed")
        if is_action:
            null_rows = int((~_action_notna(out[target])).sum())
        else:
            null_rows = int(out[target].isna().sum())
        report_labels[label] = {
            "mode": mode,
            "target_column": target,
            "available_rows": len(out) - null_rows,
            "proxy_rows": proxy_rows,
            "field_rows": field_rows,
            "missing_rows": null_rows,
            "source": "proxy" if proxy_rows else "field",
        }

    uses_by_kind = {
        kind: bool(proxy_flags.get(kind, True)) for kind in TRAINED_LABELS
    }
    uses_any = any(uses_by_kind.values())

    report = {
        "uses_proxy_labels": bool(uses_any),
        "uses_proxy_labels_by_kind": uses_by_kind,
        "labels": report_labels,
        "banner": warning_banner(config),
        "config_file": proxy_labels_signature(),
        "dataset_source": dataset_source or "unknown",
        "leakage": leakage_map(config),
    }
    return out, report


def _proxy_for(df: pd.DataFrame, label: str, spec: Dict[str, Any],
               config: Dict[str, Any]) -> pd.Series:
    """Compute the proxy series for one label (used for fill / full generation)."""
    if label == "harvest_readiness":
        return _gen_harvest_readiness(df, spec)
    if label == "climate_risk":
        return _gen_climate_risk(df, spec)[0]
    if label == "days_to_harvest":
        return _gen_days_to_harvest(df, spec)
    if label == "yield_loss":
        return _gen_yield_loss(df, spec)
    if label == "recommended_action":
        ready = _gen_harvest_readiness(df, label_spec(config, "harvest_readiness"))
        risk = _gen_climate_risk(df, label_spec(config, "climate_risk"))[0]
        return _gen_recommended_action(df, spec, ready, risk)
    raise ValueError(f"Unknown proxy label '{label}'")


# ------------------------------------------------------------------ leakage

def leakage_map(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Target -> features it was computed DIRECTLY from (non-independent)."""
    config = config or _cfg()
    mapping: Dict[str, List[str]] = {}
    labels = config.get("labels") or {}
    for label, spec in labels.items():
        feats = spec.get("leakage_features") or []
        if feats:
            mapping[spec.get("target_column") or label] = list(feats)
    return {
        "note": (config.get("leakage") or {}).get(
            "note",
            "Labels computed directly from the same measurements used as features "
            "cannot be used as independent proof of model accuracy."),
        "map": mapping,
    }


def labels_status_summary(db_models: Optional[List[Any]] = None, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Frontend-facing status: banner, active proxy flag, per-kind flags."""
    config = config or _cfg()
    kinds: Dict[str, bool] = {}
    any_proxy = False
    if db_models:
        for model in db_models:
            kind = getattr(model, "model_type", "")
            flag = bool(getattr(model, "uses_proxy_labels", True))
            kinds[kind] = flag
            if flag:
                any_proxy = True
    else:
        # No model metadata to inspect -> be conservative and warn.
        any_proxy = True
    return {
        "banner": warning_banner(config),
        "subtext": (config.get("warning") or {}).get(
            "subtext", DEFAULT_BANNER),
        "any_active_proxy": any_proxy,
        "models": kinds,
        "config_file": proxy_labels_signature(),
        "methodology_file": (config.get("output") or {}).get(
            "methodology_file", "docs/proxy_label_methodology.md"),
    }


# ------------------------------------------------------------------ documentation

def methodology_markdown(config: Optional[Dict[str, Any]] = None) -> str:
    config = config or _cfg()
    labels = config.get("labels") or {}
    L: List[str] = []

    L.append("# Proxy / simulated label methodology (Phase 5)")
    L.append("")
    L.append("> **" + warning_banner(config) + "**")
    L.append(">")
    L.append("> " + ((config.get("warning") or {}).get("subtext") or ""))
    L.append("")
    L.append(
        "This document defines EXACTLY how every prototype label is produced when "
        "real field measurements are unavailable. The active rules live in "
        f"`{proxy_labels_signature()}` (env override `PROXY_LABELS_CONFIG_FILE`)."
    )
    L.append("")
    L.append("## Operating modes")
    L.append("")
    prov = config.get("provenance") or {}
    markers = prov.get("field_columns") or []
    marker_desc = " or ".join(
        f"`{m.get('name')} == \"{m.get('value')}\"`" for m in markers) if markers else \
        "`label_source == \"field\"`"
    L.append("1. **Field-data mode** — rows marked as real field records survive unchanged. "
             "A row is treated as field data when a provenance marker column is set "
             f"({marker_desc}), a per-label `<label>_source` column "
             "equals `field`/`real`/`measured`, or the dataset comes from the verified "
             f"feedback loop (`source == \"{prov.get('feedback_source', 'feedback')}\"`).")
    L.append("2. **Proxy / simulation mode** — every other row has its label computed by "
             "the mass-balance formulas below and is stamped `*_source == \"proxy\"`. Proxy "
             "labels are NEVER presented as field measurements.")
    L.append("")
    L.append("If a dataset has no provenance marker at all, the default is **proxy** "
             f"(`provenance.default_mode = \"{prov.get('default_mode', 'proxy')}\"`) so "
             "unprovenanced values are never silently trusted.")
    L.append("")

    descriptions = {
        "harvest_readiness": (
            "Continuous 0-1 score of how close a bed is to harvest. Weighted "
            "combination of brine density progress and salt-bed thickness relative "
            "to the harvest target, with a penalty applied shortly after rain."),
        "climate_risk": (
            "Continuous 0-1 exposure score plus a `climate_risk_class` bucket "
            "(low / medium / high). Forecast rain, bed exposure and brine density "
            "contribute linearly."),
        "days_to_harvest": (
            "Number of days until the salt bed reaches harvest thickness, from a "
            "mass balance between the thickness deficit and the daily salt "
            "deposition rate estimated from evaporation. NULL when evaporation is "
            "too weak to estimate a date. Forecast rain adds setback days."),
        "yield_loss": (
            "Expected `yield_loss_pct` if the forecast rain materialises, computed "
            "as the thickness lost to rain dissolution divided by the current bed "
            "thickness. Zero when no bed exists. This is a projection, not a "
            "measured loss."),
        "recommended_action": (
            "Single highest-priority expert action (harvest_now / harvest_soon / "
            "protect_pan / continue_evaporation / pump_excess / store_brine / "
            "monitor) selected from the readiness/risk/density/depth state and the "
            "forecast."),
    }

    formulas = {
        "harvest_readiness": (
            "$$ readiness = w_d · clamp\\left(\\frac{den - base}{span}, 0, 1\\right) + "
            "w_t · clamp\\left(\\frac{thick}{target}, 0, 1\\right) $$\n"
            "with the recent-rain penalty applied when `days_since_last_rain < penalty_days` "
            "and `readiness > 0.4`: multiply by `floor + slope · dsr / penalty_days`."),
        "climate_risk": (
            "$$ risk = a + w_r · clamp\\left(\\frac{rain7}{rain_{ref}}, 0, 1\\right) + "
            "w_e · clamp\\left(\\frac{thick}{target}, 0, 1\\right) + "
            "w_d · clamp\\left(\\frac{den - start}{span}, 0, 1\\right) $$\n"
            "`rain7` = next-7-day forecast rain; the class bucket maps "
            "`risk < low_max` → low, `< medium_max` → medium, else high."),
        "days_to_harvest": (
            "$$ dailyGain = k_{dep} · evap · (0.4 + 0.6 · keep) \\quad "
            "keep = clamp\\left(\\frac{den - dep_{start}}{dep_{sat} - dep_{start}}, 0, 1\\right) $$\n"
            "$$ deficit = max(target - thick, 0) \\qquad days = \\lceil deficit / dailyGain \\rceil $$\n"
            "`evap` is the documented evaporation index (`app.ml.features.evap_index`). "
            "If `dailyGain < evap_min_gain` the estimate is NULL (cannot estimate). "
            "Forecast rain adds `clamp(floor(rain7 / setback_mm) + 1, 0, setback_max)` days."),
        "yield_loss": (
            "$$ productive = rain7 · clamp(depth_{max} - depth, floor, 1) $$\n"
            "$$ dissolved = min(thick, productive · k_{diss}) \\qquad "
            "loss\\% = 100 · dissolved / thick $$"),
        "recommended_action": (
            "Priority table (first matching rule wins):\n"
            "- `risk > 0.65` and `readiness ≥ 0.55` → **harvest_now**\n"
            "- `readiness ≥ 0.55` → **harvest_soon**\n"
            "- `risk > 0.55` or +10 mm rain arriving → **protect_pan**\n"
            "- `density < 18°Bé`, `depth > 8 cm`, `readiness < 0.5`, `risk ≤ 0.6` → **pump_excess**\n"
            "- `readiness < 0.55` and `risk ≤ 0.6` → **continue_evaporation**\n"
            "- +8 mm rain arriving with `18 ≤ density ≤ 28°Bé` → **store_brine**\n"
            "- otherwise → **monitor**"),
    }

    for label in PROXY_LABELS:
        spec = labels.get(label) or {}
        if not spec.get("enabled", True):
            continue
        target = spec.get("target_column") or label
        L.append(f"## `{target}`")
        L.append("")
        L.append(descriptions.get(label, ""))
        L.append("")
        L.append(f"- **Mode**: `{spec.get('mode', 'auto')}` (auto = field where "
                 f"provenance exists, proxy otherwise, per the rules above).")
        if spec.get("leakage_features"):
            L.append(f"- **Directly derived from**: `{', '.join(spec['leakage_features'])}`.")
            L.append("  Metrics measured against these columns are self-consistency "
                     "checks, NOT independent field validation.")
        L.append("")
        L.append("### Proxy formula")
        L.append("")
        L.append(formulas.get(label, ""))
        L.append("")
        L.append("### Active constants")
        L.append("")
        L.append("| Parameter | Value |")
        L.append("|---|---|")
        p = spec.get("proxy") or {}
        for k, v in p.items():
            L.append(f"| `{k}` | {v} |")
        L.append("")

    L.append("## Target leakage")
    L.append("")
    leak = config.get("leakage") or {}
    L.append(leak.get("note", ""))
    L.append("")
    lmap = leakage_map(config)
    if lmap.get("map"):
        L.append("| Target | Directly-derived features |")
        L.append("|---|---|")
        for target, feats in lmap["map"].items():
            L.append(f"| `{target}` | {', '.join('`' + f + '`' for f in feats)} |")
        L.append("")
    L.append("## Where `uses_proxy_labels` is set")
    L.append("")
    L.append("Every trained `ModelVersion` stores `uses_proxy_labels` in the DB and "
             "in its `.meta.json`. It is `true` whenever any training row used a "
             "proxy label, and the evaluation UI must not present metrics as "
             "field-validated while it is true.")
    L.append("")
    L.append("_Generated by `app.services.proxy_labels.write_methodology` from "
             f"`{proxy_labels_signature()}`._")
    return "\n".join(L)


def write_methodology(path) -> str:
    import os

    config = _cfg()
    os.makedirs(os.path.dirname(str(path)) or ".", exist_ok=True)
    text = methodology_markdown(config)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return str(path)