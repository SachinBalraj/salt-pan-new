from __future__ import annotations

import datetime as dt
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Outcome, Prediction, Recommendation, SaltPan
from app.schemas import OutcomeCreate, OutcomeOut

router = APIRouter(prefix="/api/outcomes", tags=["outcomes"])


def _gate_risk_occurred(rainfall_mm: float) -> bool:
    return rainfall_mm >= 15.0


@router.post("", response_model=OutcomeOut, status_code=201)
def create_outcome(body: OutcomeCreate, db: Session = Depends(get_db)):
    pan = db.get(SaltPan, body.pan_id)
    if not pan:
        raise HTTPException(404, "Salt pan not found")
    risk = body.risk_occurred if body.risk_occurred is not None \
        else _gate_risk_occurred(body.actual_rainfall_mm)

    delayed_days = None
    if body.harvest_date:
        pred = db.get(Prediction, body.prediction_id) if body.prediction_id else None
        if pred and pred.forecast_date:
            try:
                forecast_d = dt.date.fromisoformat(pred.forecast_date)
                harvest_d = dt.date.fromisoformat(body.harvest_date)
                delayed_days = max(0, (harvest_d - forecast_d).days)
            except ValueError:
                delayed_days = None

    out = Outcome(
        pan_id=body.pan_id,
        prediction_id=body.prediction_id,
        recommendation_id=body.recommendation_id,
        outcome_date=body.outcome_date or dt.date.today().isoformat(),
        actual_rainfall_mm=body.actual_rainfall_mm,
        risk_occurred=risk,
        action_taken=body.action_taken,
        harvest_date=body.harvest_date,
        harvest_delayed_days=delayed_days,
        actual_yield_kg=body.actual_yield_kg,
        brine_density_be=body.brine_density_be,
        salt_thickness_mm=body.salt_thickness_mm,
        notes=body.notes,
    )
    db.add(out)
    db.commit()
    db.refresh(out)
    return out


@router.get("", response_model=List[OutcomeOut])
def list_outcomes(pan_id: Optional[int] = None, verified: Optional[bool] = None,
                  db: Session = Depends(get_db)):
    q = db.query(Outcome).order_by(Outcome.created_at.desc())
    if pan_id:
        q = q.filter(Outcome.pan_id == pan_id)
    if verified is not None:
        q = q.filter(Outcome.verified == verified)
    return q.limit(300).all()


@router.get("/{outcome_id}", response_model=OutcomeOut)
def get_outcome(outcome_id: int, db: Session = Depends(get_db)):
    out = db.get(Outcome, outcome_id)
    if not out:
        raise HTTPException(404, "Outcome not found")
    return out


@router.post("/{outcome_id}/verify", response_model=OutcomeOut)
def verify_outcome(outcome_id: int, db: Session = Depends(get_db)):
    out = db.get(Outcome, outcome_id)
    if not out:
        raise HTTPException(404, "Outcome not found")
    out.verified = True
    out.verified_at = dt.datetime.utcnow()
    if out.risk_occurred is None:
        out.risk_occurred = _gate_risk_occurred(out.actual_rainfall_mm)
    db.commit()
    db.refresh(out)
    return out