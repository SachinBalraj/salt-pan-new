from __future__ import annotations

from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

HARVEST_READY_THRESHOLD = 0.55

VERIFIED_SOURCE_VALUES = {"field", "real", "measured", "observed", "actual"}

_CLASS_LOOKUP = {"LOW": "LOW", "MEDIUM": "MEDIUM", "HIGH": "HIGH"}


def _class_upper(v) -> str:
    return _CLASS_LOOKUP.get(str(v).strip().upper(), str(v).strip().upper())


def _field_mask(df: pd.DataFrame, label: str) -> pd.Series:
    """True where a row carries a real-field provenance marker for `label`."""
    for col in (f"{label}_source", f"{label.replace('_ready', '')}_source"):
        if col in df.columns:
            return df[col].astype(str).str.strip().str.lower().isin(VERIFIED_SOURCE_VALUES)
    return pd.Series(False, index=df.index)


def _notna_series(s: Optional[pd.Series]) -> pd.Series:
    if s is None:
        return pd.Series(False, dtype=bool)
    return s.notna()


def resolve_targets(
    df: pd.DataFrame,
    label_report: Optional[Dict] = None,
    dataset_source: Optional[str] = None,
) -> Tuple[pd.DataFrame, Dict]:
    """Derive the three Phase-6 supervised targets on a copy of `df`.

    - `risk_level`      (LOW / MEDIUM / HIGH) — real `risk_level` values where
      field-provenanced, otherwise binned from the proxy `climate_risk_class`.
    - `harvest_ready`   (0 / 1) — real column values where field-provenanced,
      otherwise thresholded from `harvest_readiness`.
    - `hours_to_harvest`— REAL VERIFIED TARGET ONLY. Never synthesised. Rows
      without verified provenance become NaN so the regression model is only
      ever trained on genuine outcome data.

    Returns (augmented_df, target_report).
    """
    out = df.copy()
    feedback = (dataset_source == "feedback")
    report: Dict = {}

    # ---- 1. risk_level ------------------------------------------------------
    cls = out.get("climate_risk_class")
    if cls is None:
        raise ValueError(
            "risk_level requires the `climate_risk_class` column — Phase-5 "
            "ensure_labels must run before target resolution.")
    upper = out["climate_risk_class"].map(_class_upper)

    real_risk = out.get("risk_level") if "risk_level" in out.columns else None
    if feedback and real_risk is not None and real_risk.notna().any():
        out["risk_level"] = real_risk.astype(str).str.strip().str.upper()
        field_mask = real_risk.notna().fillna(False)
    elif real_risk is not None:
        fm = _field_mask(out, "risk_level")
        if not fm.any():
            fm = _field_mask(out, "climate_risk")
        out["risk_level"] = real_risk.astype(str).str.strip().str.upper().where(
            fm, upper)
        field_mask = fm
    else:
        out["risk_level"] = upper
        field_mask = _field_mask(out, "climate_risk")

    out["risk_level_source"] = np.where(field_mask, "field", "proxy")
    n_valid = int(out["risk_level"].astype(str).str.strip().ne("").sum())
    report["risk_level"] = {
        "target": "risk_level",
        "mode": "mixed" if field_mask.any() else "proxy",
        "rows": int(len(out)),
        "field_rows": int(field_mask.sum()),
        "proxy_rows": int((~field_mask).sum()),
        "valid_rows": n_valid,
    }

    # ---- 2. harvest_ready ----------------------------------------------------
    real_ready = None
    real_ready_col = None
    for cand in ("harvest_ready", "harvest_ready_flag"):
        if cand in out.columns:
            real_ready = out[cand]
            real_ready_col = cand
            break

    proxy_ready = (pd.to_numeric(out.get("harvest_readiness", 0.0),
                                 errors="coerce") >= HARVEST_READY_THRESHOLD).astype(int)

    if feedback:
        if real_ready is not None:
            rnum = pd.to_numeric(real_ready, errors="coerce")
            fm = rnum.notna()
            out["harvest_ready"] = rnum.where(fm, proxy_ready).astype(int)
            field_mask = fm.fillna(False)
        else:
            out["harvest_ready"] = proxy_ready
            field_mask = pd.Series(False, index=out.index)
    elif real_ready is not None and real_ready.notna().any():
        rnum = pd.to_numeric(real_ready, errors="coerce")
        fm = _field_mask(out, real_ready_col)
        out["harvest_ready"] = rnum.where(fm, proxy_ready).astype(int)
        field_mask = fm
    else:
        out["harvest_ready"] = proxy_ready
        field_mask = pd.Series(False, index=out.index)

    out["harvest_ready_source"] = np.where(field_mask, "field", "proxy")
    report["harvest_ready"] = {
        "target": "harvest_ready",
        "mode": "mixed" if field_mask.any() else "proxy",
        "rows": int(len(out)),
        "field_rows": int(field_mask.sum()),
        "proxy_rows": int((~field_mask).sum()),
        "valid_rows": int(out["harvest_ready"].notna().sum()),
    }

    # ---- 3. hours_to_harvest (verified-only) ----------------------------------
    hths = out.get("hours_to_harvest") if "hours_to_harvest" in out.columns else None
    fm_ht = _field_mask(out, "hours_to_harvest")
    if feedback and hths is not None and hths.notna().any():
        out["hours_to_harvest"] = pd.to_numeric(hths, errors="coerce").clip(lower=0)
        field_mask = out["hours_to_harvest"].notna()
    elif hths is not None and fm_ht.any():
        rnum = pd.to_numeric(hths, errors="coerce").clip(lower=0)
        out["hours_to_harvest"] = rnum.where(fm_ht)
        field_mask = out["hours_to_harvest"].notna()
    else:
        out["hours_to_harvest"] = np.nan
        field_mask = pd.Series(False, index=out.index)
    out["hours_to_harvest_source"] = np.where(field_mask, "field", "proxy")
    report["hours_to_harvest"] = {
        "target": "hours_to_harvest",
        "mode": "field" if field_mask.any() else "none",
        "rows": int(len(out)),
        "field_rows": int(field_mask.sum()),
        "proxy_rows": 0,
        "valid_rows": int(field_mask.sum()),
    }

    return out, report