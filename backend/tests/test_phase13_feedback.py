"""Phase 13: closed feedback loop.

Covers:
* outcome -> recommended-vs-actual action comparison
* forecast vs actual rainfall comparison
* predicted vs actual harvest date comparison
* predicted vs actual yield comparison
* recommendation success + acceptance/completion/success rates
* digital twin update at outcome-record time
* verified record appended to the future-training dataset
* manual retrain using verified outcomes
"""
import datetime as dt

from app.config import get_settings

_PAN = {
    "pan_id": "FB-1",
    "name": "Feedback Pan",
    "location": "Feedbackville",
    "area_m2": 2000.0,
    "latitude": 12.0,
    "longitude": 75.0,
}

# Forward mapping from recommendation code to the recorded action that
# satisfies it (mirror of evaluation.REC_ACTION_MATCH).
_REC_TO_ACTION = {
    "harvest_now": "harvest",
    "harvest_soon": "harvest",
    "protect_pan": "protected_pan",
    "store_brine": "stored_brine",
    "pump_excess": "pumped_water",
    "continue_evaporation": "no_action",
    "monitor": "no_action",
}


def _ready_harvest_pan(client, pan_overrides=None):
    payload = {
        **_PAN,
        **(pan_overrides or {}),
        "twin_state": {
            "brine_density_be": 26.5,
            "salt_thickness_mm": 15.0,
            "water_depth_cm": 9.0,
            "days_since_last_rain": 4,
        },
    }
    r = client.post("/api/pans", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _train_models(client, dataset_id):
    r = client.post("/api/models/train", json={"kind": "all", "dataset_id": dataset_id})
    assert r.status_code == 201, r.text
    return r.json()


def test_feedback_loop_metrics_and_retrain(client, sample_dataset_path):
    with open(sample_dataset_path, "rb") as fh:
        r = client.post("/api/datasets/upload",
                        files={"file": ("fb.csv", fh, "text/csv")})
    assert r.status_code == 201, r.text
    dataset_id = r.json()["id"]
    _train_models(client, dataset_id)

    pan = _ready_harvest_pan(client, {"pan_id": "FB-A"})

    # ---- 1. Prediction + recommendations --------------------------------
    r = client.post("/api/predictions/run",
                    json={"pan_id": pan["id"], "horizon_days": 7,
                          "scenario": "actual_forecast"})
    assert r.status_code == 200, r.text
    prediction = r.json()
    r = client.post("/api/recommendations/generate", params={"pan_id": pan["id"]})
    assert r.status_code == 201, r.text
    recs = r.json()
    assert recs, "expected recommendations for a harvest-ready pan"
    rec = recs[0]
    rec_id = rec["id"]
    advised = rec["recommendation_type"]
    assert advised in _REC_TO_ACTION, f"unexpected recommendation {advised}"

    r = client.post(f"/api/recommendations/{rec_id}/respond",
                    json={"status": "accepted", "farmer_notes": "Confirmed."})
    assert r.status_code == 200

    # ---- 2. Record outcome that FULFILS the advised action ---------------
    r = client.post("/api/outcomes", json={
        "pan_id": pan["id"],
        "prediction_id": prediction["id"],
        "recommendation_id": rec_id,
        "outcome_date": "2023-07-05",
        "actual_rainfall_mm": 42.0,
        "action_taken": _REC_TO_ACTION[advised],
        "harvest_date": "2023-07-06",
        "actual_yield_kg": 1800.0,
        "brine_density_be": 26.1,
        "salt_thickness_mm": 12.0,
    })
    assert r.status_code == 201, r.text
    outcome = r.json()
    assert outcome["risk_occurred"] is True

    # Twin was updated at record time (rain reset days_since_last_rain).
    twin = client.get(f"/api/pans/{pan['id']}/twin").json()
    assert twin["state"]["days_since_last_rain"] == 0

    # ---- 3. Comparisons ---------------------------------------------------
    rows = client.get("/api/evaluation/comparison").json()
    row = next(x for x in rows if x["outcome_id"] == outcome["id"])
    assert row["recommendation_id"] == rec_id
    assert row["recommended_action"], "linked outcome must carry the advised action"
    assert isinstance(row["action_matched"], bool)
    assert row["rain_error_mm"] is not None
    assert row["forecast_rainfall_mm"] is not None
    assert row["predicted_harvest_date"]
    assert row["harvest_date_error_days"] is not None
    assert row["yield_error_kg"] is not None
    # Harvest rec + realised harvest is a successful outcome.
    assert row["recommendation_success"] is True

    # ---- 4. Summary metrics ----------------------------------------------
    summary = client.get("/api/evaluation/summary").json()
    assert summary["recommendation_acceptance_rate"] == 1.0
    assert summary["recommendation_completion_rate"] is None or \
        isinstance(summary["recommendation_completion_rate"], float)
    assert summary["response_time_mean_hours"] is not None
    assert summary["response_time_median_hours"] is not None
    assert summary["harvest_date_mae_days"] is not None
    assert summary["forecast_rainfall_mae_mm"] is not None
    assert summary["recommendation_success_rate"] == 1.0
    assert summary["linked_outcomes"] >= 1
    assert summary["models_pending_retrain"] is False

    # ---- 5. Verify -> feedback pool (twin update + training rows) -------
    r = client.post(f"/api/outcomes/{outcome['id']}/verify")
    assert r.status_code == 200
    r = client.post("/api/evaluation/feedback")
    assert r.status_code == 200, r.text
    feedback = r.json()
    assert feedback["ingested"] is True
    assert outcome["id"] in feedback["outcome_ids"]
    assert feedback["training_rows_added"] >= 1

    # ---- 6. Manual retrain using verified outcomes ----------------------
    r = client.post("/api/evaluation/retrain")
    assert r.status_code == 200, r.text
    retrain = r.json()
    assert retrain["feedback_rows_used"] >= 1
    assert retrain["base_rows"] >= 1
    assert retrain["models_trained"] >= 2
    kinds = {m["kind"] for m in retrain["models"]}
    assert {"harvest_readiness", "climate_risk"}.issubset(kinds)

    # Retrain is manual-only: summary now reports no pending retrain.
    summary2 = client.get("/api/evaluation/summary").json()
    assert summary2["models_pending_retrain"] is False


def test_retrain_without_feedback_still_trains(client, sample_dataset_path):
    import os

    # Isolate from earlier tests in the same session.
    settings = get_settings()
    feedback_path = settings.processed_data_path / "collected_feedback.csv"
    if feedback_path.exists():
        os.remove(feedback_path)

    with open(sample_dataset_path, "rb") as fh:
        client.post("/api/datasets/upload", files={"file": ("nofb.csv", fh, "text/csv")})
    ds = client.get("/api/datasets").json()
    ds_id = max(d["id"] for d in ds)

    # No verified outcomes ingested yet -> retrain falls back to base data.
    r = client.post("/api/evaluation/retrain")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["feedback_rows_used"] == 0
    assert body["models_trained"] >= 1


def test_feedback_ingest_noop_without_verified_outcomes(client, sample_dataset_path):
    with open(sample_dataset_path, "rb") as fh:
        client.post("/api/datasets/upload", files={"file": ("emptyfb.csv", fh, "text/csv")})
    pan = _ready_harvest_pan(client, {"pan_id": "FB-C"})
    client.post("/api/predictions/run",
                json={"pan_id": pan["id"], "horizon_days": 7,
                      "scenario": "actual_forecast"})
    r = client.post("/api/outcomes", json={
        "pan_id": pan["id"],
        "outcome_date": "2024-01-10",
        "actual_rainfall_mm": 3.0,
        "action_taken": "no_action",
    })
    assert r.status_code == 201, r.text
    # Not verified -> must NOT enter the training pool.
    r = client.post("/api/evaluation/feedback")
    assert r.status_code == 200
    assert r.json()["ingested"] is False
    assert r.json()["training_rows_added"] == 0