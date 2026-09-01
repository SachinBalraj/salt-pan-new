from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import ComparisonRow, EvaluationSummary, FeedbackResult, RetrainResult
from app.services.evaluation import comparison_rows, evaluation_summary, feedback_ingest, retrain_with_feedback

router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])


@router.get("/comparison", response_model=List[ComparisonRow])
def comparison( db: Session = Depends(get_db)):
    return comparison_rows(db)


@router.get("/summary", response_model=EvaluationSummary)
def summary(db: Session = Depends(get_db)):
    return evaluation_summary(db)


@router.post("/feedback", response_model=FeedbackResult)
def ingest_feedback(outcome_ids: Optional[List[int]] = None, db: Session = Depends(get_db)):
    """Feed verified outcomes back into twins + future training dataset."""
    return feedback_ingest(db, outcome_ids)


@router.post("/retrain", response_model=RetrainResult)
def retrain_models(db: Session = Depends(get_db)):
    """Manual retrain using verified outcomes (never automatic)."""
    try:
        return retrain_with_feedback(db)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc