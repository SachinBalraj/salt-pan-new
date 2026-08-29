from __future__ import annotations

import datetime as dt
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Prediction, Recommendation, SaltPan
from app.schemas import RecommendationOut, RespondRequest
from app.services.predictor import day0_features, local_shap_values, scored_timeline
from app.services.recommendation_engine import generate_recommendations

router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])


@router.get("", response_model=List[RecommendationOut])
def list_recommendations(pan_id: Optional[int] = None, status: Optional[str] = None,
                         db: Session = Depends(get_db)):
    q = db.query(Recommendation).order_by(Recommendation.created_at.desc())
    if pan_id:
        q = q.filter(Recommendation.pan_id == pan_id)
    if status:
        q = q.filter(Recommendation.status == status)
    return q.limit(200).all()


@router.post("/generate", response_model=List[RecommendationOut], status_code=201)
def generate(pan_id: int, db: Session = Depends(get_db)):
    pan = db.get(SaltPan, pan_id)
    if not pan:
        raise HTTPException(404, "Salt pan not found")

    from app.config import get_settings
    from app.ml.model_store import load_model
    from app.routers.predictions import latest_model, resolve_forecast

    settings = get_settings()
    forecast_days = resolve_forecast(db, pan, 7)
    models = {}
    for kind in ("harvest_readiness", "climate_risk"):
        m = latest_model(db, kind)
        models[kind] = load_model(kind, settings.models_path, version=m.version)["model"]

    start_date = pan.twin_state.get("demo_today") or dt.date.today().isoformat()
    timeline = scored_timeline(pan, forecast_days, models, start_date=start_date)
    shap = {}
    for kind in ("harvest_readiness", "climate_risk"):
        fd = day0_features(pan, forecast_days, kind)
        shap[kind] = local_shap_values(models[kind], list(fd.values()), list(fd.keys()))

    pred = Prediction(
        pan_id=pan.id,
        prediction_type="combined",
        scenario="actual_forecast",
        score=float(timeline[0]["readiness"]),
        horizon_days=7,
        prediction_date=dt.date.today().isoformat(),
        forecast_date=timeline[0]["date"],
        features={**day0_features(pan, forecast_days, "harvest_readiness"),
                  "projected_yield_kg": pan.twin_state.get("estimated_salt_mass_kg", 0) or 0},
        shap_values=shap,
        series=timeline,
    )
    db.add(pred)
    db.flush()

    output: List[Recommendation] = []
    for rec in generate_recommendations(pan, timeline, shap=shap, prediction=pred)[:3]:
        r = Recommendation(
            pan_id=pan.id, prediction_id=pred.id,
            recommendation_type=rec["recommendation_type"],
            title=rec["title"], message=rec["message"],
            rationale=rec["rationale"], expected_benefit=rec["expected_benefit"],
            risk_level=rec["risk_level"],
        )
        db.add(r)
        output.append(r)
    db.commit()
    for r in output:
        db.refresh(r)
    return output


@router.post("/{rec_id}/respond", response_model=RecommendationOut)
def respond(rec_id: int, body: RespondRequest, db: Session = Depends(get_db)):
    rec = db.get(Recommendation, rec_id)
    if not rec:
        raise HTTPException(404, "Recommendation not found")
    if body.status not in ("accepted", "declined"):
        raise HTTPException(400, "status must be 'accepted' or 'declined'")
    rec.status = body.status
    rec.farmer_notes = body.farmer_notes
    rec.responded_at = dt.datetime.utcnow()
    db.commit()
    db.refresh(rec)
    return rec