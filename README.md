# SaltLens DSS

AI-driven digital twin decision support for climate-resilient salt pan management.

A full-stack application that models salt pans as digital twins, integrates weather forecasts, trains ML models with SHAP explainability, runs what-if rain simulations, generates farmer recommendations, and feeds verified outcomes back into model retraining.

> **Prototype status.** All thresholds, proxy-label formulas and expert rules
> are **un-calibrated defaults** pending field validation. See
> [Proxy-Data Disclosure](#proxy-data-disclosure) and
> [`docs/proxy_label_methodology.md`](docs/proxy_label_methodology.md).

---

## Architecture

```
┌────────────────┐   weather    ┌──────────────────┐   twin physics   ┌───────────────────┐
│   Weather      │─────────────▶│  FastAPI Backend │─────────────────▶│  Digital Twin     │
│   Service      │  forecast    │  /api/*          │  advance_state   │  (PostgreSQL)     │
│ (Open-Meteo /  │             └────────┬─────────┘                   └───────────────────┘
│  mock / CSV)   │                      │ ML scoring + SHAP
└────────────────┘                      ▼
                          ┌───────────────────────────┐
                          │  Simulations · Advice ·   │
                          │  Outcomes · Evaluation    │
                          └───────────────────────────┘
                                    ▲
                          ┌─────────┴──────────┐
                          │  Next.js Dashboard │  :3000
                          └────────────────────┘
```

**Data flow:**

1. **Upload** CSV datasets (sensor / weather / operations / combined) → validate → import
2. **Train** 5 model kinds on the training pool (proxy or field labels)
3. **Sensor readings** update the digital twin in real time
4. **Weather forecasts** (live or mock) project rain impact
5. **Simulations** answer "what if it rains 20 mm tomorrow?"
6. **Recommendations** are generated with SHAP-backed reasons
7. **Farmer accepts/rejects** → outcome recorded → feedback retrains models

---

## Technology Stack

| Layer     | Technology                                                                         |
|-----------|------------------------------------------------------------------------------------|
| Backend   | Python 3.9+, FastAPI, SQLAlchemy 2, Alembic, scikit-learn, SHAP, pandas, joblib   |
| Frontend  | Next.js 14 (App Router), React 18, TanStack Query, Recharts, Tailwind CSS         |
| Database  | PostgreSQL 16 (Docker) with SQLite fallback for local no-Docker development        |
| Infra     | Docker Compose (db + backend + frontend)                                           |
| Weather   | Open-Meteo API (live), deterministic mock, historical CSV, or auto-fallback        |
| i18n      | English / Tamil (தமிழ்) toggle for farmer-facing instructions                       |

---

## Folder Structure

```
salt-pan-dss/
├── backend/
│   ├── alembic/                  # DB migrations (5 versions)
│   │   └── versions/
│   ├── app/
│   │   ├── config/               # YAML configs (thresholds, proxy labels)
│   │   ├── ml/                   # SHAP explainer, model utilities
│   │   ├── routers/              # 11 FastAPI routers
│   │   │   ├── datasets.py
│   │   │   ├── evaluation.py
│   │   │   ├── models.py
│   │   │   ├── outcomes.py
│   │   │   ├── pans.py
│   │   │   ├── predictions.py
│   │   │   ├── recommendations.py
│   │   │   ├── sensors.py
│   │   │   ├── simulations.py
│   │   │   └── weather.py
│   │   ├── services/             # Business logic (18 modules)
│   │   │   ├── advisor.py
│   │   │   ├── data_generator.py
│   │   │   ├── dataset_validator.py
│   │   │   ├── digital_twin.py
│   │   │   ├── evaluation.py
│   │   │   ├── explainability.py
│   │   │   ├── ingestion.py
│   │   │   ├── model_targets.py
│   │   │   ├── predictor.py
│   │   │   ├── proxy_labels.py
│   │   │   ├── recommendation_engine.py
│   │   │   ├── seeding.py
│   │   │   ├── serializers.py
│   │   │   ├── simulator.py
│   │   │   ├── training.py
│   │   │   └── weather/
│   │   │       ├── __init__.py
│   │   │       ├── base.py
│   │   │       ├── csv_provider.py
│   │   │       ├── live_provider.py
│   │   │       └── mock_provider.py
│   │   ├── config.py             # pydantic-settings
│   │   ├── database.py           # SQLAlchemy engine + session
│   │   ├── main.py               # FastAPI app + lifespan
│   │   └── models.py             # 10 ORM models
│   ├── tests/                    # pytest suite (15 files, 90+ tests)
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── app/                      # Next.js App Router
│   │   ├── globals.css
│   │   ├── layout.tsx
│   │   ├── page.tsx              # 9-tab dashboard shell
│   │   └── providers.tsx
│   ├── components/
│   │   ├── panels/               # 14 panel components
│   │   │   ├── Dashboard.tsx
│   │   │   ├── PanDetails.tsx
│   │   │   ├── SimulatePanel.tsx
│   │   │   ├── DataPanel.tsx
│   │   │   ├── ModelsPanel.tsx
│   │   │   ├── PredictPanel.tsx
│   │   │   ├── RecommendationsPanel.tsx
│   │   │   ├── OutcomesPanel.tsx
│   │   │   ├── FeedbackPanel.tsx
│   │   │   ├── SetupPanel.tsx
│   │   │   ├── ComparePanel.tsx
│   │   │   ├── WeatherPanel.tsx
│   │   │   ├── TwinPanel.tsx
│   │   │   └── common.tsx
│   │   └── ui.tsx
│   ├── lib/
│   │   ├── api.ts                # Typed API client
│   │   ├── types.ts              # TypeScript interfaces
│   │   └── i18n.tsx              # English / Tamil translations
│   ├── Dockerfile
│   └── package.json
├── data/
│   ├── raw/                      # Uploaded raw files
│   ├── processed/                # Training pool + feedback CSV
│   ├── samples/                  # Bundled sample datasets + CSV templates
│   └── logs/
├── models/                       # Joblib model artifacts (gitignored)
├── docs/
│   └── proxy_label_methodology.md
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## Installation Requirements

| Requirement | Version | Notes |
|-------------|---------|-------|
| Docker | 20.10+ | Recommended path — includes PostgreSQL |
| Docker Compose | v2+ | `docker compose` (not `docker-compose`) |
| Python | 3.9+ | Only for local no-Docker development |
| Node.js | 20+ | Only for local no-Docker frontend dev |
| PostgreSQL | 16 | Provided by Docker; SQLite fallback available locally |

---

## Docker Startup (Recommended)

```bash
cd salt-pan-dss
cp .env.example .env          # optional — defaults match docker-compose.yml
docker compose up --build
```

On first boot the backend runs `alembic upgrade head`, then auto-seeds demo data
(3 salt pans, 5 trained ML models, sample predictions, recommendations) because
`AUTO_SEED=true`. Restart to re-seed (seeds only when the DB is empty).

**Services:**

| Service    | Port | Notes |
|------------|------|-------|
| `frontend` | 3000 | Next.js production build |
| `backend`  | 8000 | FastAPI + Swagger docs at `/docs` |
| `db`       | 5432 | PostgreSQL 16, healthcheck, named volume `pgdata` |

---

## Local Startup (No Docker)

### Backend (port 8000)

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env        # DATABASE_URL defaults to SQLite
alembic upgrade head           # creates backend/salt_pan_dss.db
uvicorn app.main:app --port 8000
```

### Frontend (port 3000, second terminal)

```bash
cd frontend
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

Open http://localhost:3000 (dashboard) and http://localhost:8000/docs (API).

---

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATABASE_URL` | `postgresql+psycopg://salt:dss@localhost:5432/salt_pan_dss` | PostgreSQL connection; swap to `sqlite:///./salt_pan_dss.db` for local SQLite |
| `AUTO_SEED` | `true` | Seed demo pans + train models when the DB is empty on boot |
| `WEATHER_PROVIDER` | `auto` | `auto` (live w/ mock fallback) / `live` / `mock` / `csv` |
| `WEATHER_API_KEY` | *(empty)* | API key for real weather; empty = fully mock weather |
| `WEATHER_MOCK_MODE` | `false` | `true` forces the deterministic offline mock |
| `WEATHER_CSV_PATH` | `data/samples/weather_historical.csv` | Historical weather CSV for `WEATHER_PROVIDER=csv` |
| `WEATHER_DEFAULT_LAT` | `19.17` | Default latitude for live forecasts |
| `WEATHER_DEFAULT_LON` | `74.73` | Default longitude for live forecasts |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated browser origins allowed |
| `NEXT_PUBLIC_API_URL` | `http://localhost:3000` | API base the frontend calls (baked at build time) |
| `DOMAIN_THRESHOLDS_FILE` | `backend/app/config/domain_thresholds.yaml` | Override validation thresholds |
| `PROXY_LABELS_CONFIG_FILE` | `backend/app/config/proxy_labels.yaml` | Override proxy-label rules |
| `MAX_UPLOAD_MB` | `50` | Maximum upload file size in MB |
| `PHYSICAL_EQUIPMENT_CONTROL` | `false` | **Must be false for prototype** — when true, sends commands to real actuators |
| `ALLOW_AUTO_RETRAIN` | `true` | Allow automatic retraining after feedback ingestion |
| `DEBUG` | `true` | Verbose logging |

> Demo pans are anchored to a fixed twin date (`2024-05-01`). Forecasts are
> served by the deterministic mock provider. Set `AUTO_SEED=false` and register
> your own pans to use live weather.

---

## Database Migration Commands

Alembic migrations live in `backend/alembic/versions/` (5 versions):

| Migration | Description |
|-----------|-------------|
| `06ec381186dc` | Initial schema |
| `b273583dc823` | Phase 2: Normalized operational schema (10 tables) |
| `60c7818b02fe` | Phase 3: Dataset upload + validation columns |
| `a1b2c3d4e5f6` | Phase 6: ML training columns on `model_versions` |
| `c1f0d2e3b4a5` | Phase 10: Recommendation `consequence_if_waited` column |

```bash
# Run all pending migrations
cd backend && alembic upgrade head

# Check current migration version
alembic current

# Roll back one step
alembic downgrade -1

# Generate a new migration after model changes
alembic revision --autogenerate -m "description"
```

In Docker, migrations run automatically at container startup before uvicorn.

---

## Dataset Formats

Four dataset types are supported. Type is auto-detected from CSV headers
(overridable via `dataset_type` parameter).

### Sensor Dataset

Required columns:

| Column | Description | Unit |
|--------|-------------|------|
| `timestamp` | Reading time (ISO 8601) | datetime |
| `pan_id` | Pan identifier (e.g. PAN-1) | string |
| `pan_area_m2` | Pan surface area | m² |
| `salinity_g_l` | Brine salinity | g/L |
| `water_depth_cm` | Water depth | cm |
| `brine_temperature_c` | Brine temperature | °C |
| `humidity_pct` | Relative humidity | % |

### Weather Dataset

Required columns:

| Column | Description | Unit |
|--------|-------------|------|
| `timestamp` | Observation time | datetime |
| `pan_id` or `location` | Pan ID or location name | string |
| `forecast_rain_mm` | Forecast rainfall (24h) | mm |
| `rain_probability_pct` | Rain probability | % |
| `actual_rainfall_mm` | Actual observed rainfall | mm |
| `air_temperature_c` | Air temperature | °C |
| `humidity_pct` | Relative humidity | % |
| `wind_speed_m_s` | Wind speed | m/s |

### Operations Dataset

Required columns:

| Column | Description | Unit |
|--------|-------------|------|
| `event_timestamp` | Operation time | datetime |
| `pan_id` | Pan identifier | string |
| `event_type` | Operation type (drain / transfer / pump / protect / harvest) | string |
| `transferred_volume_l` | Volume transferred | L |
| `pump_duration_min` | Pump duration | min |
| `protection_applied` | Protection used (true/false) | bool |
| `harvest_date` | Harvest date | date |
| `actual_yield_kg` | Harvest yield | kg |
| `salt_purity_pct` | Salt purity | % |
| `yield_loss_pct` | Yield loss | % |

### Combined Dataset (Legacy Master)

Required columns:

| Column | Description | Unit |
|--------|-------------|------|
| `pan_id` | Pan identifier | string |
| `date` | Observation date | date |
| `temperature_c` | Temperature | °C |
| `humidity_pct` | Humidity | % |
| `wind_speed_kmh` | Wind speed | km/h (auto-converted to m/s) |
| `rainfall_mm` | Rainfall | mm |
| `sunshine_hours` | Sunshine duration | hours |
| `water_level_cm` | Water level | cm |
| `brine_density_be` | Brine density | °Bé |
| `salt_thickness_mm` | Salt bed thickness | mm |
| `days_since_last_rain` | Dry days counter | days |

> Column headers are fuzzy-matched via aliases in
> `backend/app/config/domain_thresholds.yaml`. For example,
> `Forecast Rain (mm/24h)` maps to `forecast_rain_mm`.

### Outcome / Feedback Dataset (for `POST /api/outcomes`)

| Column | Description | Unit |
|--------|-------------|------|
| `pan_id` | Pan identifier | string |
| `harvest_date` | Harvest date | date |
| `actual_yield_kg` | Actual yield | kg |
| `salt_purity_pct` | Salt purity | % |
| `actual_rainfall_mm` | Observed rainfall | mm |
| `rain_damage` | Rain damage occurred (true/false) | bool |
| `yield_loss_pct` | Yield loss | % |
| `outcome_notes` | Free-text notes | string |

---

## Model Training Instructions

### Via the UI

1. Open the **Models** tab
2. Click **Train All Models** (trains all 5 kinds) or select a specific kind
3. View training results: dataset used, train/test split, metrics, proxy flag
4. Activate the desired model version

### Via the API

```bash
# Train all 5 model kinds
curl -X POST http://localhost:8000/api/models/train

# Train a specific kind
curl -X POST http://localhost:8000/api/models/train \
  -H "Content-Type: application/json" \
  -d '{"model_kind": "climate_risk_classifier"}'

# List trained models
curl http://localhost:8000/api/models

# Activate a specific version
curl -X POST http://localhost:8000/api/models/{id}/activate
```

### Model Kinds

| Kind | Algorithm | Target | Type |
|------|-----------|--------|------|
| `harvest_readiness` | GradientBoostingRegressor | `harvest_readiness` (0–1) | Scorer |
| `climate_risk` | GradientBoostingRegressor | `climate_risk` (0–1) | Scorer |
| `climate_risk_classifier` | RandomForestClassifier | `risk_level` (LOW/MEDIUM/HIGH) | Classifier |
| `harvest_readiness_classifier` | RandomForestClassifier | `harvest_ready` (0/1) | Classifier |
| `harvest_time_regressor` | RandomForestRegressor | `hours_to_harvest` | Regressor |

**Time-based split:** All models use an 80/20 chronological split — no future
data leaks into training.

**Proxy vs field labels:** Models trained on proxy (synthesised) labels report
`uses_proxy_labels: true`. The UI shows a persistent banner:

> **PROXY/SIMULATED MODEL — NOT YET FIELD VALIDATED**

The `harvest_time_regressor` is **deferred** when no verified field outcomes
exist in the training pool.

---

## Weather Configuration

| Mode | `WEATHER_PROVIDER` | Behaviour |
|------|-------------------|-----------|
| Auto | `auto` | Try live API, fall back to deterministic mock |
| Live | `live` | Require real API; mock fallback on outages |
| Mock | `mock` | Always built-in deterministic offline generator |
| CSV | `csv` | Serve day-by-day from a historical weather CSV |

- `WEATHER_API_KEY` empty → app runs fully on mock weather
- `WEATHER_MOCK_MODE=true` → force mock from any configuration
- `WEATHER_CSV_PATH` → path to historical CSV (missing file falls back to mock)
- **Forecast and observed rainfall are stored separately** — `forecast_rain_mm`
  never mutates; `actual_rainfall_mm` is stamped via `POST /api/weather/actual`

---

## Demo Workflow

With `AUTO_SEED=true` (default), the following is pre-loaded on first boot:

### 1. Explore the Dashboard

Open http://localhost:3000 → **Dashboard** tab shows 3 demo pans with
digital-twin state, readiness scores, and climate risk.

### 2. View a Pan's Digital Twin

**Pans** tab → click a pan → view salinity, depth, brine temperature, volume,
dissolved salt mass, forecast rain, predicted post-rain state, evaporation,
readiness, and climate risk.

### 3. Run a Rain Simulation

**Simulator** tab → select a pan → set rainfall to **20 mm** → click
**Simulate**. View before/after salinity & depth, risk change, harvest delay,
and recommended action.

### 4. Upload a Dataset

**Dataset** tab → choose a CSV file → click **Upload** → review validation
report → click **Import** to confirm.

### 5. Train Models

**Models** tab → click **Train All** → review metrics and proxy flag → activate
the best version.

### 6. Generate a Prediction

**Predictions** are auto-generated when sensor readings arrive (if an active
model exists), or manually via `POST /api/predictions/run`.

### 7. Get a Recommendation

**Recommendations** tab → view generated advice with:
- Recommended action + deadline
- Three SHAP-backed reasons
- Confidence percentage
- Consequence if the farmer waits
- Step-by-step instructions

### 8. Accept or Reject

**Recommendations** tab → click **Accept** or **Reject** → add optional notes.

### 9. Record an Outcome

**Outcomes** tab → record actual yield, purity, rainfall, damage, and loss.

### 10. View Feedback

**Feedback** tab → see how outcomes compare to predictions → trigger model
retraining with the new data.

---

## API Endpoint List

| Method | Path | Description |
|--------|------|-------------|
| **System** | | |
| GET | `/api/health` | Health probe (app, environment, database) |
| GET | `/api/system/status` | Counts + per-kind model availability |
| GET | `/api/system/safety` | Equipment safety guardrail status |
| **Datasets** | | |
| GET | `/api/datasets` | List uploaded datasets |
| GET | `/api/datasets/thresholds` | Logical-range + outlier config |
| POST | `/api/datasets/preview` | Analyse file without persisting |
| POST | `/api/datasets/upload` | Store + validate a CSV |
| GET | `/api/datasets/{id}` | Dataset detail |
| GET | `/api/datasets/{id}/analysis` | Full quality report |
| GET | `/api/datasets/{id}/preview` | Preview imported rows |
| GET | `/api/datasets/{id}/invalid_rows` | Download rejected rows CSV |
| POST | `/api/datasets/{id}/import` | Confirm import of valid rows |
| POST | `/api/datasets/{id}/validate` | Re-run validation |
| POST | `/api/datasets/{id}/promote` | Promote to training pool |
| GET | `/api/datasets/{id}/file` | Download original file |
| **Pans** | | |
| GET | `/api/pans` | List all pans |
| POST | `/api/pans` | Register a new pan |
| GET | `/api/pans/{id}` | Pan detail |
| PATCH | `/api/pans/{id}` | Update pan properties |
| GET | `/api/pans/{id}/digital-twin` | Full digital twin snapshot |
| GET | `/api/pans/{id}/twin` | Twin state (legacy) |
| POST | `/api/pans/{id}/twin` | Update twin state |
| POST | `/api/pans/{id}/simulate-rain` | What-if rain simulation |
| POST | `/api/pans/{id}/predict` | Run prediction for a pan |
| GET | `/api/pans/{id}/snapshots` | Twin history snapshots |
| GET | `/api/pans/{id}/sensors` | Sensor readings for a pan |
| GET | `/api/pans/{id}/operations` | Operations for a pan |
| **Models** | | |
| GET | `/api/models` | List all model versions |
| GET | `/api/models/latest` | Newest version per kind |
| GET | `/api/models/label-status` | Proxy/field label provenance |
| POST | `/api/models/train` | Train models (all kinds or one) |
| GET | `/api/models/{id}` | Model version detail |
| GET | `/api/models/{id}/shap` | SHAP values for a model |
| POST | `/api/models/{id}/activate` | Activate a version |
| **Weather** | | |
| GET | `/api/weather/forecast` | Get weather forecast |
| POST | `/api/weather/actual` | Record observed rainfall |
| **Predictions** | | |
| POST | `/api/predictions/run` | Run 7-day readiness + risk forecast |
| GET | `/api/predictions` | List predictions |
| GET | `/api/predictions/{id}` | Prediction detail with SHAP explain |
| **Simulations** | | |
| POST | `/api/simulations/what-if-rain` | What-if rain twin simulation |
| **Recommendations** | | |
| GET | `/api/recommendations` | List recommendations |
| POST | `/api/recommendations/generate` | Generate rule-based advice |
| GET | `/api/recommendations/active` | Active recommendations |
| GET | `/api/recommendations/{id}` | Recommendation detail |
| POST | `/api/recommendations/{id}/accept` | Farmer accepts |
| POST | `/api/recommendations/{id}/reject` | Farmer rejects |
| POST | `/api/recommendations/{id}/complete` | Mark completed |
| POST | `/api/recommendations/{id}/respond` | Accept/decline with notes |
| **Sensors** | | |
| POST | `/api/sensors/readings` | Ingest sensor reading → update twin |
| **Outcomes** | | |
| POST | `/api/outcomes` | Record verified field outcome |
| GET | `/api/outcomes` | List outcomes |
| GET | `/api/outcomes/{id}` | Outcome detail |
| POST | `/api/outcomes/{id}/verify` | Verify an outcome |
| **Evaluation** | | |
| GET | `/api/evaluation/comparison` | Prediction vs outcome comparison |
| GET | `/api/evaluation/summary` | Precision/recall, MAE metrics |
| POST | `/api/evaluation/feedback` | Fold outcomes into retraining |
| POST | `/api/evaluation/retrain` | Trigger retraining |

Full OpenAPI spec: http://localhost:8000/docs

---

## Test Commands

### Backend Tests

```bash
cd backend
source .venv/bin/activate
pytest -v                  # run all tests
pytest -q                  # quiet mode
pytest tests/test_phase15_integration.py  # integration tests
```

**Test files (15):**

| File | Tests | Coverage |
|------|-------|----------|
| `test_health.py` | 2 | Health + system status |
| `test_datasets.py` | 5 | Upload, validation, garbage data |
| `test_ingestion.py` | 9 | Column mapping, unit conversion, duplicates |
| `test_proxy_labels.py` | 10 | Determinism, formulas, leakage map |
| `test_pipeline.py` | 2 | End-to-end pipeline, what-if regression |
| `test_phase6_training.py` | 8 | Time-split, classifiers, regressor, activation |
| `test_phase7_digital_twin.py` | 7 | Sensors, twin update, pan-code routing |
| `test_phase8_weather.py` | 9 | Mock, live, CSV, fallback, forecast storage |
| `test_phase9_simulator.py` | 7 | Physics, risk monotonicity, unit invariants |
| `test_phase10_explainability.py` | 9 | Glossary, SHAP factors, 6-part contract |
| `test_phase13_feedback.py` | 3 | Feedback loop, retrain, noop |
| `test_phase14_seed.py` | 5 | Demo data, 30-day sensors, weather |
| `test_phase15_integration.py` | ~55 | Full stack across 12 test classes |

### Frontend Build

```bash
cd frontend
npm run build       # type-check + lint + production bundle
npm run lint        # ESLint only
npm test            # Jest (passWithNoTests)
```

---

## Known Limitations

1. **Prototype thresholds** — all validation bounds in
   `domain_thresholds.yaml` are un-calibrated defaults pending field
   verification with real instruments and pan geometries.

2. **Proxy labels** — models trained without verified field outcomes use
   synthesised mass-balance labels. Metrics against proxy-labelled data are
   **self-consistency checks**, not independent validation.

3. **No authentication** — the application has no user authentication or
   role-based access control. All endpoints are open.

4. **No real-time WebSocket** — sensor readings are polled via HTTP; there is
   no push notification for twin state changes.

5. **Harvest time regressor deferred** — without verified field outcomes in the
   training pool, the `harvest_time_regressor` cannot train and is skipped.

6. **Fixed demo twin date** — seeded demo pans are anchored to `2024-05-01`.
   Live weather responses would be physically inconsistent with the demo twin
   state.

7. **Single-tenant** — designed for one operator. No multi-user, multi-tenant,
   or row-level security.

8. **SQLite limitations** — the local no-Docker SQLite fallback lacks
   concurrent-write performance and JSON query features of PostgreSQL.

9. **No physical actuator integration** — `PHYSICAL_EQUIPMENT_CONTROL` is
   `false` by default. Real pump/gate control requires a certified safety
   review.

10. **Upload size** — default max 50 MB (`MAX_UPLOAD_MB`). Large historical
    datasets may need this increased.

---

## Proxy-Data Disclosure

The application distinguishes three types of data:

### Field Data
Real measurements from physical sensors or verified harvest records. Identified
by `label_source == "field"`, per-label `*_source == "field"` columns, or
`source == "feedback"` from the verified outcome loop.

### Proxy Data
Values synthesised from documented mass-balance calculations and configurable
expert rules when field measurements are unavailable. Every proxy value is
stamped `*_source == "proxy"`. See `backend/app/config/proxy_labels.yaml` and
[`docs/proxy_label_methodology.md`](docs/proxy_label_methodology.md).

### Simulated Data
Weather forecasts from the mock provider, digital-twin state projections, and
what-if rain simulation results. These are physics-based computations, not
field observations.

**UI transparency:** When any active model uses proxy labels, the dashboard
displays a persistent amber banner:

> **PROXY/SIMULATED MODEL — NOT YET FIELD VALIDATED**

The `ModelVersion.uses_proxy_labels` flag (DB column + API + artifact metadata)
is `true` whenever *any* training row used a proxy label, including mixed
field/proxy datasets.

---

## Field-Validation Requirements

Before production deployment, the following must be completed:

1. **Calibrate `domain_thresholds.yaml`** — replace prototype bounds with
   instrument-specific ranges from the actual sensor hardware and local pan
   geometry. Flip `meta.status` from `prototype` to `calibrated`.

2. **Calibrate `proxy_labels.yaml`** — tune mass-balance constants
   (`density_base_be`, `rain_weight`, `dissolution_per_rain_mm`, etc.) against
   real salt-pan operations data.

3. **Collect verified field outcomes** — record actual harvest yields, rain
   damage, and purity for at least one full season to replace proxy labels with
   field-proven targets.

4. **Retrain in field-data mode** — after collecting verified outcomes, retrain
   all models. Verify `uses_proxy_labels` transitions to `false`.

5. **Validate SHAP explanations** — confirm that the top SHAP factors align
   with agronomic domain knowledge for the specific salt-pan region.

6. **Safety review** — before enabling `PHYSICAL_EQUIPMENT_CONTROL`, conduct a
   formal safety review of the actuator integration.

---

## Screenshots Section

> Screenshots can be added here after running the application. Capture:
>
> - Dashboard overview with 3 demo pans
> - Digital twin detail view
> - Rain simulation results (20 mm scenario)
> - Dataset upload + validation report
> - Model training results with metrics
> - Recommendation card with SHAP reasons
> - Farmer accept/reject flow
> - Feedback comparison view
> - Proxy warning banner
> - English / Tamil language toggle

---

## Sample CSV Templates

Template files are in `data/samples/`:

| File | Dataset Type |
|------|-------------|
| `data/samples/template_sensor.csv` | Sensor readings |
| `data/samples/template_weather.csv` | Weather observations |
| `data/samples/template_operations.csv` | Operations + harvest outcomes |
| `data/samples/template_combined.csv` | Combined master dataset |
| `data/samples/template_outcomes.csv` | Field outcomes for feedback |

---

## Recommended Next Steps

1. **Collect real sensor data** — deploy IoT sensors to 2–3 pans and stream
   readings via `POST /api/sensors/readings`
2. **Record verified outcomes** — log actual harvest yields and rain damage
   through the Outcomes tab
3. **Retrain with field data** — after one season, retrain models and verify
   the proxy banner disappears
4. **Calibrate thresholds** — adjust `domain_thresholds.yaml` to match local
   instrument ranges
5. **Add authentication** — implement JWT or OAuth2 for multi-user access
6. **WebSocket updates** — add real-time push for twin state changes
7. **Mobile responsiveness** — optimize the dashboard for tablet/phone use
   in the field
8. **Tamil translation audit** — verify the i18n Tamil strings with native
   speakers
9. **Integration testing** — add end-to-end tests with Playwright or Cypress
10. **Deploy to staging** — set up a cloud deployment with real PostgreSQL and
    live weather API
