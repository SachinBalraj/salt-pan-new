from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import ComparisonRow, EvaluationSummary, FeedbackResult
from app.services.evaluation import comparison_rows, evaluation_summary, feedback_ingest

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