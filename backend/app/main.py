from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import Base, engine, ensure_schema, get_db
from app.models import (  # noqa: F401  (register models)
    DataSet,
    DigitalTwinState,
    HarvestOutcome,
    ModelVersion,
    OperationEvent,
    Pan,
    Prediction,
    Recommendation,
    SensorReading,
    WeatherReading,
)
from app.routers import (
    datasets,
    evaluation,
    models,
    outcomes,
    pans,
    predictions,
    recommendations,
    sensors,
    simulations,
    weather,
)

settings = get_settings()

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("saltlens")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.validate_startup()
    Base.metadata.create_all(bind=engine)
    ensure_schema(engine)  # idempotent column sync for pre-existing databases
    logger.info("SaltLens DSS started (env=%s, db=%s)", settings.environment, "postgres" if settings.is_postgres else "sqlite")
    if settings.physical_equipment_control:
        logger.critical(
            "PHYSICAL EQUIPMENT CONTROL IS ENABLED — "
            "the system WILL send commands to real actuators. "
            "Disable this unless a certified safety review is complete."
        )
    app.state.seeded = False
    if settings.auto_seed:
        from app.services.seeding import seed_all
        from app.database import SessionLocal

        db = SessionLocal()
        try:
            result = seed_all(db)
            app.state.seeded = True
        finally:
            db.close()
    yield


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="AI-driven digital twin decision support for climate-resilient salt pan management.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Request-logging middleware — assigns a correlation ID and logs timing
# ---------------------------------------------------------------------------
@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    correlation_id = str(uuid.uuid4())[:12]
    request.state.correlation_id = correlation_id
    start = time.monotonic()
    response = await call_next(request)
    elapsed_ms = round((time.monotonic() - start) * 1000, 1)
    logger.info(
        "[%s] %s %s → %s (%sms)",
        correlation_id,
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    response.headers["X-Correlation-ID"] = correlation_id
    return response


# ---------------------------------------------------------------------------
# Global exception handler — translates unhandled errors into structured JSON
# ---------------------------------------------------------------------------
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_server_error",
            "message": "An unexpected error occurred. Please try again later.",
            "detail": str(exc) if settings.debug else None,
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": "http_error",
            "message": exc.detail,
            "status_code": exc.status_code,
        },
    )


app.include_router(datasets.router)
app.include_router(pans.router)
app.include_router(models.router)
app.include_router(weather.router)
app.include_router(predictions.router)
app.include_router(simulations.router)
app.include_router(recommendations.router)
app.include_router(sensors.router)
app.include_router(outcomes.router)
app.include_router(evaluation.router)


@app.get("/api/health", tags=["system"])
def health():
    return {"status": "ok", "app": settings.app_name,
            "environment": settings.environment,
            "database": "postgresql" if settings.is_postgres else "sqlite",
            "physical_equipment_control": settings.physical_equipment_control}


@app.get("/api/system/safety", tags=["system"])
def safety_status():
    """Return the equipment-safety guardrail status.

    The frontend should display this prominently so operators always know
    whether real-world actuators can be triggered.
    """
    return {
        "physical_equipment_control_enabled": settings.physical_equipment_control,
        "auto_retrain_allowed": settings.allow_auto_retrain,
        "environment": settings.environment,
        "warning": (
            "PHYSICAL EQUIPMENT CONTROL IS ACTIVE — "
            "the system can send commands to real pumps/gates/valves."
            if settings.physical_equipment_control
            else "SAFE — the system operates in advisory-only mode. "
                 "All physical actions require manual farmer confirmation."
        ),
    }


@app.get("/api/system/status", tags=["system"])
def system_status(db: Session = Depends(get_db)):
    seeded = getattr(app.state, "seeded", False)
    pans = db.query(Pan).count()
    models_count = db.query(ModelVersion).count()
    datasets_count = db.query(DataSet).count()
    predictions_count = db.query(Prediction).count()
    recs = db.query(Recommendation).count()
    outcomes_count = db.query(HarvestOutcome).count()
    kind_status = {}
    for kind in ("harvest_readiness", "climate_risk", "climate_risk_classifier",
                 "harvest_readiness_classifier", "harvest_time_regressor"):
        m = (db.query(ModelVersion).filter(ModelVersion.model_type == kind)
             .order_by(ModelVersion.active.desc(), ModelVersion.created_at.desc()).first())
        kind_status[kind] = {
            "available": m is not None,
            "active": bool(m.active) if m else False,
            "id": m.id if m else None,
            "version": m.version if m else None,
            "target": getattr(m, "target_column", ""),
            "algorithm": getattr(m, "algorithm", ""),
            "metrics": m.metrics_json if m else {},
            "rows_trained": m.training_rows if m else 0,
            "test_rows": m.test_rows if m else 0,
            "training_errors": getattr(m, "training_errors_json", []) or [],
            "uses_proxy_labels": bool(m.uses_proxy_labels) if m else True,
        }
    any_active_model = bool(
        db.query(ModelVersion).filter(ModelVersion.active.is_(True)).first())
    return {
        "seeded": seeded,
        "pans": pans,
        "models": models_count,
        "model_kinds": kind_status,
        "any_active_model": any_active_model,
        "datasets": datasets_count,
        "predictions": predictions_count,
        "recommendations": recs,
        "outcomes": outcomes_count,
        "training_pool_file": str(settings.processed_data_path / "training.csv"),
        "feedback_pool_file": str(settings.processed_data_path / "collected_feedback.csv"),
    }