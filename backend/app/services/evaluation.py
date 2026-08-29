from __future__ import annotations

import csv
import datetime as dt
import os
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import DataSet, Outcome, Prediction, SaltPan, TwinSnapshot
from app.services.digital_twin import apply_outcome_to_twin, normalise_state

RAIN_RISK_THRESHOLD_MM = 15.0


def _pred_matches_outcome(pred: Prediction, out: Outcome) -> bool:
    if out.prediction_id and pred.id == out.prediction_id:
        return True
    if pred.pan_id != out.pan_id:
        return False
    # A prediction made before the outcome date, same window.
    try:
        if pred.prediction_date and out.outcome_date:
            return pred.prediction_date <= out.outcome_date
    except Exception:
        pass
    return False


def comparison_rows(db: Session) -> List[dict]:
    outcomes = db.query(Outcome).order_by(Outcome.created_at.desc()).all()
    predictions = db.query(Prediction).order_by(Prediction.created_at.desc()).all()
    pans = {p.id: p for p in db.query(SaltPan).all()}
    rows: List[dict] = []
    for out in outcomes:
        pred: Optional[Prediction] = None
        if out.prediction_id:
            pred = next((p for p in predictions if p.id == out.prediction_id), None)
        if pred is None:
            pred = next((p for p in predictions if _pred_matches_outcome(p, out)), None)
        pan = pans.get(out.pan_id)
        hit = "na"
        error = None
        projected_yield = None
        pred_score = float(pred.score) if pred else None
        pred_type = pred.prediction_type if pred else ""
        risk_score = None
        if pred and pred.features and "max_risk_horizon" in pred.features:
            try:
                risk_score = float(pred.features["max_risk_horizon"])
            except (TypeError, ValueError):
                risk_score = None
        if pred_score is not None:
            risk_involved = pred_type in ("climate_risk", "combined")
            if risk_involved:
                r_score = risk_score if risk_score is not None else pred_score
                predicted_rain = r_score >= 0.5
                actual = out.risk_occurred
                hit = "hit" if (predicted_rain == actual) else "miss"
            if pred_type in ("harvest_readiness", "combined"):
                actual_harvest = 1.0 if out.action_taken == "harvest" else 0.0
                error = round(pred_score - actual_harvest, 4)
                if hit in ("na", "hit", "miss") and pred_type == "harvest_readiness":
                    hit = "hit" if abs(error) <= 0.15 else "miss"
                if pred_type == "combined" and risk_score is None:
                    hit = "hit" if abs(error) <= 0.15 else "miss"
        if pred and pred.features:
            projected_yield = pred.features.get("projected_yield_kg")
        if out.prediction_id and pred is None:
            pred_id_display = out.prediction_id
        else:
            pred_id_display = pred.id if pred else None
        rows.append({
            "outcome_id": out.id,
            "pan_id": out.pan_id,
            "pan_ref": pan.pan_id if pan else f"#{out.pan_id}",
            "prediction_id": pred_id_display,
            "prediction_type": pred_type or "none",
            "prediction_date": pred.prediction_date if pred else "",
            "prediction_score": pred_score,
            "outcome_date": out.outcome_date,
            "actual_rainfall_mm": out.actual_rainfall_mm,
            "risk_occurred": out.risk_occurred,
            "action_taken": out.action_taken,
            "actual_yield_kg": out.actual_yield_kg,
            "projected_yield_kg": projected_yield,
            "hit": hit,
            "error": error,
            "verified": out.verified,
        })
    return rows


def evaluation_summary(db: Session) -> dict:
    rows = comparison_rows(db)
    by_type: Dict[str, int] = {}
    for r in rows:
        by_type[r["prediction_type"]] = by_type.get(r["prediction_type"], 0) + 1

    risk_hits = [r for r in rows if r["hit"] in ("hit", "miss")]
    risk_hit = sum(1 for r in risk_hits if r["hit"] == "hit")
    tp = sum(1 for r in rows if r["hit"] == "hit" and r["risk_occurred"])
    fn = sum(1 for r in rows if r["hit"] == "miss" and r["risk_occurred"])
    fp = sum(1 for r in rows if r["hit"] == "miss" and not r["risk_occurred"])
    tn = sum(1 for r in rows if r["hit"] == "hit" and not r["risk_occurred"])

    readiness_errors = [abs(r["error"]) for r in rows if r["error"] is not None]
    yield_errors = [abs(r["projected_yield_kg"] - r["actual_yield_kg"])
                    for r in rows if r["projected_yield_kg"] and r["actual_yield_kg"]]

    delays = [r for r in rows if r["prediction_type"] in ("harvest_readiness", "combined")]
    rec_counts: Dict[str, int] = {}
    from app.models import Recommendation
    for s, c in db.query(Recommendation.status, Recommendation.risk_level).all():
        rec_counts[s] = rec_counts.get(s, 0) + 1

    return {
        "total_outcomes": len(rows),
        "verified_outcomes": sum(1 for r in rows if r["verified"]),
        "risk_accuracy": round(risk_hit / len(risk_hits), 3) if risk_hits else None,
        "risk_tp": tp, "risk_tn": tn, "risk_fp": fp, "risk_fn": fn,
        "readiness_mae": round(sum(readiness_errors) / len(readiness_errors), 4) if readiness_errors else None,
        "yield_mae_kg": round(sum(yield_errors) / len(yield_errors), 1) if yield_errors else None,
        "harvest_delay_mean_days": None,
        "recommendations": rec_counts,
        "by_prediction_type": by_type,
    }


# ------------------------------------------------------------------ Feedback loop
def _default_row() -> dict:
    return {
        "pan_id": "", "date": "", "temperature_c": 0.0, "humidity_pct": 0.0,
        "wind_speed_kmh": 0.0, "rainfall_mm": 0.0, "sunshine_hours": 0.0,
        "water_depth_cm": 0.0, "brine_density_be": 0.0, "salt_thickness_mm": 0.0,
        "days_since_last_rain": 0, "precipitation_7d_forecast_mm": 0.0,
        "precipitation_probability_pct": 0.0,
        "harvest_readiness": 0.0, "climate_risk": 0.0,
        "harvest_ready_flag": 0, "yield_kg": 0.0, "action_recorded": "",
    }


def _outcome_to_row(out: Outcome, pan: SaltPan, pred: Optional[Prediction], twin_after: dict) -> dict:
    row = _default_row()
    row["pan_id"] = pan.pan_id
    row["date"] = out.outcome_date
    row["rainfall_mm"] = float(out.actual_rainfall_mm or 0.0)
    row["water_depth_cm"] = twin_after.get("water_depth_cm", 0.0)
    row["brine_density_be"] = float(out.brine_density_be if out.brine_density_be is not None
                                    else twin_after.get("brine_density_be", 0.0))
    row["salt_thickness_mm"] = float(out.salt_thickness_mm if out.salt_thickness_mm is not None
                                     else twin_after.get("salt_thickness_mm", 0.0))
    row["days_since_last_rain"] = int(twin_after.get("days_since_last_rain", 90))
    row["yield_kg"] = float(out.actual_yield_kg or 0.0)
    row["action_recorded"] = out.action_taken or ""
    row["harvest_ready_flag"] = 1 if out.action_taken == "harvest" else 0
    # Feature context from the linked prediction where available
    ctx: Dict[str, float] = {}
    if pred and pred.features:
        ctx = dict(pred.features)
    row["temperature_c"] = ctx.get("temperature_c", 0.0)
    row["humidity_pct"] = ctx.get("humidity_pct", 0.0)
    row["wind_speed_kmh"] = ctx.get("wind_speed_kmh", 0.0)
    row["sunshine_hours"] = ctx.get("sunshine_hours", 0.0)
    row["precipitation_7d_forecast_mm"] = ctx.get("precipitation_7d_forecast_mm", 0.0)
    row["precipitation_probability_pct"] = ctx.get("precipitation_probability_pct", 0.0)
    # Targets derived from the verified truth
    row["harvest_readiness"] = 1.0 if out.action_taken == "harvest" else 0.0
    row["climate_risk"] = 1.0 if out.risk_occurred else float(
        min(1.0, (out.actual_rainfall_mm or 0.0) / 60.0))
    return row


def feedback_ingest(db: Session, outcome_ids: Optional[List[int]] = None) -> dict:
    settings = get_settings()
    q = db.query(Outcome).filter(Outcome.verified.is_(True), Outcome.feedback_ingested.is_(False))
    if outcome_ids:
        q = q.filter(Outcome.id.in_(outcome_ids))
    outcomes = q.all()
    if not outcomes:
        return {"ingested": False, "outcome_ids": [], "twin_updated": [],
                "training_rows_added": 0, "feedback_dataset_id": None,
                "models_pending_retrain": False}

    collected_path = settings.processed_data_path / "collected_feedback.csv"
    header = list(_default_row().keys())
    new_rows_file = not collected_path.exists() or os.path.getsize(collected_path) == 0

    pans = {p.id: p for p in db.query(SaltPan).all()}
    preds = {p.id: p for p in db.query(Prediction).all()}
    twin_updated: List[int] = []
    rows: List[dict] = []
    ingested_ids: List[int] = []

    for out in outcomes:
        pan = pans.get(out.pan_id)
        if not pan:
            continue
        pred = preds.get(out.prediction_id) if out.prediction_id else None
        twin_after = apply_outcome_to_twin(pan, {
            "outcome_date": out.outcome_date,
            "actual_rainfall_mm": out.actual_rainfall_mm,
            "action_taken": out.action_taken,
            "harvest_date": out.harvest_date,
            "brine_density_be": out.brine_density_be,
            "salt_thickness_mm": out.salt_thickness_mm,
        })
        pan.twin_state = twin_after
        db.add(TwinSnapshot(pan_id=pan.id, snapshot_date=out.outcome_date,
                            source="outcome_feedback", state=twin_after))
        row = _outcome_to_row(out, pan, pred, twin_after)
        rows.append(row)
        ingested_ids.append(out.id)
        out.feedback_ingested = True
        twin_updated.append(pan.id)

    db.flush()

    # Persist rows to the evolving feedback training file (CSV).
    write_header = new_rows_file
    with open(collected_path, mode="a", newline="") as feed_file:
        writer = csv.DictWriter(feed_file, fieldnames=header, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        for r in rows:
            writer.writerow(r)

    # Register the feedback file as its own dataset record.
    dataset = DataSet(
        name=f"Model feedback {dt.date.today().isoformat()}",
        filename=collected_path.name,
        filepath=str(collected_path),
        rows_count=len(rows),
        columns=header,
        status="valid",
        source="feedback",
        validation_report={"note": "Verified-outcome feedback rows appended to training pool.",
                           "rows_appended": len(rows)},
    )
    db.add(dataset)
    db.flush()
    db.commit()

    return {
        "ingested": True,
        "outcome_ids": ingested_ids,
        "twin_updated": twin_updated,
        "training_rows_added": len(rows),
        "feedback_dataset_id": dataset.id,
        "models_pending_retrain": len(rows) > 0,
    }