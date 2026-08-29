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
pytest -q          # 9 tests: health, datasets, full training/prediction pipeline
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
| GET/POST| `/api/datasets`                    | Upload / validate / preview / promote datasets |
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
(current head `b273583dc823`, `phase 2 - normalized operational schema`).

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

## Repository layout

```
backend/
  alembic/            # migrations (initial + Phase-2 normalized schema)
  app/                # FastAPI app: routers/, services/, ml/
  tests/              # pytest suite (9 tests)
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