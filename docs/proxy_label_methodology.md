# Proxy / simulated label methodology (Phase 5)

> **PROXY/SIMULATED MODEL — NOT YET FIELD VALIDATED**
>
> This model was trained on prototype labels synthesised from mass-balance calculations, not on verified field measurements. Treat every score as an un-validated estimate until real harvest/weather outcomes are captured and the model is re-trained in field-data mode.


This document defines EXACTLY how every prototype label is produced when real field measurements are unavailable. The active rules live in `/Users/sachin/Documents/salt pan/salt-pan-dss/backend/app/config/proxy_labels.yaml` (env override `PROXY_LABELS_CONFIG_FILE`).

## Operating modes

1. **Field-data mode** — rows marked as real field records survive unchanged. A row is treated as field data when a provenance marker column is set (`label_source == "field"`), a per-label `<label>_source` column equals `field`/`real`/`measured`, or the dataset comes from the verified feedback loop (`source == "feedback"`).
2. **Proxy / simulation mode** — every other row has its label computed by the mass-balance formulas below and is stamped `*_source == "proxy"`. Proxy labels are NEVER presented as field measurements.

If a dataset has no provenance marker at all, the default is **proxy** (`provenance.default_mode = "proxy"`) so unprovenanced values are never silently trusted.

## `harvest_readiness`

Continuous 0-1 score of how close a bed is to harvest. Weighted combination of brine density progress and salt-bed thickness relative to the harvest target, with a penalty applied shortly after rain.

- **Mode**: `auto` (auto = field where provenance exists, proxy otherwise, per the rules above).
- **Directly derived from**: `brine_density_be, salt_thickness_mm, days_since_last_rain`.
  Metrics measured against these columns are self-consistency checks, NOT independent field validation.

### Proxy formula

$$ readiness = w_d · clamp\left(\frac{den - base}{span}, 0, 1\right) + w_t · clamp\left(\frac{thick}{target}, 0, 1\right) $$
with the recent-rain penalty applied when `days_since_last_rain < penalty_days` and `readiness > 0.4`: multiply by `floor + slope · dsr / penalty_days`.

### Active constants

| Parameter | Value |
|---|---|
| `density_base_be` | 24.0 |
| `density_span_be` | 4.0 |
| `target_thickness_mm` | 15.0 |
| `density_weight` | 0.5 |
| `thickness_weight` | 0.5 |
| `recent_rain_penalty_days` | 5 |
| `recent_rain_penalty_floor` | 0.65 |
| `recent_rain_penalty_slope` | 0.35 |

## `climate_risk`

Continuous 0-1 exposure score plus a `climate_risk_class` bucket (low / medium / high). Forecast rain, bed exposure and brine density contribute linearly.

- **Mode**: `auto` (auto = field where provenance exists, proxy otherwise, per the rules above).
- **Directly derived from**: `precipitation_7d_forecast_mm, salt_thickness_mm, brine_density_be`.
  Metrics measured against these columns are self-consistency checks, NOT independent field validation.

### Proxy formula

$$ risk = a + w_r · clamp\left(\frac{rain7}{rain_{ref}}, 0, 1\right) + w_e · clamp\left(\frac{thick}{target}, 0, 1\right) + w_d · clamp\left(\frac{den - start}{span}, 0, 1\right) $$
`rain7` = next-7-day forecast rain; the class bucket maps `risk < low_max` → low, `< medium_max` → medium, else high.

### Active constants

| Parameter | Value |
|---|---|
| `intercept` | 0.04 |
| `rain_weight` | 0.55 |
| `rain_reference_mm` | 80.0 |
| `exposure_target_mm` | 15.0 |
| `exposure_weight` | 0.26 |
| `density_weight` | 0.12 |
| `density_start_be` | 20.0 |
| `density_span_be` | 8.0 |
| `class_low_max` | 0.33 |
| `class_medium_max` | 0.66 |

## `days_to_harvest`

Number of days until the salt bed reaches harvest thickness, from a mass balance between the thickness deficit and the daily salt deposition rate estimated from evaporation. NULL when evaporation is too weak to estimate a date. Forecast rain adds setback days.

- **Mode**: `auto` (auto = field where provenance exists, proxy otherwise, per the rules above).
- **Directly derived from**: `brine_density_be, salt_thickness_mm, temperature_c, humidity_pct, wind_speed_kmh, sunshine_hours`.
  Metrics measured against these columns are self-consistency checks, NOT independent field validation.

### Proxy formula

$$ dailyGain = k_{dep} · evap · (0.4 + 0.6 · keep) \quad keep = clamp\left(\frac{den - dep_{start}}{dep_{sat} - dep_{start}}, 0, 1\right) $$
$$ deficit = max(target - thick, 0) \qquad days = \lceil deficit / dailyGain \rceil $$
`evap` is the documented evaporation index (`app.ml.features.evap_index`). If `dailyGain < evap_min_gain` the estimate is NULL (cannot estimate). Forecast rain adds `clamp(floor(rain7 / setback_mm) + 1, 0, setback_max)` days.

### Active constants

| Parameter | Value |
|---|---|
| `deposition_start_be` | 25.0 |
| `deposition_sat_be` | 28.0 |
| `deposit_salt_per_evap_mm` | 0.2 |
| `target_thickness_mm` | 15.0 |
| `evap_min_gain_mm_per_day` | 0.02 |
| `rain_setback_mm_per_day` | 20.0 |
| `rain_setback_max_days` | 10.0 |

## `yield_loss_pct`

Expected `yield_loss_pct` if the forecast rain materialises, computed as the thickness lost to rain dissolution divided by the current bed thickness. Zero when no bed exists. This is a projection, not a measured loss.

- **Mode**: `auto` (auto = field where provenance exists, proxy otherwise, per the rules above).
- **Directly derived from**: `precipitation_7d_forecast_mm, water_depth_cm, salt_thickness_mm`.
  Metrics measured against these columns are self-consistency checks, NOT independent field validation.

### Proxy formula

$$ productive = rain7 · clamp(depth_{max} - depth, floor, 1) $$
$$ dissolved = min(thick, productive · k_{diss}) \qquad loss\% = 100 · dissolved / thick $$

### Active constants

| Parameter | Value |
|---|---|
| `dissolution_per_rain_mm` | 0.012 |
| `productive_rain_max_depth_cm` | 3.0 |
| `productive_rain_floor` | 0.3 |

## `recommended_action`

Single highest-priority expert action (harvest_now / harvest_soon / protect_pan / continue_evaporation / pump_excess / store_brine / monitor) selected from the readiness/risk/density/depth state and the forecast.

- **Mode**: `auto` (auto = field where provenance exists, proxy otherwise, per the rules above).
- **Directly derived from**: `harvest_readiness, climate_risk`.
  Metrics measured against these columns are self-consistency checks, NOT independent field validation.

### Proxy formula

Priority table (first matching rule wins):
- `risk > 0.65` and `readiness ≥ 0.55` → **harvest_now**
- `readiness ≥ 0.55` → **harvest_soon**
- `risk > 0.55` or +10 mm rain arriving → **protect_pan**
- `density < 18°Bé`, `depth > 8 cm`, `readiness < 0.5`, `risk ≤ 0.6` → **pump_excess**
- `readiness < 0.55` and `risk ≤ 0.6` → **continue_evaporation**
- +8 mm rain arriving with `18 ≤ density ≤ 28°Bé` → **store_brine**
- otherwise → **monitor**

### Active constants

| Parameter | Value |
|---|---|
| `harvest_now_risk_min` | 0.65 |
| `harvest_now_readiness_min` | 0.55 |
| `harvest_soon_readiness_min` | 0.55 |
| `protect_risk_min` | 0.55 |
| `protect_rain_mm_min` | 10.0 |
| `evaporate_risk_max` | 0.6 |
| `pump_density_max_be` | 18.0 |
| `pump_depth_min_cm` | 8.0 |
| `store_rain_mm_min` | 8.0 |
| `store_density_min_be` | 18.0 |
| `store_density_max_be` | 28.0 |
| `rain_arrival_mm_min` | 0.5 |

## Target leakage

Labels listed below were computed DIRECTLY from the same physical measurements used as model features. Accuracy metrics reported against those features therefore measure formula self-consistency, not independent field performance. Field-labelled data is required to credibly report model accuracy against these columns.


| Target | Directly-derived features |
|---|---|
| `harvest_readiness` | `brine_density_be`, `salt_thickness_mm`, `days_since_last_rain` |
| `climate_risk` | `precipitation_7d_forecast_mm`, `salt_thickness_mm`, `brine_density_be` |
| `days_to_harvest` | `brine_density_be`, `salt_thickness_mm`, `temperature_c`, `humidity_pct`, `wind_speed_kmh`, `sunshine_hours` |
| `yield_loss_pct` | `precipitation_7d_forecast_mm`, `water_depth_cm`, `salt_thickness_mm` |
| `recommended_action` | `harvest_readiness`, `climate_risk` |

## Where `uses_proxy_labels` is set

Every trained `ModelVersion` stores `uses_proxy_labels` in the DB and in its `.meta.json`. It is `true` whenever any training row used a proxy label, and the evaluation UI must not present metrics as field-validated while it is true.

_Generated by `app.services.proxy_labels.write_methodology` from `/Users/sachin/Documents/salt pan/salt-pan-dss/backend/app/config/proxy_labels.yaml`._