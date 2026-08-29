from __future__ import annotations

import pandas as pd

from app.ml.features import REQUIRED_RAW_COLUMNS

RANGE_CHECKS = {
    "temperature_c": (-25.0, 55.0, "temperature outside physical range"),
    "humidity_pct": (0.0, 100.0, "humidity out of percentage range"),
    "wind_speed_kmh": (0.0, 160.0, "wind speed out of range"),
    "rainfall_mm": (0.0, 500.0, "rainfall cannot be negative / absurd"),
    "sunshine_hours": (0.0, 24.0, "sunshine hours outside 0-24"),
    "water_depth_cm": (0.0, 500.0, "water depth out of range"),
    "brine_density_be": (0.0, 32.0, "brine density (Baume) out of range"),
    "salt_thickness_mm": (0.0, 500.0, "salt thickness out of range"),
    "days_since_last_rain": (0.0, 365.0, "days since last rain out of range"),
    "precipitation_7d_forecast_mm": (0.0, 1000.0, "7-day forecast rain out of range"),
    "precipitation_probability_pct": (0.0, 100.0, "precipitation probability out of range"),
}


def validate_dataset(df: pd.DataFrame) -> dict:
    """Structural + statistical validation of an uploaded dataset.

    Returns a report: {valid, rows, columns, missing, errors, warnings}.
    """
    errors: list[str] = []
    warnings: list[str] = []
    missing: dict[str, int] = {}

    for col in REQUIRED_RAW_COLUMNS:
        if col not in df.columns:
            errors.append(f"Missing required column: '{col}'")

    # Core columns must be numeric when present.
    numeric_cols = [c for c in REQUIRED_RAW_COLUMNS if c not in ("date", "pan_id")]
    for col in numeric_cols:
        if col in df.columns:
            coerced = pd.to_numeric(df[col], errors="coerce")
            n_bad = int(coerced.isna().sum())
            if n_bad:
                missing[col] = n_bad
            if n_bad > 0.05 * len(df):
                errors.append(f"Column '{col}' has {n_bad} non-numeric rows ({n_bad / len(df):.0%})")
            else:
                # Range check
                bad = (coerced < RANGE_CHECKS[col][0]) | (coerced > RANGE_CHECKS[col][1])
                n = int(bad.sum())
                if n:
                    warnings.append(f"{RANGE_CHECKS[col][2]} ({n} rows in '{col}')")

    if "date" in df.columns:
        dates = pd.to_datetime(df["date"], errors="coerce")
        n_bad_date = int(dates.isna().sum())
        if n_bad_date:
            missing["date"] = n_bad_date
            if n_bad_date > 0.05 * len(df):
                errors.append(f"Column 'date' has {n_bad_date} unparseable rows")
    else:
        errors.append("Missing required column: 'date'")

    dupes = int(df.duplicated(subset=["pan_id", "date"], keep=False).sum()) if \
        {"pan_id", "date"}.issubset(df.columns) else 0
    if dupes:
        warnings.append(f"{dupes} duplicate (pan_id, date) rows found")

    if not errors and ("harvest_readiness" not in df.columns or "climate_risk" not in df.columns):
        warnings.append(
            "Dataset has no ML target columns (harvest_readiness, climate_risk). "
            "It can still be stored / validated but cannot train models."
        )

    valid = not errors
    return {
        "valid": valid,
        "rows": int(len(df)),
        "columns": list(df.columns),
        "missing": missing,
        "required_missing": REQUIRED_RAW_COLUMNS,
        "errors": errors,
        "warnings": warnings,
        "file_size_bytes": None,
    }