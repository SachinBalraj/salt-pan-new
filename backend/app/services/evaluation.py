from __future__ import annotations

import csv
import datetime as dt
import os
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import DataSet, HarvestOutcome, ModelVersion, Pan, Prediction, Recommendation
from app.services.digital_twin import apply_outcome_to_twin, get_twin_state, record_state

RAIN_RISK_THRESHOLD_MM = 15.0
RAIN_EVENT_MIN_MM = 5.0

# Recommendation code -> set of recorded "action_taken" values that satisfy it.
REC_ACTION_MATCH = {
    "harvest_now": {"harvest"},
    "harvest_soon": {"harvest"},
    "protect_pan": {"protected_pan", "covered_pans", "protection"},
    "store_brine": {"stored_brine", "transferred_brine", "brine_transfer"},
    "pump_excess": {"pumped_water", "drained_pan"},
    "continue_evaporation": {"no_action"},
    "monitor": {"no_action"},
}

# Provenance markers stamped on verified feedback rows when they are merged
# into a training frame, so ensure_labels / resolve_targets treat them as field.
FEEDBACK_FIELD_COLUMNS = [
    "harvest_readiness_source",
    "climate_risk_source",
    "recommended_action_source",
    "risk_level_source",
    "harvest_ready_source",
    "hours_to_harvest_source",
]


def _snapshot(pred: Optional[Prediction]) -> dict:
    if pred is None:
        return {}
    return dict(pred.input_snapshot_json or {})


def _details(out: HarvestOutcome) -> dict:
    return dict(out.details_json or {})


def _pred_matches_outcome(pred: Prediction, out: HarvestOutcome) -> bool:
    if out.prediction_id and pred.id == out.prediction_id:
        return True
    if pred.pan_id != out.pan_id:
        return False
    snap = _snapshot(pred)
    try:
        if snap.get("prediction_date") and out.harvest_date:
            return snap["prediction_date"] <= out.harvest_date
    except Exception:
        pass
    return False


def _as_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_date(v) -> Optional[dt.date]:
    if not v:
        return None
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _action_matched(rec_action: str, action_taken: str) -> bool:
    allowed = REC_ACTION_MATCH.get(rec_action)
    if allowed is None:
        return False
    return str(action_taken).strip() in allowed


def comparison_rows(db: Session) -> List[dict]:
    outcomes = db.query(HarvestOutcome).order_by(HarvestOutcome.created_at.desc()).all()
    predictions = db.query(Prediction).order_by(Prediction.created_at.desc()).all()
    pans = {k.id: k for k in db.query(Pan).all()}
    recs = {k.id: k for k in db.query(Recommendation).all()}
    rows: List[dict] = []
    for out in outcomes:
        panel = _details(out)
        pred: Optional[Prediction] = None
        if out.prediction_id:
            pred = next((p for p in predictions if p.id == out.prediction_id), None)
        if pred is None:
            pred = next((p for p in predictions if _pred_matches_outcome(p, out)), None)
        pan = pans.get(out.pan_id)
        rec = recs.get(out.recommendation_id) if out.recommendation_id else None

        snap = _snapshot(pred)
        features = snap.get("features") or {}
        hit = "na"
        error = None
        projected_yield = None
        pred_score = _as_float(snap.get("score")) if pred else None
        pred_type = snap.get("prediction_type", "none") if pred else "none"
        risk_score = None
        if pred and isinstance(features, dict) and "max_risk_horizon" in features:
            risk_score = _as_float(features["max_risk_horizon"])
        actual_rain_damage = bool(out.rain_damage)
        action_taken = str(panel.get("action_taken", ""))
        if pred_score is not None:
            risk_involved = pred_type in ("climate_risk", "combined")
            if risk_involved:
                r_score = risk_score if risk_score is not None else pred_score
                predicted_rain = r_score >= 0.5
                hit = "hit" if (predicted_rain == actual_rain_damage) else "miss"
            if pred_type in ("harvest_readiness", "combined"):
                actual_harvest = 1.0 if action_taken == "harvest" else 0.0
                error = round(float(pred_score) - actual_harvest, 4)
                if hit in ("na", "hit", "miss") and pred_type == "harvest_readiness":
                    hit = "hit" if abs(error) <= 0.15 else "miss"
                if pred_type == "combined" and risk_score is None:
                    hit = "hit" if abs(error) <= 0.15 else "miss"
        if pred and isinstance(features, dict):
            projected_yield = _as_float(features.get("projected_yield_kg"))

        # ---- Phase 13: full recommended-vs-actual comparison ----------------
        recommended_action = rec.recommended_action if rec else ""
        action_matched = None
        rec_success = None
        if rec:
            action_matched = _action_matched(recommended_action, action_taken)
            rec_success = bool(action_matched)

        forecast_rain = None
        if pred and isinstance(features, dict):
            forecast_rain = _as_float(features.get("precipitation_7d_forecast_mm"))
        rain_error = (forecast_rain - (out.actual_rainfall_mm or 0.0)
                      if forecast_rain is not None else None)

        predicted_harvest_date = None
        harvest_date_error_days = None
        if pred:
            p_h = _parse_date(snap.get("forecast_date"))
            pdate = _parse_date(snap.get("prediction_date"))
            actual_h = _parse_date(out.harvest_date) or _parse_date(panel.get("harvest_date"))
            if p_h:
                predicted_harvest_date = snap.get("forecast_date")
            elif pdate and pred.predicted_harvest_hours:
                p_h = pdate + dt.timedelta(hours=float(pred.predicted_harvest_hours))
                predicted_harvest_date = p_h.isoformat()
            if actual_h and p_h:
                harvest_date_error_days = int((actual_h - p_h).days)

        yield_error = None
        if projected_yield is not None and out.actual_yield_kg is not None:
            yield_error = round(projected_yield - float(out.actual_yield_kg), 1)

        pred_id_display = out.prediction_id if (out.prediction_id and pred is None) else (pred.id if pred else None)
        rows.append({
            "outcome_id": out.id,
            "pan_id": out.pan_id,
            "pan_ref": pan.pan_code if pan else f"#{out.pan_id}",
            "prediction_id": pred_id_display,
            "recommendation_id": rec.id if rec else None,
            "recommended_action": recommended_action,
            "action_matched": action_matched,
            "recommendation_success": rec_success,
            "prediction_type": pred_type,
            "prediction_date": snap.get("prediction_date", "") if pred else "",
            "prediction_score": pred_score if pred_score is not None else 0.0,
            "outcome_date": out.harvest_date,
            "actual_rainfall_mm": out.actual_rainfall_mm if out.actual_rainfall_mm is not None else 0.0,
            "forecast_rainfall_mm": forecast_rain,
            "rain_error_mm": round(rain_error, 2) if rain_error is not None else None,
            "predicted_harvest_date": predicted_harvest_date or None,
            "harvest_date_error_days": harvest_date_error_days,
            "risk_occurred": actual_rain_damage,
            "action_taken": action_taken,
            "actual_yield_kg": out.actual_yield_kg,
            "projected_yield_kg": projected_yield,
            "yield_error_kg": yield_error,
            "hit": hit,
            "error": error,
            "verified": out.verified,
            "feedback_ingested": out.feedback_ingested,
        })
    return rows


def _mae(values: List[float]) -> Optional[float]:
    values = [abs(float(v)) for v in values if v is not None]
    if not values:
        return None
    return round(float(np.mean(values)), 3)


def _recommendation_metrics(db: Session) -> dict:
    recs = db.query(Recommendation).all()
    total = len(recs)
    status: Dict[str, int] = {}
    response_hours: List[float] = []
    for r in recs:
        status[r.status] = status.get(r.status, 0) + 1
        if r.operator_response_at and r.created_at:
            delta = (r.operator_response_at - r.created_at).total_seconds() / 3600.0
            if delta >= 0:
                response_hours.append(delta)
    responded = status.get("accepted", 0) + status.get("completed", 0) \
        + status.get("declined", 0) + status.get("rejected", 0)
    accepted_or_completed = status.get("accepted", 0) + status.get("completed", 0)
    declined_or_rejected = status.get("declined", 0) + status.get("rejected", 0)
    completed = status.get("completed", 0)
    acceptance_rate = (accepted_or_completed / responded) if responded else None
    completion_rate = (completed / accepted_or_completed) if accepted_or_completed else None
    response_mean = round(float(np.mean(response_hours)), 2) if response_hours else None
    response_median = round(float(np.median(response_hours)), 2) if response_hours else None
    return {
        "total": total,
        "status_counts": status,
        "acceptance_rate": acceptance_rate,
        "completion_rate": completion_rate,
        "response_time_mean_hours": response_mean,
        "response_time_median_hours": response_median,
    }


def _feedback_state(db: Session) -> dict:
    settings = get_settings()
    collected_path = settings.processed_data_path / "collected_feedback.csv"
    rows_collected = 0
    if collected_path.exists():
        with open(collected_path) as fh:
            rows_collected = max(0, sum(1 for _ in fh) - 1)
    ingested_outcomes = db.query(HarvestOutcome).filter(
        HarvestOutcome.feedback_ingested.is_(True)).count()
    latest_fb_ds = db.query(DataSet).filter(
        DataSet.source == "feedback").order_by(
        DataSet.created_at.desc()).first()
    latest_model = db.query(ModelVersion).order_by(
        ModelVersion.created_at.desc()).first()
    pending = ingested_outcomes > 0 and (
        latest_model is None
        or (latest_fb_ds is not None
            and latest_fb_ds.created_at >= latest_model.created_at))
    return {
        "feedback_rows_collected": max(rows_collected, ingested_outcomes),
        "ingested_outcomes": ingested_outcomes,
        "models_pending_retrain": bool(pending),
    }


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
    harvest_errors = [r["harvest_date_error_days"] for r in rows
                      if r["harvest_date_error_days"] is not None]
    rain_errors = [r["rain_error_mm"] for r in rows if r["rain_error_mm"] is not None]

    linked = [r for r in rows if r["recommendation_success"] is not None]
    success = sum(1 for r in linked if r["recommendation_success"])
    matched = [r for r in linked if r["action_matched"] is not None]

    active_models = db.query(ModelVersion).all()
    proxy_in_use = any(m.uses_proxy_labels for m in active_models)
    proxy_note = (
        "At least one active model was trained on PROXY/SIMULATED labels "
        "(uses_proxy_labels=true). Accuracy reported here is prototype-only and "
        "must not be presented as field-validated performance."
        if proxy_in_use else
        "Active models were trained on real field labels (uses_proxy_labels=false)."
    )

    rec_metrics = _recommendation_metrics(db)
    feedback_state = _feedback_state(db)

    return {
        "total_outcomes": len(rows),
        "verified_outcomes": sum(1 for r in rows if r["verified"]),
        "risk_accuracy": round(risk_hit / len(risk_hits), 3) if risk_hits else None,
        "risk_tp": tp, "risk_tn": tn, "risk_fp": fp, "risk_fn": fn,
        "readiness_mae": round(sum(readiness_errors) / len(readiness_errors), 4) if readiness_errors else None,
        "yield_mae_kg": round(sum(yield_errors) / len(yield_errors), 1) if yield_errors else None,
        "harvest_delay_mean_days": _mae(harvest_errors),
        "harvest_date_mae_days": _mae(harvest_errors),
        "forecast_rainfall_mae_mm": _mae(rain_errors),
        "recommendations": rec_metrics["status_counts"],
        "by_prediction_type": by_type,
        "recommendation_acceptance_rate": rec_metrics["acceptance_rate"],
        "recommendation_completion_rate": rec_metrics["completion_rate"],
        "response_time_mean_hours": rec_metrics["response_time_mean_hours"],
        "response_time_median_hours": rec_metrics["response_time_median_hours"],
        "recommendation_success_rate": (success / len(linked)) if linked else None,
        "linked_outcomes": len(linked),
        "action_match_rate": round(len(matched) / len(matched), 3) if matched else None,
        "feedback_rows_collected": feedback_state["feedback_rows_collected"],
        "ingested_outcomes": feedback_state["ingested_outcomes"],
        "models_pending_retrain": feedback_state["models_pending_retrain"],
        "proxy_labels_in_use": proxy_in_use,
        "proxy_note": proxy_note,
    }


# ------------------------------------------------------------------ Feedback loop
def _default_row() -> dict:
    return {
        "pan_id": "", "date": "", "temperature_c": 0.0, "humidity_pct": 0.0,
        "wind_speed_kmh": 0.0, "rainfall_mm": 0.0, "sunshine_hours": 0.0,
        "water_depth_cm": 0.0, "brine_density_be": 0.0, "salt_thickness_mm": 0.0,
        "days_since_last_rain": 0, "precipitation_7d_forecast_mm": 0.0,
        "precipitation_probability_pct": 0.0,
        "harvest_readiness": float("nan"), "climate_risk": 0.0,
        "harvest_ready": 0, "harvest_ready_flag": 0, "yield_kg": 0.0,
        "action_recorded": "", "risk_level": "",
        "hours_to_harvest": float("nan"),
    }


def _outcome_to_row(out: HarvestOutcome, pan: Pan, pred: Optional[Prediction],
                    twin_after: dict) -> dict:
    row = _default_row()
    panel = _details(out)
    action_taken = str(panel.get("action_taken", ""))
    snap = _snapshot(pred)
    harvest_date = str(out.harvest_date or panel.get("harvest_date") or "")

    row["pan_id"] = pan.pan_code
    row["date"] = harvest_date
    row["rainfall_mm"] = float(out.actual_rainfall_mm or 0.0)
    row["water_depth_cm"] = twin_after.get("water_depth_cm", 0.0)
    row["brine_density_be"] = float(panel.get("brine_density_be")
                                    if panel.get("brine_density_be") is not None
                                    else twin_after.get("brine_density_be", 0.0))
    row["salt_thickness_mm"] = float(panel.get("salt_thickness_mm")
                                     if panel.get("salt_thickness_mm") is not None
                                     else twin_after.get("salt_thickness_mm", 0.0))
    row["days_since_last_rain"] = int(twin_after.get("days_since_last_rain", 90))
    row["yield_kg"] = float(out.actual_yield_kg or 0.0)
    row["action_recorded"] = action_taken
    row["harvest_ready_flag"] = 1 if action_taken == "harvest" else 0
    row["harvest_ready"] = row["harvest_ready_flag"]
    row["harvest_readiness"] = 1.0 if action_taken == "harvest" else float("nan")
    row["climate_risk"] = 1.0 if out.rain_damage else float(
        min(1.0, (out.actual_rainfall_mm or 0.0) / 60.0))
    row["risk_level"] = (
        "HIGH" if out.rain_damage else
        "MEDIUM" if (out.actual_rainfall_mm or 0.0) >= RAIN_EVENT_MIN_MM else "LOW")
    ctx: Dict[str, float] = {}
    if pred:
        ctx = dict((snap.get("features") or {}))
    row["temperature_c"] = ctx.get("temperature_c", 0.0)
    row["humidity_pct"] = ctx.get("humidity_pct", 0.0)
    row["wind_speed_kmh"] = ctx.get("wind_speed_kmh", 0.0)
    row["sunshine_hours"] = ctx.get("sunshine_hours", 0.0)
    row["precipitation_7d_forecast_mm"] = ctx.get("precipitation_7d_forecast_mm", 0.0)
    row["precipitation_probability_pct"] = ctx.get("precipitation_probability_pct", 0.0)

    # Verified hours-to-harvest: prediction creation -> actual harvest.
    if harvest_date:
        pdate = _parse_date(snap.get("prediction_date"))
        hdate = _parse_date(harvest_date)
        if pdate and hdate:
            row["hours_to_harvest"] = float((hdate - pdate).days * 24.0)
        elif hdate and pred and pred.predicted_harvest_hours:
            forecast_d = _parse_date(snap.get("forecast_date"))
            if forecast_d:
                row["hours_to_harvest"] = float((hdate - forecast_d).days * 24.0)
    return row


def feedback_ingest(db: Session, outcome_ids: Optional[List[int]] = None) -> dict:
    settings = get_settings()
    q = db.query(HarvestOutcome).filter(HarvestOutcome.verified.is_(True),
                                        HarvestOutcome.feedback_ingested.is_(False))
    if outcome_ids:
        q = q.filter(HarvestOutcome.id.in_(outcome_ids))
    outcomes = q.all()
    if not outcomes:
        return {"ingested": False, "outcome_ids": [], "twin_updated": [],
                "training_rows_added": 0, "feedback_dataset_id": None,
                "models_pending_retrain": False}

    collected_path = settings.processed_data_path / "collected_feedback.csv"
    header = list(_default_row().keys())
    new_rows_file = not collected_path.exists() or os.path.getsize(collected_path) == 0

    pans = {p.id: p for p in db.query(Pan).all()}
    preds = {p.id: p for p in db.query(Prediction).all()}
    twin_updated: List[int] = []
    rows: List[dict] = []
    ingested_ids: List[int] = []

    for out in outcomes:
        pan = pans.get(out.pan_id)
        if not pan:
            continue
        pred = preds.get(out.prediction_id) if out.prediction_id else None
        panel = _details(out)
        twin_after = apply_outcome_to_twin(get_twin_state(db, pan), {
            "outcome_date": out.harvest_date,
            "actual_rainfall_mm": out.actual_rainfall_mm,
            "action_taken": panel.get("action_taken"),
            "harvest_date": panel.get("harvest_date") or out.harvest_date,
            "brine_density_be": panel.get("brine_density_be"),
            "salt_thickness_mm": panel.get("salt_thickness_mm"),
        })
        record_state(db, pan, twin_after, source="outcome_feedback")
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
        "models_pending_retrain": True,
    }


# ------------------------------------------------------------------ Retrain (manual)
def _train_on_frame(db: Session, df: pd.DataFrame, dataset_source: str,
                    dataset: Optional[DataSet]) -> Tuple[List[dict], List[str], bool]:
    """Run the standard label + target pipeline and train every model kind."""
    from app.config.proxy_labels import get_proxy_labels_config
    from app.services.model_targets import resolve_targets
    from app.services.proxy_labels import ensure_labels
    from app.services.serializers import model_to_dict
    from app.services.training import train_model
    from app.routers.models import ALL_KINDS

    settings = get_settings()
    label_report = None
    target_report = None
    try:
        df, label_report = ensure_labels(df, get_proxy_labels_config(),
                                         dataset_source=dataset_source)
        df, target_report = resolve_targets(df, label_report,
                                            dataset_source=dataset_source)
    except Exception as exc:  # pragma: no cover - defensive
        raise ValueError(f"Label preparation failed: {exc}") from exc

    created: List[ModelVersion] = []
    errors: List[str] = []
    proxy_used = False
    for kind in ALL_KINDS:
        try:
            trained = train_model(kind, df, dataset.id if dataset else None,
                                  settings.models_path,
                                  labels_report=label_report,
                                  target_report=target_report,
                                  dataset_name=dataset.name if dataset else "combined")
        except ValueError as exc:
            errors.append(str(exc))
            continue
        split = trained.get("split") or {}
        trs, tre = split.get("train_dates") or [None, None]
        mv = ModelVersion(
            model_name=trained["model_name"],
            model_type=kind,
            algorithm=trained.get("algorithm", ""),
            target_column=trained.get("target", ""),
            version=trained["version"],
            model_path=trained["artifact_path"],
            training_rows=int(trained["rows_trained"]),
            test_rows=int(trained.get("test_rows", 0)),
            training_start_date=trs,
            training_end_date=tre,
            split_json=split,
            metrics_json=trained["metrics"],
            feature_names_json=trained["feature_names"],
            uses_proxy_labels=bool(trained["uses_proxy_labels"]),
            training_errors_json=trained.get("training_errors", []),
            dataset_id=dataset.id if dataset else None,
            active=bool(trained["version"] and trained["status"] == "trained"),
        )
        db.add(mv)
        created.append(mv)
        if trained.get("uses_proxy_labels"):
            proxy_used = True
    db.commit()
    for m in created:
        db.refresh(m)
    return [model_to_dict(m, db) for m in created], errors, proxy_used


def retrain_with_feedback(db: Session) -> dict:
    """Manual retrain: base dataset + all verified feedback rows.

    Feedback rows carry per-label `*_source = field` provenance so the label /
    target pipeline treats them as real measurements while the base dataset stays
    proxy where unprovenanced. Never invoked automatically.
    """
    settings = get_settings()
    base_q = db.query(DataSet).filter(DataSet.source != "feedback")
    base = base_q.filter(DataSet.status == "promoted").order_by(
        DataSet.created_at.desc()).first()
    if not base:
        base = base_q.order_by(DataSet.created_at.desc()).first()
    if not base:
        raise ValueError(
            "No dataset available. Upload one or re-seed the demo first.")

    base_df = pd.read_csv(base.filepath)
    feedback_path = settings.processed_data_path / "collected_feedback.csv"
    feedback_df = pd.DataFrame()
    if feedback_path.exists() and os.path.getsize(feedback_path) > 0:
        feedback_df = pd.read_csv(feedback_path)

    field_rows = len(feedback_df)
    source = base.source
    if field_rows > 0:
        # Verified feedback rows are REAL field records: stamp provenance.
        for col in FEEDBACK_FIELD_COLUMNS:
            feedback_df[col] = "field"
        combined = pd.concat([base_df, feedback_df], ignore_index=True)
        if "pan_id" in combined.columns and "date" in combined.columns:
            combined = combined.drop_duplicates(subset=["pan_id", "date"],
                                                keep="last")
        source = base.source
    else:
        combined = base_df

    models, errors, proxy_used = _train_on_frame(db, combined, source, base)
    return {
        "feedback_rows_used": int(field_rows),
        "base_dataset_id": base.id,
        "base_rows": int(len(base_df)),
        "combined_rows": int(len(combined)),
        "models_trained": len(models),
        "proxy_labels_in_use": proxy_used,
        "errors": errors,
        "models": models,
    }