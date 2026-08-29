from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import Base, engine, get_db
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
    simulations,
    weather,
)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
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

app.include_router(datasets.router)
app.include_router(pans.router)
app.include_router(models.router)
app.include_router(weather.router)
app.include_router(predictions.router)
app.include_router(simulations.router)
app.include_router(recommendations.router)
app.include_router(outcomes.router)
app.include_router(evaluation.router)


@app.get("/api/health", tags=["system"])
def health():
    return {"status": "ok", "app": settings.app_name,
            "environment": settings.environment,
            "database": "postgresql" if settings.is_postgres else "sqlite"}


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
    for kind in ("harvest_readiness", "climate_risk"):
        m = (db.query(ModelVersion).filter(ModelVersion.model_type == kind)
             .order_by(ModelVersion.active.desc(), ModelVersion.created_at.desc()).first())
        kind_status[kind] = {
            "available": m is not None,
            "id": m.id if m else None,
            "version": m.version if m else None,
            "metrics": m.metrics_json if m else {},
            "rows_trained": m.training_rows if m else 0,
        }
    return {
        "seeded": seeded,
        "pans": pans,
        "models": models_count,
        "model_kinds": kind_status,
        "datasets": datasets_count,
        "predictions": predictions_count,
        "recommendations": recs,
        "outcomes": outcomes_count,
        "training_pool_file": str(settings.processed_data_path / "training.csv"),
        "feedback_pool_file": str(settings.processed_data_path / "collected_feedback.csv"),
    }