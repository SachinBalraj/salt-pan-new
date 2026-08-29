from __future__ import annotations

import datetime as dt
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import HarvestOutcome, Pan, Prediction
from app.schemas import OutcomeCreate, OutcomeOut
from app.services.serializers import outcome_to_dict

router = APIRouter(prefix="/api/outcomes", tags=["outcomes"])


def _gate_risk_occurred(rainfall_mm: float) -> bool:
    return rainfall_mm >= 15.0


@router.post("", response_model=OutcomeOut, status_code=201)
def create_outcome(body: OutcomeCreate, db: Session = Depends(get_db)):
    pan = db.get(Pan, body.pan_id)
    if not pan:
        raise HTTPException(404, "Salt pan not found")
    risk = body.risk_occurred if body.risk_occurred is not None \
        else _gate_risk_occurred(body.actual_rainfall_mm)

    outcome_date = body.outcome_date or dt.date.today().isoformat()
    harvest_date = body.harvest_date or outcome_date

    delayed_days = None
    if body.harvest_date:
        pred = db.get(Prediction, body.prediction_id) if body.prediction_id else None
        if pred:
            snap = dict(pred.input_snapshot_json or {})
            forecast_d = snap.get("forecast_date")
            try:
                fdate = dt.date.fromisoformat(str(forecast_d)) if forecast_d else None
                hdate = dt.date.fromisoformat(body.harvest_date)
                if fdate:
                    delayed_days = max(0, (hdate - fdate).days)
            except ValueError:
                delayed_days = None

    details = {
        "outcome_date": outcome_date,
        "harvest_date": harvest_date,
        "action_taken": body.action_taken,
        "harvest_delayed_days": delayed_days,
        "brine_density_be": body.brine_density_be,
        "salt_thickness_mm": body.salt_thickness_mm,
    }
    actual_rain = body.actual_rainfall_mm or 0.0

    out = HarvestOutcome(
        pan_id=body.pan_id,
        prediction_id=body.prediction_id,
        recommendation_id=body.recommendation_id,
        harvest_date=harvest_date,
        actual_yield_kg=body.actual_yield_kg,
        salt_purity_pct=None,
        actual_rainfall_mm=actual_rain,
        rain_damage=risk,
        yield_loss_pct=None,
        outcome_notes=body.notes,
        details_json=details,
    )
    db.add(out)
    db.commit()
    db.refresh(out)
    return outcome_to_dict(out)


@router.get("", response_model=List[OutcomeOut])
def list_outcomes(pan_id: Optional[int] = None, verified: Optional[bool] = None,
                  db: Session = Depends(get_db)):
    q = db.query(HarvestOutcome).order_by(HarvestOutcome.created_at.desc())
    if pan_id:
        q = q.filter(HarvestOutcome.pan_id == pan_id)
    if verified is not None:
        q = q.filter(HarvestOutcome.verified == verified)
    return [outcome_to_dict(o) for o in q.limit(300).all()]


@router.get("/{outcome_id}", response_model=OutcomeOut)
def get_outcome(outcome_id: int, db: Session = Depends(get_db)):
    out = db.get(HarvestOutcome, outcome_id)
    if not out:
        raise HTTPException(404, "Outcome not found")
    return outcome_to_dict(out)


@router.post("/{outcome_id}/verify", response_model=OutcomeOut)
def verify_outcome(outcome_id: int, db: Session = Depends(get_db)):
    out = db.get(HarvestOutcome, outcome_id)
    if not out:
        raise HTTPException(404, "Outcome not found")
    out.verified = True
    out.verified_at = dt.datetime.utcnow()
    if out.rain_damage is None:
        out.rain_damage = _gate_risk_occurred(out.actual_rainfall_mm or 0.0)
    db.commit()
    db.refresh(out)
    return outcome_to_dict(out)