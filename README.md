# SaltLens · DSS — AI-Driven Digital Twin Decision Support for Climate-Resilient Salt Pan Management

A full-stack mini-project that manages salt pans as **digital twins**, marries
them with **weather forecasts** (Open-Meteo live or an offline mock), scores a
**harvest-readiness** and **climate-risk** pair of **GradientBoost ML models**
(with SHAP explanations), trains three **supervised Phase-6 models** — a
**climate-risk classifier**, a **harvest-readiness classifier** and a
**harvest-time regressor** on verified field outcomes — runs **"what-if it
rains?"** simulations, issues **recommendations** for harvest dates, records
**verified outcomes**, and **feeds corrections back** into model retraining.
Real-time **sensor readings** (salinity, depth, brine temperature) are
validated, stored and streamed straight into each pan's **digital twin**,
refreshing its forecast, readiness/risk scores and advice.

## Stack

| Layer     | Tech                                                                        |
|-----------|-----------------------------------------------------------------------------|
| Backend   | Python 3.9+, FastAPI, SQLAlchemy 2, Alembic, scikit-learn, SHAP, pandas     |
| Frontend  | Next.js 14 (App Router), React 18, TanStack Query, Recharts, Tailwind CSS    |
| Storage   | PostgreSQL 16 (Docker) with SQLite fallback for local no-Docker development  |
| Infra     | Docker Compose (db + backend + frontend)                                    |

```
┌────────────┐   weather    ┌──────────────┐   twin physics   ┌───────────────┐
│  Weather   │─────────────▶│  FastAPI     │─────────────────▶│  Digital Twin │
│ (Open-     │  forecast    │  /api/*      │  advance_pan_state│  (Postgres)   │
│  Meteo/mock)│             └─────┬────────┘                   └───────────────┘
└────────────┘                    │ ML scoring (readiness / risk) + SHAP
                                  ▼
                    ┌───────────────────────────┐
                    │  Simulations · Advice ·   │
                    │  Outcomes · Evaluation    │
                    └───────────────────────────┘
                                  ▲
                    ┌─────────────┴──────────┐
                    │  Next.js dashboard ✅  │  port 3000
                    └────────────────────────┘
```

## Quick start (Docker — recommended)

Requires Docker (target ports: **3000 / 8000 / 5432**).

```bash
cp .env.example .env      # optional; defaults match docker-compose
docker compose up --build
```

- Frontend dashboard: http://localhost:3000
- API + interactive Swagger: http://localhost:8000/docs
- Health probe: http://localhost:8000/api/health

On first boot the backend runs `alembic upgrade head`, then auto-seeds demo
data (3 salt pans, 5 trained ML kinds, sample predictions/recommendations)
because `AUTO_SEED=true`. Restart to re-seed, because the seed runs only when
the DB is empty.

### What "up --build" gives you

| Service  | Image / build | Port | Notes                                        |
|----------|---------------|------|----------------------------------------------|
| `db`     | postgres:16-alpine | 5432 | healthcheck, named volume `pgdata`       |
| `backend`| `./backend/Dockerfile` | 8000 | `alembic upgrade head` → uvicorn on port 8000 |
| `frontend`| `./frontend/Dockerfile` (multi-stage, `NEXT_PUBLIC_API_URL` baked at build) | 3000 | `next start` |

## Quick start (local, no Docker)

### Backend (port 8000)

```bash
cd backend
python3.9 -m venv .venv                 # any Python ≥ 3.9 works
source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env                 # DATABASE_URL defaults to SQLite
alembic upgrade head                    # create schema (SQLite file: backend/salt_pan_dss.db)
uvicorn app.main:app --port 8000
```

### Frontend (port 3000, in a second terminal)

```bash
cd frontend
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

Open http://localhost:3000 (dashboard) or http://localhost:8000/docs (API).

### Tests

```bash
cd backend && source .venv/bin/activate
pytest -q          # 67 tests: health, datasets, ingestion, proxies, full training/prediction pipeline, Phase-6 ML, Phase-7 digital-twin + sensors, Phase-8 weather service, Phase-9 rain simulator
cd ../frontend
npm run build      # type-check + lint + production bundle
npm run lint
```

## Configuration (`.env.example`)

| Var                 | Default                                                | Purpose                                    |
|---------------------|--------------------------------------------------------|--------------------------------------------|
| `DATABASE_URL`      | SQLite for local / PostgreSQL in compose               | `postgresql+psycopg://…` or `sqlite:///…`   |
| `AUTO_SEED`         | `true`                                                 | seed demo pans + train models on empty DB  |
| `WEATHER_PROVIDER`  | `auto`                                                 | `auto` (live w/ mock fallback) / `live` / `mock` / `csv` |
| `WEATHER_API_KEY`   | *(empty)*                                             | real weather API key; empty ⇒ the app runs fully on mock weather |
| `WEATHER_MOCK_MODE` | `false`                                               | `true` forces the deterministic offline mock |
| `WEATHER_CSV_PATH`  | *(empty → `data/samples/weather_historical.csv`)*     | historical-weather CSV for `WEATHER_PROVIDER=csv` |
| `CORS_ORIGINS`      | `http://localhost:3000,http://127.0.0.1:3000`          | comma-separated browser origins allowed    |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000`                              | API base the frontend bundle calls         |

> Demo pans are anchored to a fixed *twin date* (`demo_today = 2024-05-01`).
> Their forecasts are therefore served by the deterministic **mock** weather
> provider (live 2026 responses would be physically inconsistent with the
> twin). Set `AUTO_SEED=false` and register your own pans to use the live feed.

## API surface (see `/docs` for the full OpenAPI spec)

| Method | Path                                | Description                                    |
|--------|-------------------------------------|------------------------------------------------|
| GET    | `/api/health`                       | Health probe (app, environment, database)      |
| GET    | `/api/system/status`                | Counts + per-kind model availability           |
| GET/POST| `/api/datasets`                    | Upload / validate / preview / import / promote datasets |
| GET    | `/api/datasets/thresholds`           | Logical-range + outlier config (prototype)     |
| POST   | `/api/datasets/preview`              | Analyse a file without persisting (dry run)    |
| POST   | `/api/datasets/upload`               | Store + validate; block nothing, show changes  |
| GET    | `/api/datasets/{id}/analysis`        | Full quality report (mappings, rejects, churn) |
| GET    | `/api/datasets/{id}/invalid_rows`    | CSV of rejected rows with per-row reasons      |
| POST   | `/api/datasets/{id}/import`          | Confirm import of valid rows into operational tables |
| GET/POST| `/api/pans`                        | Register pans, read/write their twin state     |
| GET    | `/api/pans/{pan_id}/digital-twin`   | Full operational twin snapshot (salinity, depth, brine temp, volume, dissolved salt mass, forecast rain + probability, post-rain depth/salinity, evaporation, readiness, climate risk, last operation, last update) |
| POST   | `/api/sensors/readings`             | Ingest a pan-sensor reading: validate → save → forecast → update twin → predict (if an active model exists) → refresh recommendations |
| POST   | `/api/pans/{pan_id}/simulate-rain` | What-if: a single rain event on the pan's current twin state (`rainfall_mm` 1–300): before/after salinity & depth, rain volume, LOW/MEDIUM/HIGH risk, forecast harvest-delay hours, recommended action |
| GET    | `/api/weather/forecast`             | `scenario=auto|mock|live|csv`, force refresh      |
| POST   | `/api/weather/actual`               | Record observed rainfall for a stored forecast day (forecast stays untouched) |
| POST   | `/api/predictions/run`              | 7-day readiness + risk forecast with SHAP (rejects `409` with no active model) |
| POST   | `/api/simulations/what-if-rain`     | "Rain tomorrow?" twin simulation with impact   |
| GET/POST| `/api/recommendations`             | Generate rule-based harvest advice             |
| POST   | `/api/recommendations/{id}/respond` | Farmer accept/decline with notes               |
| POST   | `/api/outcomes`                     | Record verified field outcome                  |
| GET    | `/api/evaluation/summary`           | Precision/recall, readiness MAE, yield MAE     |
| POST   | `/api/evaluation/feedback`          | Fold outcomes into retraining pool + twin      |
| GET    | `/api/models/label-status`          | Proxy/field label provenance + warning banner  |
| GET/POST| `/api/models`/`/api/models/train`  | List models, train (all five kinds or one); `ModelOut` carries `uses_proxy_labels`, split dates, test rows, metrics, training errors |
| GET    | `/api/models/latest`                 | Newest trained version per model kind          |
| POST   | `/api/models/{id}/activate`          | Activate a version (deactivates same-kind siblings) |

## Database schema (Phase 2 — normalized)

Operational data lives in ten tables. Migrations are in `backend/alembic`
(current head `a1b2c3d4e5f6`, which adds the Phase-6 ML-training columns to
`model_versions`; older databases are also synced idempotently at startup by
`ensure_schema`).

| Table                | Purpose                                                        |
|----------------------|----------------------------------------------------------------|
| `datasets`           | Registered data sources (uploads, training pool, feedback)     |
| `pans`               | Salt pans: `pan_code`, name, lat/lon, `area_m2`               |
| `sensor_readings`    | Raw in-pan measurements (brine density, depth, thickness, etc.)|
| `weather_readings`   | Per-day forecast rows (shared cache + per-pan; `forecast_rain_mm` + `actual_rainfall_mm` kept separate) |
| `digital_twin_states`| Twin snapshots (`state_json` + derived readiness/risk columns) |
| `model_versions`     | Trained artifacts + metrics per `kind` (`GradientBoostingRegressor`, `RandomForestClassifier`, `RandomForestRegressor`), track `uses_proxy_labels`, split dates, test rows, training errors, active flag |
| `predictions`        | Model runs; legacy fields stashed in `input_snapshot_json`     |
| `recommendations`    | Rule-based advice (status: pending/accepted/declined)          |
| `operation_events`   | Farmer responses (`farmer_notes`), related to recommendations  |
| `harvest_outcomes`   | Verified field outcomes (+ `details_json` for extra fields)    |

Legacy API-facing ids (`pan_id`, `prediction_id`, …) keep their names on the
wire — the routers (`pans`, `predictions`, `recommendations`, `outcomes`,
`evaluation`, `weather`, `models`) synthesize the old response shapes from the
normalized tables via `app/services/serializers.py`.

## Dataset upload & validation (Phase 3)

Uploading never mutates your data silently. `POST /api/datasets/preview`
runs the full analysis without persisting anything, so you see exactly what
will change before confirming.

- **Type detection** — `sensor`, `weather`, `operations` or `combined`
  (auto-detected from headers; overridable via `dataset_type`).
- **Column normalisation** — fuzzy header aliases map onto canonical columns
  (e.g. `Forecast Rain (mm/24h)` → `forecast_rain_mm`). Re-usable
  **unit conversions** are applied transparently and reported
  (`wind_speed_kmh` → `wind_speed_ms` ÷ 3.6, humidity fraction → %).
- **Timestamp parsing, duplicate detection** (pan + timestamp), missing-value
  counts, **logical-range validation** and a **statistical outlier report**
  (IQR, report-only — never auto-removed).
- **Per-row reasons** — rows that fail validation are excluded from import with
  a downloadable CSV of rejected rows (`/api/datasets/{id}/invalid_rows`).
- **Import is an explicit confirm** — `POST /api/datasets/{id}/import` writes
  the valid rows into `sensor_readings` / `weather_readings` /
  `operation_events` / `harvest_outcomes`, auto-creating missing pans.

Required columns per type:

| Type | Required columns |
|------|------------------|
| `sensor` | `timestamp, pan_id, pan_area_m2, salinity_g_l, water_depth_cm, brine_temperature_C, humidity_pct` |
| `weather` | `timestamp, pan_id (or location), forecast_rain_mm, rain_probability_pct, actual_rainfall_mm, air_temperature_C, humidity_pct, wind_speed_m_s` |
| `operations` | `event_timestamp, pan_id, event_type, transferred_volume_L, pump_duration_min, protection_applied, harvest_date, actual_yield_kg, salt_purity_pct, yield_loss_pct` |
| `combined` | legacy master columns (`pan_id, date, temperature_c, humidity_pct, wind_speed_kmh, rainfall_mm, sunshine_hours, water_level_cm, brine_density_be, salt_thickness_mm, days_since_last_rain`) |

**Logical-range thresholds are configurable, not hard-coded.** They live in
`backend/app/config/domain_thresholds.yaml`, explicitly marked *prototype*
(`meta.status: prototype`) pending field calibration, and can be overridden at
runtime with `DOMAIN_THRESHOLDS_FILE=/path/to/my_calibrated.yaml`.
`min`/`max` are hard bounds (exceeding them rejects the row); `outlier_band`
is the IQR multiplier for the report-only outlier flag.

## Missing real labels (Phase 5 — proxy / simulation mode)

Real field measurements are not always available for the ML targets
(`harvest_readiness`, `climate_risk`, `days_to_harvest`, `yield_loss_pct`,
`recommended_action`). The training pipeline runs in two modes:

- **Field-data mode** — rows that carry a field provenance marker are used
  unchanged: a `label_source == "field"` column, a per-label
  `*_source == "field"` column, or data ingested from the verified feedback
  loop (`source == "feedback"`).
- **Proxy / simulation mode** — everything else is synthesised with
  documented mass-balance calculations and configurable expert rules and is
  stamped `*_source == "proxy"`. Proxy values are **never** presented as field
  measurements.

Every trained `ModelVersion` records `uses_proxy_labels` (DB column + API
`ModelOut.uses_proxy_labels` + artifact `.meta.json`). It is `true` whenever
*any* training row used a proxy label (including mixed field/proxy datasets).
While it is `true` the UI shows a persistent banner:

> **PROXY/SIMULATED MODEL — NOT YET FIELD VALIDATED**

The exact formulas, constants and the **target-leakage** note (metrics against
features that directly produced a label are *self-consistency* checks, not
independent validation) are in
[`docs/proxy_label_methodology.md`](docs/proxy_label_methodology.md). The expert
rules are configurable, not hard-coded, in
`backend/app/config/proxy_labels.yaml` and can be overridden at runtime with
`PROXY_LABELS_CONFIG_FILE=/path/to/my_calibrated.yaml`.

## Supervised ML training (Phase 6)

Beyond the two legacy gradient-boosting scorers, the pipeline trains three
Phase-6 models through the same `POST /api/models/train` endpoint:
`climate_risk_classifier` (`risk_level` → LOW/MEDIUM/HIGH), 
`harvest_readiness_classifier` (`harvest_ready` → 0/1) and
`harvest_time_regressor` (`hours_to_harvest`).

- **Targets** — the classifiers use real field values where provenance is
  recorded and fall back to the Phase-5 proxy signals otherwise
  (`climate_risk_class` binning, `harvest_readiness >= 0.55`), stamping each
  row's source. The regressor is trained **only on verified field outcomes** —
  proxy hours are never fabricated. On a synthetic demo dataset it has no
  verified rows and is **deferred** with
  `["Insufficient verified outcome data."]`.
- **Time-based split** — every kind is split chronologically (80/20) so no
  future observation ever leaks into the training past
  (`ModelOut.split.future_leakage_prevented`).
- **Metrics** — classifiers report accuracy / macro precision / recall / F1
  plus the confusion matrix and per-class train/test distribution; the
  regressors report MAE / RMSE / R². Artifacts are versioned with joblib
  (`models/model_kind_vN.joblib`).
- **Activation** — `POST /api/models/{id}/activate` makes a version active and
  deactivates its same-kind siblings; freshly trained models start active.
- **Prediction gate** — `POST /api/predictions/run` returns `409` when no
  active model exists (`/api/system/status` exposes `any_active_model`), and
  the frontend disables *Run prediction* accordingly.

The training page shows the dataset used, training/test row counts, split date
range, feature list, metrics, proxy-label flag, model version and training
errors.

## Digital twin + sensor readings (Phase 7)

Every salt pan has an operational **digital twin**:

```
GET /api/pans/{pan_id}/digital-twin
```

which returns the current **salinity (g/L)**, **water depth (cm)**,
**brine temperature (°C)**, **brine volume (m³)**, **estimated dissolved salt
mass (kg)**, **forecast rainfall** (next 24h + 7-day window, mm) with **rain
probability (%)**, **predicted post-rain depth** and **predicted post-rain
salinity**, **evaporation estimate (mm/day)**, **harvest readiness**,
**climate risk**, the pan's **last operation** and its **last update**.

In-situ telemetry is streamed in through:

```
POST /api/sensors/readings
    { "pan_code": "PAN-1", "salinity_g_l": 245.2, "water_depth_cm": 6.8,
      "brine_temperature_c": 30.1, "ec_ms_cm": 205.0, ... }
```

The payload is **validated** against physical/domain ranges (rejects
`422`), saved, then piped end-to-end: the **latest weather forecast** is
resolved for the pan, the **digital twin is updated** with the measured state,
a **prediction is run when an active model exists** (skipped cleanly when the
model gate is closed), and the pan's recommendations are **refreshed** —
previous pending advice is expired and a fresh top-3 set is issued. Sensed
salinity is converted to the internal °Bé density (÷ 9.5) so the twin physics,
forecast and ML features stay consistent.

## Weather service (Phase 8 — pluggable providers)

Forecasts come from a small provider interface in `app/services/weather/`,
selected at runtime from the environment:

```
auto   (default)  try the real weather API, fall back to a deterministic mock
live              require the real weather API (mock fallback on outages)
mock              always the built-in deterministic offline generator
csv               serve day-by-day values from a historical-weather CSV
```

Decisions are environment-driven — **no API keys live in source code**:

- `WEATHER_PROVIDER` selects the mode; `WEATHER_API_KEY` carries the key and,
  when empty, the application **still runs completely on mock weather**.
- `WEATHER_MOCK_MODE=true` force-activates mock from any configuration.
- `WEATHER_CSV_PATH` sets the history file for `csv` (default
  `data/samples/weather_historical.csv`); a missing or unreadable CSV (or a
  requested day past the records) falls back to mock continuation, reported as
  `source=csv` / `csv+mock` / `mock`.

**Forecast and observed rainfall are stored separately.** Every
`weather_readings` row keeps `forecast_rain_mm` (never mutates) and
`actual_rainfall_mm` (stamped via `POST /api/weather/actual`, matched to the
pan's newest forecast batch). Both are returned by `GET /api/weather/forecast`
and the digital-twin snapshot; the legacy `rainfall_mm = forecast_rain_mm`
field is preserved for the frontend. A provider outage in `auto`/`live` mode
emits mock data labelled `… (fallback)`, so the platform never goes dark.

## Rain-impact simulator (Phase 9)

`POST /api/pans/{pan_id}/simulate-rain` answers a single what-if question
against the pan's **current** digital-twin state — no trained models needed, so
it works for any registered pan:

```
POST /api/pans/PAN-3/simulate-rain          GET result
  { "rainfall_mm": 20 }                       {
                                                "pan_id": "PAN-3",
                                                "current_salinity_g_l": 245.0,
                                                "current_depth_cm": 8.0,
                                                "current_volume_m3": 40.0,
                                                "rainfall_mm": 20.0,
                                                "rain_volume_m3": 10.0,
                                                "predicted_depth_after_rain_cm": 10.0,
                                                "predicted_salinity_after_rain_g_l": 196.0,
                                                "risk_before": "LOW",
                                                "risk_after": "HIGH",
                                                "predicted_harvest_delay_hours": 72.0,
                                                "recommended_action": "store_brine",
                                                "recommendation": "Store the concentrated…"
                                              }
```

The physics is transparent and deterministic (`app/services/simulator.py`):

- **Post-rain depth** = depth + rainfall/10; **post-rain salinity** = mass-conserving
  dilution (`salinity × depth ÷ depth_after`) — the same conventions the twin's
  own projections use, so numbers agree with the digital twin & forecasts.
- **Risk** (`LOW < 0.25 ≤ MEDIUM < 0.50 ≤ HIGH`) blends three dimensionless
  drivers: how big the event is relative to the pan depth, the relative drop in
  salinity, and how far the pan overflows its safe depth.
- **Harvest delay (h)** = the longer of (rebuild the salt the storm dissolved,
  at ~0.9 mm/day deposition) and (evaporate the rain column, at ~7 mm/day).
- **Recommended action** mirrors the DSS advisory order
  `harvest_now > store_brine > protect_pan > monitor`, keyed to the post-event
  risk and the current brine state.

Runs are **stateless** — the simulation never writes to the twin; refresh the
page or re-run and the pan state is untouched. The **What-if** tab in the UI
adds a one-click control card (pan selector, 0–100 mm rainfall slider, Simulate
button) showing before/after salinity & depth charts, a risk comparison and the
recommended action on top of the existing ML-scenario panel.

## Repository layout

```
backend/
  alembic/            # migrations (initial, Phase-2 normalized schema, Phase-3 dataset_type)
  app/                # FastAPI app: routers/, services/, ml/
  tests/              # pytest suite (67 tests)
data/
  samples/            # etc. bundled sample dataset (salt_pan_dataset.csv)
  processed/          # training pool + feedback CSV (gitignored)
frontend/
  app/                # Next.js App Router (tabbed dashboard)
  components/         # UI kit + panel components
  lib/                # typed API client (lib/api.ts, lib/types.ts)
models/               # joblib artifacts after training (gitignored)
docker-compose.yml
.env.example
```