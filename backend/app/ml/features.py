from __future__ import annotations

import math
from datetime import date
from typing import Dict, List, Optional

import pandas as pd

# Columns that must exist in any raw salt-pan dataset.
REQUIRED_RAW_COLUMNS = [
    "pan_id",
    "date",
    "temperature_c",
    "humidity_pct",
    "wind_speed_kmh",
    "rainfall_mm",
    "sunshine_hours",
    "water_depth_cm",
    "brine_density_be",
    "salt_thickness_mm",
    "days_since_last_rain",
]

OPTIONAL_RAW_COLUMNS = [
    "season",
    "precipitation_7d_forecast_mm",
    "precipitation_probability_pct",
    "harvest_readiness",
    "climate_risk",
    "harvest_ready_flag",
    "yield_kg",
    "action_recorded",
    "latitude",
    "longitude",
]

# Features used to train / serve each model kind.
FEATURE_COLUMNS: Dict[str, List[str]] = {
    "harvest_readiness": [
        "temperature_c",
        "humidity_pct",
        "wind_speed_kmh",
        "sunshine_hours",
        "days_since_last_rain",
        "water_depth_cm",
        "brine_density_be",
        "salt_thickness_mm",
        "season_code",
    ],
    "climate_risk": [
        "precipitation_7d_forecast_mm",
        "precipitation_probability_pct",
        "temperature_c",
        "humidity_pct",
        "wind_speed_kmh",
        "days_since_last_rain",
        "water_depth_cm",
        "brine_density_be",
        "salt_thickness_mm",
        "season_code",
    ],
}

TARGET_COLUMNS: Dict[str, str] = {
    "harvest_readiness": "harvest_readiness",
    "climate_risk": "climate_risk",
}

SEASON_TABLE = {12: 0, 1: 0, 2: 1, 3: 1, 4: 1, 5: 1, 6: 2, 7: 2, 8: 2, 9: 2, 10: 3, 11: 3}


def season_code_for(month: int) -> int:
    return SEASON_TABLE.get(int(month), 0)


def normalize_raw_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure required columns exist as float and add derived columns."""
    df = df.copy()
    for col in REQUIRED_RAW_COLUMNS + OPTIONAL_RAW_COLUMNS:
        if col not in df.columns:
            df[col] = 0.0

    for col in [
        "temperature_c", "humidity_pct", "wind_speed_kmh", "rainfall_mm",
        "sunshine_hours", "water_depth_cm", "brine_density_be", "salt_thickness_mm",
        "days_since_last_rain", "precipitation_7d_forecast_mm",
        "precipitation_probability_pct", "latitude", "longitude",
    ]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    dates = pd.to_datetime(df["date"], errors="coerce")
    df["_month"] = dates.dt.month.fillna(6).astype(int)
    df["season_code"] = df["_month"].map(SEASON_TABLE).fillna(1).astype(int)
    df.drop(columns=["_month"], inplace=True)

    # Rolling 30-day rain used by the readiness model where available.
    if "rainfall_mm" in df.columns:
        df["days_since_last_rain"] = pd.to_numeric(
            df.get("days_since_last_rain"), errors="coerce"
        ).fillna(0.0)
    return df


def build_training_matrices(
    df: pd.DataFrame, kind: str
) -> tuple[pd.DataFrame, pd.Series]:
    """Return (X, y) for a given model kind using column groups."""
    nf = normalize_raw_dataframe(df)
    features = FEATURE_COLUMNS[kind]
    target = TARGET_COLUMNS[kind]
    if target not in nf.columns:
        raise ValueError(
            f"Dataset is missing target column '{target}' required to train "
            f"a {kind} model. Valid targets: harvest_readiness, climate_risk."
        )
    y = pd.to_numeric(nf[target], errors="coerce")
    X = nf[features].copy()
    X = X[y.notna()]
    y = y.dropna()
    # Rows without any signal are not useful for regression.
    mask = y.iloc[:0].notna()  # placeholder
    return X, y


def evap_index(temperature_c: float, humidity_pct: float, wind_speed_kmh: float,
               sunshine_hours: float, rainfall_mm: float = 0.0) -> float:
    """Simple evaporation proxy used by the digital-twin physics layer."""
    satur = math.exp(17.27 * temperature_c / (237.3 + temperature_c))
    humidity = min(max(humidity_pct, 0.0), 100.0)
    rad = max(sunshine_hours, 0.0)
    wind = max(wind_speed_kmh, 0.0)
    e = (0.7 + 0.12 * wind) * satur * (1 - humidity / 100.0) * (0.6 + 0.4 * rad / 12.0)
    return max(0.0, round(e, 3))


def readiness_features_from_state(
    twin_state: dict,
    weather_day: dict,
    precip_7d_mm: float = 0.0,
    precip_prob_pct: float = 0.0,
) -> List[float]:
    """Feature vector for one day, derived from twin state + weather."""
    season = season_code_for(int(weather_day.get("month", 6)))
    return [
        float(weather_day.get("temperature_c", 0.0)),
        float(weather_day.get("humidity_pct", 0.0)),
        float(weather_day.get("wind_speed_kmh", 0.0)),
        float(weather_day.get("sunshine_hours", 0.0)),
        float(twin_state.get("days_since_last_rain", 0.0)),
        float(twin_state.get("water_depth_cm", 0.0)),
        float(twin_state.get("brine_density_be", 0.0)),
        float(twin_state.get("salt_thickness_mm", 0.0)),
        season,
    ]


def risk_features_from_state(
    twin_state: dict,
    weather_day: dict,
    precip_7d_mm: float,
    precip_prob_pct: float,
) -> List[float]:
    season = season_code_for(int(weather_day.get("month", 6)))
    return [
        float(precip_7d_mm),
        float(precip_prob_pct),
        float(weather_day.get("temperature_c", 0.0)),
        float(weather_day.get("humidity_pct", 0.0)),
        float(weather_day.get("wind_speed_kmh", 0.0)),
        float(twin_state.get("days_since_last_rain", 0.0)),
        float(twin_state.get("water_depth_cm", 0.0)),
        float(twin_state.get("brine_density_be", 0.0)),
        float(twin_state.get("salt_thickness_mm", 0.0)),
        season,
    ]


def features_dict(kind: str, twin_state: dict, weather_day: dict,
                  precip_7d_mm: float, precip_prob_pct: float) -> Dict[str, float]:
    if kind == "harvest_readiness":
        vals = readiness_features_from_state(twin_state, weather_day, precip_7d_mm, precip_prob_pct)
    else:
        vals = risk_features_from_state(twin_state, weather_day, precip_7d_mm, precip_prob_pct)
    return dict(zip(FEATURE_COLUMNS[kind], vals))