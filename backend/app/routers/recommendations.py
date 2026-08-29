from __future__ import annotations

import datetime as dt
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import OperationEvent, Pan, Prediction, Recommendation
from app.schemas import RecommendationOut, RespondRequest
from app.services.digital_twin import get_twin_state
from app.services.recommendation_engine import generate_recommendations
from app.services.serializers import (
    make_prediction_row,
    recommendation_to_dict,
)

router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])


def _code(pan: Pan, action: str) -> str:
    stamp = dt.datetime.utcnow().strftime("%Y%m%d%H%M%S")
    return f"{action[:18]}-{pan.pan_code}-{stamp}-{uuid.uuid4().hex[:4]}"


def _deadline(action: str, timeline: List[dict]) -> Optional[dt.datetime]:
    if action == "harvest_now":
        return dt.datetime.utcnow() + dt.timedelta(days=1)
    if action in ("protect_pan", "store_brine"):
        rain_day = max((p for p in timeline if p["rainfall_mm"] > 0.5),
                       key=lambda p: p["rainfall_mm"], default=None)
        if rain_day:
            try:
                return dt.datetime.fromisoformat(str(rain_day["date"]))
            except ValueError:
                pass
    return dt.datetime.utcnow() + dt.timedelta(days=1)


def _to_row(pan: Pan, pred: Prediction, rec: dict) -> Recommendation:
    deadline = rec.get("action_deadline")
    if deadline:
        try:
            deadline = dt.datetime.fromisoformat(str(deadline))
        except ValueError:
            deadline = _deadline(rec["recommendation_type"], rec.get("_timeline") or [])
    else:
        deadline = _deadline(rec["recommendation_type"], rec.get("_timeline") or [])
    return Recommendation(
        recommendation_code=_code(pan, rec["recommendation_type"]),
        pan_id=pan.id,
        prediction_id=pred.id,
        timestamp=dt.datetime.utcnow(),
        recommended_action=rec["recommendation_type"],
        action_deadline=deadline,
        reason_1=rec.get("reason_1", ""),
        reason_2=rec.get("reason_2", ""),
        reason_3=rec.get("reason_3", ""),
        instruction_1=rec.get("instruction_1", ""),
        instruction_2=rec.get("instruction_2", ""),
        instruction_3=rec.get("instruction_3", ""),
        confidence_pct=rec.get("confidence_pct", 0.0),
        consequence_if_waited=rec.get("consequence_if_waited", ""),
        status="pending",
    )


@router.get("", response_model=List[RecommendationOut])
def list_recommendations(pan_id: Optional[int] = None, status: Optional[str] = None,
                         db: Session = Depends(get_db)):
    q = db.query(Recommendation).order_by(Recommendation.created_at.desc())
    if pan_id:
        q = q.filter(Recommendation.pan_id == pan_id)
    if status:
        q = q.filter(Recommendation.status == status)
    notes = {e.recommendation_id: e.operator_notes
             for e in db.query(OperationEvent).filter(
                 OperationEvent.event_type == "operator_response").all()}
    out = []
    for rec in q.limit(200).all():
        out.append(recommendation_to_dict(rec, farmer_notes=notes.get(rec.id, "")))
    return out


@router.post("/generate", response_model=List[RecommendationOut], status_code=201)
def generate(pan_id: int, db: Session = Depends(get_db)):
    pan = db.get(Pan, pan_id)
    if not pan:
        raise HTTPException(404, "Salt pan not found")

    from app.config import get_settings
    from app.routers.predictions import latest_model, load_models, resolve_forecast

    settings = get_settings()
    state = get_twin_state(db, pan)
    forecast_days = resolve_forecast(db, pan, 7)
    models, model_versions = load_models(db, settings)

    start_date = state.get("demo_today") or dt.date.today().isoformat()
    from app.services.predictor import scored_timeline

    timeline = scored_timeline(state, forecast_days, models, start_date=start_date)

    pred = make_prediction_row(
        db, pan,
        state=state,
        series=timeline,
        models=models,
        shap={},
        scenario="actual_forecast",
        horizon_days=7,
        model_version=model_versions["harvest_readiness"],
    )
    db.add(pred)
    db.flush()

    output: List[Recommendation] = []
    for rec in generate_recommendations(state, timeline, shap=None, prediction=pred)[:3]:
        rec["_timeline"] = timeline
        r = _to_row(pan, pred, rec)
        db.add(r)
        output.append(r)
    db.commit()
    for r in output:
        db.refresh(r)
    return [recommendation_to_dict(r) for r in output]


@router.get("/active", response_model=List[RecommendationOut])
def active_recommendations(pan_id: Optional[int] = None,
                           db: Session = Depends(get_db)):
    """Recommendations still waiting for a farmer decision (pending/accepted)."""
    q = db.query(Recommendation).filter(Recommendation.status.in_(("pending", "accepted")))
    if pan_id:
        q = q.filter(Recommendation.pan_id == pan_id)
    q = q.order_by(Recommendation.created_at.desc())
    return [recommendation_to_dict(r) for r in q.limit(100).all()]


@router.get("/{rec_id}", response_model=RecommendationOut)
def get_recommendation(rec_id: int, db: Session = Depends(get_db)):
    rec = db.get(Recommendation, rec_id)
    if not rec:
        raise HTTPException(404, "Recommendation not found")
    return recommendation_to_dict(rec, farmer_notes=_farmer_notes(db, rec))


def _farmer_notes(db: Session, rec: Recommendation) -> str:
    note = (db.query(OperationEvent)
            .filter(OperationEvent.recommendation_id == rec.id,
                    OperationEvent.event_type == "operator_response")
            .order_by(OperationEvent.created_at.desc()).first())
    return note.operator_notes if note else ""


def _respond(db: Session, rec_id: int, status: str) -> Recommendation:
    rec = db.get(Recommendation, rec_id)
    if not rec:
        raise HTTPException(404, "Recommendation not found")
    if rec.status == "completed":
        raise HTTPException(409, "This recommendation is already completed")
    rec.status = status
    rec.operator_accepted = status == "accepted"
    rec.operator_response_at = dt.datetime.utcnow()
    db.add(OperationEvent(
        pan_id=rec.pan_id,
        recommendation_id=rec.id,
        event_timestamp=dt.datetime.utcnow(),
        event_type="operator_response",
        operator_notes="farmer confirmation",
    ))
    db.commit()
    db.refresh(rec)
    return rec


@router.post("/{rec_id}/accept", response_model=RecommendationOut)
def accept_recommendation(rec_id: int, db: Session = Depends(get_db)):
    """Farmer approves the action: the recommendation becomes an operator
    record. The model still does not operate any pump/gate/drain itself."""
    rec = _respond(db, rec_id, "accepted")
    return recommendation_to_dict(rec, farmer_notes=_farmer_notes(db, rec))


@router.post("/{rec_id}/reject", response_model=RecommendationOut)
def reject_recommendation(rec_id: int, db: Session = Depends(get_db)):
    rec = _respond(db, rec_id, "rejected")
    return recommendation_to_dict(rec, farmer_notes=_farmer_notes(db, rec))


@router.post("/{rec_id}/complete", response_model=RecommendationOut)
def complete_recommendation(rec_id: int, db: Session = Depends(get_db)):
    """Farmer marks the accepted action as physically done in the field."""
    rec = db.get(Recommendation, rec_id)
    if not rec:
        raise HTTPException(404, "Recommendation not found")
    if rec.status != "accepted":
        raise HTTPException(409, "Only an accepted recommendation can be completed")
    rec.status = "completed"
    rec.operator_response_at = dt.datetime.utcnow()
    db.add(OperationEvent(
        pan_id=rec.pan_id,
        recommendation_id=rec.id,
        event_timestamp=dt.datetime.utcnow(),
        event_type="operator_response",
        operator_notes="action completed in the field",
    ))
    db.commit()
    db.refresh(rec)
    return recommendation_to_dict(rec, farmer_notes=_farmer_notes(db, rec))


@router.post("/{rec_id}/respond", response_model=RecommendationOut)
def respond(rec_id: int, body: RespondRequest, db: Session = Depends(get_db)):
    rec = db.get(Recommendation, rec_id)
    if not rec:
        raise HTTPException(404, "Recommendation not found")
    if body.status not in ("accepted", "declined"):
        raise HTTPException(400, "status must be 'accepted' or 'declined'")
    rec.status = body.status
    rec.operator_accepted = body.status == "accepted"
    rec.operator_response_at = dt.datetime.utcnow()
    db.add(OperationEvent(
        pan_id=rec.pan_id,
        recommendation_id=rec.id,
        event_timestamp=dt.datetime.utcnow(),
        event_type="operator_response",
        operator_notes=body.farmer_notes,
    ))
    db.commit()
    db.refresh(rec)
    notes = (db.query(OperationEvent)
             .filter(OperationEvent.recommendation_id == rec.id,
                     OperationEvent.event_type == "operator_response")
             .order_by(OperationEvent.created_at.desc()).first())
    return recommendation_to_dict(rec, farmer_notes=notes.operator_notes if notes else "")