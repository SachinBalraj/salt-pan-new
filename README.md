# SaltLens · DSS — AI-Driven Digital Twin Decision Support for Climate-Resilient Salt Pan Management

A full-stack mini-project that manages salt pans as **digital twins**, marries
them with **weather forecasts** (Open-Meteo live or an offline mock), scores a
**harvest-readiness** and **climate-risk** pair of **GradientBoost ML models**
(with SHAP explanations), runs **"what-if it rains?"** simulations, issues
**recommendations** for harvest dates, records **verified outcomes**, and
**feeds corrections back** into model retraining.

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
data (3 salt pans, 2 trained ML models, sample predictions/recommendations)
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
pytest -q          # 21 tests: health, datasets, ingestion pipeline, full training/prediction pipeline
cd ../frontend
npm run build      # type-check + lint + production bundle
npm run lint
```

## Configuration (`.env.example`)

| Var                 | Default                                                | Purpose                                    |
|---------------------|--------------------------------------------------------|--------------------------------------------|
| `DATABASE_URL`      | SQLite for local / PostgreSQL in compose               | `postgresql+psycopg://…` or `sqlite:///…`   |
| `AUTO_SEED`         | `true`                                                 | seed demo pans + train models on empty DB  |
| `WEATHER_PROVIDER`  | `auto`                                                 | `auto`/`mock`/`live` forecast resolution   |
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
| GET    | `/api/weather/forecast`             | `scenario=auto|mock|live`, force refresh       |
| POST   | `/api/predictions/run`              | 7-day readiness + risk forecast with SHAP      |
| POST   | `/api/simulations/what-if-rain`     | "Rain tomorrow?" twin simulation with impact   |
| GET/POST| `/api/recommendations`             | Generate rule-based harvest advice             |
| POST   | `/api/recommendations/{id}/respond` | Farmer accept/decline with notes               |
| POST   | `/api/outcomes`                     | Record verified field outcome                  |
| GET    | `/api/evaluation/summary`           | Precision/recall, readiness MAE, yield MAE     |
| POST   | `/api/evaluation/feedback`          | Fold outcomes into retraining pool + twin      |

## Database schema (Phase 2 — normalized)

Operational data lives in ten tables. Migrations are in `backend/alembic`
(current head `60c7818b02fe`, Phase-3 dataset upload/validation column).

| Table                | Purpose                                                        |
|----------------------|----------------------------------------------------------------|
| `datasets`           | Registered data sources (uploads, training pool, feedback)     |
| `pans`               | Salt pans: `pan_code`, name, lat/lon, `area_m2`               |
| `sensor_readings`    | Raw in-pan measurements (brine density, depth, thickness, etc.)|
| `weather_readings`   | Per-day forecast rows (shared cache + per-pan live/mock)       |
| `digital_twin_states`| Twin snapshots (`state_json` + derived readiness/risk columns) |
| `model_versions`     | Trained GradientBoost artifacts + metrics per `kind`           |
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

## Repository layout

```
backend/
  alembic/            # migrations (initial, Phase-2 normalized schema, Phase-3 dataset_type)
  app/                # FastAPI app: routers/, services/, ml/
  tests/              # pytest suite (21 tests)
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