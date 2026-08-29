from __future__ import annotations

import json
import math
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.config.domain_thresholds import (
    aliases_map,
    conversions_for,
    get_domain_thresholds,
    range_for,
    signature_of,
    thresholds_signature,
)
from app.ml.features import REQUIRED_RAW_COLUMNS
from app.models import HarvestOutcome, OperationEvent, Pan, SensorReading, WeatherReading

# ---------------------------------------------------------------------------
# Canonical columns per dataset type.
# The "required" lists drive validation; numeric lists drive range checks.
# ---------------------------------------------------------------------------

TYPE_TIMESTAMP = {
    "sensor": "timestamp",
    "weather": "timestamp",
    "operations": "event_timestamp",
    "combined": "date",
}

TYPE_PAN_KEYS = {
    "sensor": ("pan_id",),
    "weather": ("pan_id", "location"),
    "operations": ("pan_id",),
    "combined": ("pan_id",),
}

REQUIRED_COLUMNS = {
    "sensor": [
        "timestamp", "pan_id", "pan_area_m2", "salinity_g_l",
        "water_depth_cm", "brine_temperature_c", "humidity_pct",
    ],
    "weather": [
        "timestamp", "pan_id", "forecast_rain_mm", "rain_probability_pct",
        "actual_rainfall_mm", "air_temperature_c", "humidity_pct", "wind_speed_ms",
    ],
    "operations": [
        "event_timestamp", "pan_id", "event_type", "transferred_volume_l",
        "pump_duration_min", "protection_applied",
    ],
    "combined": REQUIRED_RAW_COLUMNS,
}

# Columns that must be numeric wherever they appear (range-checked).
NUMERIC_KEYS = {
    "pan_area_m2", "salinity_g_l", "water_depth_cm", "brine_temperature_c",
    "air_temperature_c", "humidity_pct", "wind_speed_ms", "wind_speed_kmh",
    "forecast_rain_mm", "rain_probability_pct", "actual_rainfall_mm",
    "transferred_volume_l", "pump_duration_min", "drained_volume_l",
    "actual_yield_kg", "salt_purity_pct", "yield_loss_pct",
    "temperature_c", "rainfall_mm", "sunshine_hours", "brine_density_be",
    "salt_thickness_mm", "days_since_last_rain", "precipitation_7d_forecast_mm",
    "precipitation_probability_pct",
}

# Statistical-outlier / hard-range thresholds live in domain_thresholds.yaml.


# ---------------------------------------------------------------------------
# Column mapping helpers
# ---------------------------------------------------------------------------


def _candidate_map(thresholds: Dict[str, Any]) -> Dict[str, List[str]]:
    """signature -> list of candidate canonical columns (YAML aliases + self)."""
    candidates: Dict[str, List[str]] = {}
    for sig, canonical in aliases_map(thresholds).items():
        candidates.setdefault(sig, [])
        if canonical not in candidates[sig]:
            candidates[sig].append(canonical)
    # Unit-conversion targets are valid candidates for their trigger signatures.
    for target, rules in conversions_for(thresholds).items():
        for rule in rules:
            for match in rule.get("matches", []):
                nsig = signature_of(match)
                candidates.setdefault(nsig, [])
                if target not in candidates[nsig]:
                    candidates[nsig].append(target)
    # Canonical names resolve to themselves (exact/self headers win).
    for col in NUMERIC_KEYS:
        sig = signature_of(col)
        candidates.setdefault(sig, [])
        candidates[sig].insert(0, col)
    return candidates


def resolve_mapping(
    original_columns: List[str],
    dataset_type: str,
    field_mapping: Optional[Dict[str, str]] = None,
    thresholds: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Map file headers -> canonical columns with type-aware disambiguation.

    Returns {mappings, unmapped, original_to_canonical, canonical_to_original}.
    """
    thresholds = thresholds or get_domain_thresholds()
    candidates = _candidate_map(thresholds)
    type_cols = set(REQUIRED_COLUMNS[dataset_type])
    overrides: Dict[str, str] = {}  # canonical -> original header
    if field_mapping:
        for canon, orig in field_mapping.items():
            if orig:
                overrides[canon] = orig

    mappings: List[Dict[str, Any]] = []
    original_to_canonical: Dict[str, str] = {}
    canonical_to_original: Dict[str, str] = {}
    used: set = set()

    def _assign(canonical: str, original: str, converted: bool = False) -> None:
        original_to_canonical[original] = canonical
        canonical_to_original[canonical] = original
        mappings.append({
            "original": original,
            "canonical": canonical,
            "converted": bool(converted),
        })

    # 1) Explicit overrides win.
    used_originals = set(overrides.values())
    for canonical, original in overrides.items():
        if original in original_columns:
            _assign(canonical, original)
            used.add(original)

    # 2) Auto-resolve the rest, preferring canonical columns of this type.
    for col in original_columns:
        if col in used:
            continue
        if col in canonical_to_original.values():
            continue
        cands = candidates.get(signature_of(col), [])
        if not cands:
            continue
        chosen = None
        for c in cands:
            if c in type_cols:
                chosen = c
                break
        if chosen is None and len(cands) == 1:
            chosen = cands[0]
        if chosen is None and len(cands) > 1:
            # Ambiguous and not type-required: pick the first not already used.
            for c in cands:
                if c not in canonical_to_original:
                    chosen = c
                    break
        if chosen and chosen not in canonical_to_original:
            _assign(chosen, col)
            used.add(col)

    unmapped = [c for c in original_columns if c not in original_to_canonical]

    # Annotate column mappings that will be unit-converted during import.
    for m in mappings:
        orig_sig = signature_of(m["original"])
        m["converted"] = False
        m["as_units"] = None
        for target, rules in conversions_for(thresholds).items():
            if m["canonical"] != target:
                continue
            if any(signature_of(match) == orig_sig for rule in rules
                   for match in rule.get("matches", [])):
                m["converted"] = True
                m["as_units"] = "m/s" if target == "wind_speed_ms" else \
                                ("%" if target == "humidity_pct" else None)

    return {
        "mappings": mappings,
        "unmapped": unmapped,
        "original_to_canonical": original_to_canonical,
        "canonical_to_original": canonical_to_original,
    }


# ---------------------------------------------------------------------------
# Dataset-type detection
# ---------------------------------------------------------------------------


def detect_type(df: pd.DataFrame, thresholds: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    thresholds = thresholds or get_domain_thresholds()
    aliases = thresholds.get("aliases") or {}
    sigs = [signature_of(c) for c in df.columns]

    def _expected(dtype: str) -> set:
        out: set = set()
        for col in REQUIRED_COLUMNS[dtype]:
            out.add(signature_of(col))
            for alias in aliases.get(col, []):
                out.add(signature_of(alias))
            # Operative defaults: forecasts may live in t-1 rows too.
        return out

    expected = {dtype: _expected(dtype) for dtype in REQUIRED_COLUMNS}
    scores = {dtype: sum(1 for s in sigs if s in expected[dtype])
              for dtype in REQUIRED_COLUMNS}
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best, best_score = ranked[0]

    has_time = any(s in sigs for s in
                   ("timestamp", "datetime", "eventtimestamp", "date_time", "date", "ts"))
    has_pan = any(s in sigs for s in ("pandid", "panid", "pancode", "pan", "panref"))

    n_expected = len(expected[best])
    confidence = min(0.98, round(0.4 + 0.12 * best_score, 2))
    reason = (f"Matched {best_score}/{n_expected} known columns for '{best}' "
              f"(aliases from domain_thresholds.yaml).")
    if best_score <= 0:
        if has_pan and has_time:
            return {"dataset_type": "combined", "confidence": 0.4,
                    "reason": "No type-specific columns matched; defaulting to combined master (pan + timestamp present)."}
        return {"dataset_type": "combined", "confidence": 0.1,
                "reason": "Could not identify dataset type; defaulting to combined master format."}
    return {"dataset_type": best, "confidence": confidence, "reason": reason}


# ---------------------------------------------------------------------------
# Main analysis pipeline
# ---------------------------------------------------------------------------


def analyze_dataframe(
    df: pd.DataFrame,
    dataset_type: Optional[str] = None,
    field_mapping: Optional[Dict[str, str]] = None,
    thresholds: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return analyze_dataframe_full(df, dataset_type, field_mapping, thresholds)[0]


def analyze_dataframe_full(
    df: pd.DataFrame,
    dataset_type: Optional[str] = None,
    field_mapping: Optional[Dict[str, str]] = None,
    thresholds: Optional[Dict[str, Any]] = None,
) -> tuple:
    """Run the full ingestion analysis over an already-parsed dataframe.

    Pure / side-effect free: returns (analysis_doc, normalized_dataframe).
    """
    thresholds = thresholds or get_domain_thresholds()

    if df.empty:
        return (_analysis_error("Empty dataframe — no rows to analyse.", 0), df.copy())

    detected = detect_type(df, thresholds)
    dataset_type = dataset_type or detected["dataset_type"]
    if dataset_type not in REQUIRED_COLUMNS:
        return (_analysis_error(
            f"Unsupported dataset type '{dataset_type}'. Choose one of "
            f"{sorted(REQUIRED_COLUMNS)}.", int(len(df))), df.copy())

    mapping = resolve_mapping(list(df.columns), dataset_type, field_mapping, thresholds)
    o2c = mapping["original_to_canonical"]

    norm = pd.DataFrame()
    renames: Dict[str, Dict[str, Any]] = {}
    conversions: List[Dict[str, Any]] = []
    conv_rules = conversions_for(thresholds)

    for col in df.columns:
        canonical = o2c.get(col, col)
        norm[canonical] = df[col].copy()
        if canonical != col:
            renames[col] = {"to": canonical, "why": "column-name normalisation"}

    # Transparent unit conversions (header-based) are only reported when the
    # original column was actually mapped onto the convertable canonical.
    for m in mapping["mappings"]:
        target = m["canonical"]
        rules = conv_rules.get(target, [])
        orig_sig = signature_of(m["original"])
        for rule in rules:
            if orig_sig in rule.get("matches", []):
                conversions.append({
                    "column": target,
                    "note": rule["note"],
                    "from_unit": rule.get("from_unit", ""),
                    "factor": float(rule["factor"]),
                })
                break

    # column-level change log
    column_changes = [
        {"type": "rename", "column": col, "from": col, "to": r["to"], "note": r["why"]}
        for col, r in renames.items()
    ]

    required = REQUIRED_COLUMNS[dataset_type]
    ts_col = TYPE_TIMESTAMP[dataset_type]
    pan_keys = TYPE_PAN_KEYS[dataset_type]

    # --- timestamp parsing --------------------------------------------------
    ts_original = norm.get(ts_col)
    if ts_original is None:
        errors = [f"Missing required column: '{ts_col}'"]
        return (_completed_analysis(dataset_type, detected, norm, required, ts_col, pan_keys,
                                    mapping, column_changes, conversions, errors, thresholds, 0),
                norm)

    norm_ts = pd.to_datetime(ts_original, errors="coerce", utc=False)
    norm[ts_col] = norm_ts.dt.strftime("%Y-%m-%dT%H:%M:%S")
    bad_ts = int(norm_ts.isna().sum())
    row_reasons: Dict[int, List[str]] = {
        int(i): ["invalid timestamp"]
        for i in norm_ts[norm_ts.isna()].index
    }

    # --- numeric coercion -----------------------------------------------------
    numeric_cols = [c for c in norm.columns if c in NUMERIC_KEYS]
    non_numeric: Dict[str, int] = {}
    for c in numeric_cols:
        raw = norm[c]
        coerced = pd.to_numeric(raw, errors="coerce")
        missing = pd.isna(raw) | ((raw.astype("string").str.strip() == ""))
        bad_mask = coerced.isna() & ~missing
        n_bad = int(bad_mask.sum())
        if n_bad:
            non_numeric[c] = n_bad
            for i in coerced.index[bad_mask]:
                row_reasons.setdefault(int(i), []).append(f"non-numeric '{c}'")
        norm[c] = coerced

    # --- unit conversion application (already reported, now applied) -------
    applied_conversion_cols = {c["column"] for c in conversions}
    for c in applied_conversion_cols:
        if c in norm.columns:
            rules = conv_rules[c]
            norm[c] = norm[c].astype("float64")
            for i in norm.index:
                v = norm.at[i, c]
                if pd.isna(v):
                    continue
                for rule in rules:
                    norm.at[i, c] = float(v) * float(rule["factor"])
                    break

    # --- pan column ---------------------------------------------------------
    pan_col_final = next((c for c in pan_keys if c in norm.columns), None)
    if pan_col_final is None:
        errors = [f"Missing required column: '{'/'.join(pan_keys)}'"]
        return (_completed_analysis(dataset_type, detected, norm, required, ts_col, pan_keys,
                                    mapping, column_changes, conversions, errors, thresholds, 0),
                norm)
    norm[pan_col_final] = norm[pan_col_final].astype(str).str.strip()

    # --- duplicate detection (before validation, using time+pan) ------------
    dup_cols = [ts_col, pan_col_final]
    norm["_n"] = range(len(norm))
    dupes_mask = norm.duplicated(subset=dup_cols, keep=False)
    dup_idx = [int(i) for i in norm.loc[dupes_mask, "_n"]]
    for i in dup_idx:
        row_reasons.setdefault(i, []).append("duplicate (pan + timestamp)")
    norm = norm.drop(columns=["_n"])

    # --- hard range validation ----------------------------------------------
    out_of_range: Dict[str, Dict[str, Any]] = {}
    for c in numeric_cols:
        spec = range_for(dataset_type, c, thresholds)
        if not spec:
            continue
        lo, hi = float(spec["min"]), float(spec["max"])
        below = norm[c] < lo
        above = norm[c] > hi
        bad_rows = norm.index[below | above]
        if len(bad_rows):
            out_of_range[c] = {
                "min": lo, "max": hi,
                "count": int(len(bad_rows)),
                "rows": [int(i) for i in bad_rows],
            }
            for i in bad_rows:
                v = norm.at[i, c]
                side = "below min" if pd.isna(v) or v < lo else "above max"
                row_reasons.setdefault(int(i), []).append(f"'{c}' {side} ({v})")
    # after coercion the subset may have grown; keep only rows with reasons
    norm = norm.copy()

    # --- statistical outliers (report only) ---------------------------------
    outliers: Dict[str, Dict[str, Any]] = {}
    for c in numeric_cols:
        spec = range_for(dataset_type, c, thresholds)
        band_mult = (spec or {}).get("outlier_band", 0)
        if not band_mult:
            continue
        vals = pd.to_numeric(norm[c], errors="coerce").dropna()
        if len(vals) < 4:
            continue
        q1, q3 = vals.quantile([0.25, 0.75])
        iqr = q3 - q1
        if not iqr:
            continue
        lo_b, hi_b = q1 - band_mult * iqr, q3 + band_mult * iqr
        in_band = pd.to_numeric(norm[c], errors="coerce").between(
            lo_b, hi_b, inclusive="neither")
        bad_rows = norm.index[~in_band]
        if len(bad_rows):
            outliers[c] = {"count": int(len(bad_rows)),
                           "rows": [int(i) for i in bad_rows],
                           "band": [round(lo_b, 3), round(hi_b, 3)]}

    # --- error/warning aggregation ------------------------------------------
    missing = {
        c: int(norm[c].isna().sum())
        for c in numeric_cols + [ts_col]
        if int(norm[c].isna().sum())
    }

    rejected_idx = sorted(set(row_reasons))
    rejected = len(rejected_idx)
    valid_idx = [int(i) for i in norm.index if int(i) not in set(rejected_idx)]

    required_present = [c for c in required if c in norm.columns]
    missing_required = [c for c in required if c not in norm.columns]
    errors = [f"Missing required column: '{c}'" for c in missing_required]
    if bad_ts == len(norm) and len(norm) > 0:
        errors.append(f"'{ts_col}' could not be parsed in any row.")

    warnings: List[str] = []
    if mapping["unmapped"]:
        warnings.append(f"Unmapped column(s): {', '.join(mapping['unmapped'])}.")
    if rejected:
        warnings.append(f"{rejected} row(s) rejected ({rejected / len(norm):.1%}) "
                        f"and excluded from import; download the rejection file.")
    if len(dup_idx):
        warnings.append(f"{len(dup_idx)} duplicate (pan + timestamp) row(s) found.")
    out_total = sum(o["count"] for o in out_of_range.values())
    if out_total:
        warnings.append(f"{out_total} value(s) outside hard range bounds.")
    outl_total = sum(o["count"] for o in outliers.values())
    if outl_total:
        warnings.append(f"{outl_total} statistical outlier(s) flagged (report only).")
    for c in missing_required:
        warnings.append(f"Dataset will be importable with {len(required_present)}/{len(required)} required columns only if '{c}' is provided later.")
    if dataset_type == "weather" and "pan_id" not in norm.columns and "location" in norm.columns:
        warnings.append("No 'pan_id' column — weather will be anchored to 'location' (may be pan-less).")

    return (_completed_analysis(dataset_type, detected, norm, required, ts_col, pan_keys,
                               mapping, column_changes, conversions, errors, thresholds,
                               len(rejected_idx), warnings=warnings, missing=missing,
                               rejected_idx=rejected_idx, out_of_range=out_of_range,
                               outliers=outliers, non_numeric=non_numeric,
                               dup_idx=dup_idx, bad_ts=bad_ts,
                               reject_reasons={k: "; ".join(v) for k, v in row_reasons.items()}),
            norm)


def _completed_analysis(dataset_type, detected, norm, required, ts_col, pan_keys,
                        mapping, column_changes, conversions, errors, thresholds,
                        n_rejected, warnings=None, missing=None, rejected_idx=None,
                        out_of_range=None, outliers=None, non_numeric=None,
                        dup_idx=None, bad_ts=0, reject_reasons=None) -> Dict[str, Any]:
    valid_idx = [int(i) for i in norm.index if not (rejected_idx and int(i) in rejected_idx)]
    good = norm.iloc[[i for i, r in enumerate(norm.index) if int(r) in valid_idx]] if valid_idx else norm.iloc[0:0]
    preview_rows = _records(good.head(12))
    total = int(len(norm))
    status = "valid"
    if errors:
        status = "invalid"
    elif n_rejected:
        status = "needs_review"

    thresholds_meta = thresholds.get("meta", {})
    range_checks = {
        c: dict(range_for(dataset_type, c, thresholds))
        for c in norm.columns if range_for(dataset_type, c, thresholds)
    }

    return make_jsonable({
        "dataset_type": dataset_type,
        "detected_type": detected["dataset_type"],
        "type_confidence": detected["confidence"],
        "type_reason": detected["reason"],
        "status": status,
        "total_rows": total,
        "valid_rows": len(valid_idx),
        "rejected_rows": n_rejected,
        "duplicates": {"count": len(dup_idx or []), "row_indices": dup_idx or []},
        "timestamp_bad": bad_ts,
        "timestamp_column": ts_col,
        "pan_columns": list(pan_keys),
        "required_columns": required,
        "required_missing": [c for c in required if c not in norm.columns],
        "columns": list(norm.columns),
        "original_columns": list(dict.fromkeys(
            [m["original"] for m in mapping["mappings"]] + mapping["unmapped"])),
        "mappings": mapping["mappings"],
        "unmapped": mapping["unmapped"],
        "column_changes": column_changes,
        "conversions": conversions,
        "preview": {"columns": list(good.columns), "rows": preview_rows},
        "quality": {
            "missing": missing or {},
            "out_of_range": out_of_range or {},
            "outliers": outliers or {},
            "non_numeric": non_numeric or {},
            "valid_sample": preview_rows,
        },
        "rejected_row_indices": rejected_idx or [],
        "reject_reasons": reject_reasons or {},
        "rejection_sample": _rejection_samples(norm, rejected_idx),
        "issues": {"errors": errors or [], "warnings": warnings or []},
        "range_checks": range_checks,
        "thresholds_source": thresholds_signature(),
        "thresholds_meta": thresholds_meta,
        "thresholds": thresholds,
    })


def _analysis_error(message: str, rows: int) -> Dict[str, Any]:
    return make_jsonable({
        "dataset_type": "combined",
        "detected_type": "combined",
        "type_confidence": 0.0,
        "type_reason": message,
        "status": "invalid",
        "total_rows": rows,
        "valid_rows": 0,
        "rejected_rows": 0,
        "duplicates": {"count": 0, "row_indices": []},
        "timestamp_bad": 0,
        "timestamp_column": "timestamp",
        "pan_columns": ["pan_id"],
        "required_columns": REQUIRED_COLUMNS["combined"],
        "required_missing": [],
        "columns": [],
        "mappings": [],
        "unmapped": [],
        "column_changes": [],
        "conversions": [],
        "preview": {"columns": [], "rows": []},
        "quality": {"missing": {}, "out_of_range": {}, "outliers": {}, "non_numeric": {}},
        "rejected_row_indices": [],
        "rejection_sample": [],
        "issues": {"errors": [message], "warnings": []},
        "thresholds_source": thresholds_signature(),
    })


def _records(df: pd.DataFrame) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for _, row in df.head(12).iterrows():
        rec: Dict[str, Any] = {}
        for col, v in row.items():
            if pd.isna(v):
                rec[col] = None
            elif isinstance(v, (pd.Timestamp, datetime)):
                rec[col] = v.strftime("%Y-%m-%dT%H:%M:%S")
            elif isinstance(v, (float, int)):
                rec[col] = None if (isinstance(v, float) and math.isnan(v)) else v
            else:
                rec[col] = str(v)
        out.append(rec)
    return out


def _rejection_samples(norm: pd.DataFrame, rejected_idx) -> List[Dict[str, Any]]:
    samples: List[Dict[str, Any]] = []
    for i in (rejected_idx or [])[:5]:
        if i in norm.index:
            samples.append({"row": i, **{c: None if pd.isna(norm.at[i, c]) else norm.at[i, c]
                                          for c in norm.columns}})
    return samples


def make_jsonable(node):
    """Recursively convert numpy/pandas scalars so analysis docs are JSON-safe.

    Dict keys are left untouched (json.dumps stringifies int keys later).
    """
    if isinstance(node, dict):
        return {k: make_jsonable(v) for k, v in node.items()}
    if isinstance(node, (list, tuple, set)):
        return [make_jsonable(v) for v in node]
    if isinstance(node, (np.integer,)):
        return int(node)
    if isinstance(node, (np.floating,)):
        return float(node)
    if isinstance(node, (np.bool_,)):
        return bool(node)
    if isinstance(node, (np.ndarray,)):
        return node.tolist()
    if isinstance(node, pd.Timestamp):
        return str(node)
    if isinstance(node, (date, datetime)):
        return node.isoformat()
    if isinstance(node, Decimal):
        return float(node)
    return node


# ---------------------------------------------------------------------------
# Persistence / import helpers
# ---------------------------------------------------------------------------


def persist_artifacts(base_path: Path, analysis: Dict[str, Any], clean_df: pd.DataFrame,
                      invalid_df: pd.DataFrame, selected_columns: List[str]) -> Dict[str, str]:
    """Write clean + invalid CSVs and the analysis doc next to a stored file.

    Returns a map of artifact names -> absolute paths (all relative to base_path).
    """
    store = {c: clean_df[c] for c in selected_columns if c in clean_df.columns}
    invalid_save = {c: invalid_df[c] for c in selected_columns if c in invalid_df.columns}
    if "_rejected_reason" in invalid_df.columns:
        invalid_save["_rejected_reason"] = invalid_df["_rejected_reason"]

    analysis_copy = json.loads(json.dumps(analysis, default=str))
    # The full threshold config is already available via /api/datasets/thresholds.
    analysis_copy.pop("thresholds", None)

    artifacts = {
        "analysis": str(base_path.parent / (base_path.name + ".analysis.json")),
        "clean": str(base_path.parent / (base_path.name + ".clean.csv")),
        "invalid": str(base_path.parent / (base_path.name + ".invalid.csv")),
    }
    (base_path.parent / (base_path.name + ".analysis.json")).write_text(
        json.dumps(analysis_copy, indent=2, default=str), encoding="utf-8")
    pd.DataFrame(store).to_csv(artifacts["clean"], index=False)
    pd.DataFrame(invalid_save).to_csv(artifacts["invalid"], index=False)
    return artifacts


def rejection_frame(clean_df: pd.DataFrame, analysis: Dict[str, Any]) -> pd.DataFrame:
    """Subset the normalized frame to rejected rows, with a reason column."""
    reasons = analysis.get("reject_reasons") or {}
    rejected = [int(i) for i in analysis.get("rejected_row_indices") or []
                if int(i) in clean_df.index]
    if not rejected:
        return clean_df.iloc[0:0].copy()
    out = clean_df.loc[rejected].copy()
    out["_rejected_reason"] = [
        reasons.get(int(i), reasons.get(str(int(i)), "rejected")) for i in out.index
    ]
    return out


def analyze_stored_file(
    file_path: Path,
    dataset_type: Optional[str] = None,
    field_mapping: Optional[Dict[str, str]] = None,
) -> tuple:
    """Re-run the analysis pipeline from a stored CSV/TSV file."""
    df = pd.read_csv(file_path, sep="\t" if str(file_path).lower().endswith(".tsv") else ",")
    return analyze_dataframe_full(df, dataset_type, field_mapping)


def import_rows(
    db: Session,
    analysis: Dict[str, Any],
    clean_df: pd.DataFrame,
    dataset_name: str,
) -> Dict[str, Any]:
    """Import valid rows into the operational tables (explicit user confirm)."""
    dataset_type = analysis["dataset_type"]
    created_pans: List[str] = []
    imported = 0
    pan_id_col = next((c for c in analysis["pan_columns"] if c in clean_df.columns), None)
    ts_col = analysis["timestamp_column"]

    tables = _TARGETS[dataset_type]
    for _, row in clean_df.iterrows():
        pan = None
        if pan_id_col:
            pan = _resolve_pan(db, str(row.get(pan_id_col, "")).strip(), row, created_pans)
        ts = row.get(ts_col)
        ts_dt = None
        try:
            ts_dt = pd.to_datetime(ts)
        except Exception:
            ts_dt = None
        if ts_dt is None:
            continue
        imported += _insert_row(db, dataset_type, pan, row, ts_dt, dataset_name)
    db.flush()
    return {"dataset_type": dataset_type, "imported_rows": imported,
            "tables": tables, "created_pans": created_pans}


_TARGETS = {
    "sensor": ["sensor_readings"],
    "weather": ["weather_readings"],
    "operations": ["operation_events", "harvest_outcomes"],
    "combined": ["sensor_readings"],
}


def _resolve_pan(db: Session, pan_key: str, row: pd.Series, created: List[str]) -> Optional[Pan]:
    key = str(pan_key)
    if not key or key in ("nan", "None"):
        return None
    pan = db.query(Pan).filter(Pan.pan_code == key).first()
    if pan:
        return pan
    area = _num(row.get("pan_area_m2")) or 1000.0
    pan = Pan(pan_code=key, name=key, area_m2=area,
              latitude=_num(row.get("latitude")), longitude=_num(row.get("longitude")))
    db.add(pan)
    db.flush()
    created.append(key)
    return pan


def _num(v) -> Optional[float]:
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _insert_row(db, dataset_type, pan, row, ts_dt, dataset_name) -> int:
    def _get(c):
        return row.get(c)

    if dataset_type in ("sensor", "combined"):
        salinity = _num(_get("salinity_g_l"))
        if salinity is None and _get("brine_density_be") is not None:
            salinity = _num(_get("brine_density_be")) * 9.5
        db.add(SensorReading(
            pan_id=pan.id if pan else None,
            timestamp=ts_dt.to_pydatetime(),
            salinity_g_l=salinity or 0.0,
            water_depth_cm=_num(_get("water_depth_cm")) or 0.0,
            brine_temperature_c=_num(_get("brine_temperature_c") if dataset_type == "sensor"
                                     else _get("temperature_c")) or 0.0,
            air_temperature_c=_num(_get("air_temperature_c")) or 0.0,
            humidity_pct=_num(_get("humidity_pct")) or 0.0,
            source="upload",
        ))
        return 1

    if dataset_type == "weather":
        pan_id = pan.id if pan else None
        db.add(WeatherReading(
            pan_id=pan_id,
            forecast_for=ts_dt.date(),
            forecast_rain_mm=_num(_get("forecast_rain_mm")) or 0.0,
            rain_probability_pct=_num(_get("rain_probability_pct")) or 0.0,
            actual_rainfall_mm=_num(_get("actual_rainfall_mm")),
            temperature_c=_num(_get("air_temperature_c")) or 0.0,
            humidity_pct=_num(_get("humidity_pct")) or 0.0,
            wind_speed_ms=_num(_get("wind_speed_ms")) or 0.0,
            source="upload",
        ))
        return 1

    if dataset_type == "operations":
        if pan is None:
            return 0
        protection = _parse_bool(_get("protection_applied"))
        db.add(OperationEvent(
            pan_id=pan.id,
            event_timestamp=ts_dt.to_pydatetime(),
            event_type=str(_get("event_type") or "operation"),
            transferred_volume_l=_num(_get("transferred_volume_l")),
            pump_duration_min=_num(_get("pump_duration_min")),
            drained_volume_l=_num(_get("drained_volume_l")),
            protection_applied=bool(protection),
            operator_notes=f"imported from '{dataset_name}'",
        ))
        n = 1
        if any(_get(c) is not None for c in ("harvest_date", "actual_yield_kg", "salt_purity_pct")):
            hd = _get("harvest_date")
            db.add(HarvestOutcome(
                pan_id=pan.id,
                harvest_date=str(hd) if hd is not None else str(ts_dt.date()),
                actual_yield_kg=_num(_get("actual_yield_kg")),
                salt_purity_pct=_num(_get("salt_purity_pct")),
                yield_loss_pct=_num(_get("yield_loss_pct")),
                outcome_notes=f"imported from '{dataset_name}'",
            ))
            n += 1
        return n
    return 0


def _parse_bool(v) -> bool:
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    norm = str(v).strip().lower()
    if norm in ("1", "yes", "true", "t", "y", "applied"):
        return True
    return False