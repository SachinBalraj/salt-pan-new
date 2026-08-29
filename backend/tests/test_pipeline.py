def _pan_payload():
    return {
        "pan_id": "TEST-1",
        "name": "Integration Test Pan",
        "location": "Testville",
        "area_m2": 2000.0,
        "latitude": 12.0,
        "longitude": 75.0,
    }


def test_end_to_end_pipeline(client, sample_dataset_path):
    # ---- 1. Upload dataset ------------------------------------------
    with open(sample_dataset_path, "rb") as fh:
        r = client.post("/api/datasets/upload", files={"file": ("pipeline.csv", fh, "text/csv")})
    assert r.status_code == 201, r.text
    dataset_id = r.json()["id"]
    assert r.json()["status"] == "valid"

    # ---- 2. Train models ---------------------------------------------
    r = client.post("/api/models/train", json={"kind": "all", "dataset_id": dataset_id})
    assert r.status_code == 201, r.text
    trained = r.json()
    kinds = {m["kind"] for m in trained}
    assert {"harvest_readiness", "climate_risk"}.issubset(kinds)
    ready_model = next(m for m in trained if m["kind"] == "harvest_readiness")
    assert ready_model["metrics"]["mae"] < 0.5

    # ---- 3. Create pan + twin ----------------------------------------
    r = client.post("/api/pans", json=_pan_payload())
    assert r.status_code == 201, r.text
    pan = r.json()
    assert pan["twin_state"]["brine_density_be"] == pan["twin_state"]["brine_density_be"]

    r = client.get(f"/api/pans/{pan['id']}/twin")
    assert r.status_code == 200
    assert "progress_to_harvest" in r.json()

    # ---- 4. Weather forecast -----------------------------------------
    r = client.get(f"/api/weather/forecast?pan_id={pan['id']}&days=7&scenario=mock")
    assert r.status_code == 200
    assert len(r.json()["days"]) == 7

    # ---- 5. Predict ---------------------------------------------------
    r = client.post("/api/predictions/run",
                    json={"pan_id": pan["id"], "horizon_days": 7, "scenario": "actual_forecast"})
    assert r.status_code == 200, r.text
    prediction = r.json()
    assert 0.0 <= prediction["day0"]["readiness"] <= 1.0
    assert len(prediction["series"]) == 7
    assert "harvest_readiness" in prediction["shap"]

    # ---- 6. What-if-rain simulation -----------------------------------
    r = client.post("/api/simulations/what-if-rain",
                    json={"pan_id": pan["id"], "horizon_days": 7,
                          "scenario": {"rainfall_mm": 35.0, "day_offset": 1, "dry_days_after": 3}})
    assert r.status_code == 200, r.text
    sim = r.json()
    assert len(sim["baseline"]) == 7
    assert len(sim["rain_scenario"]) == 7
    assert "projected_yield_loss_kg" in sim["impact"]
    assert sim["impact"]["rainfall_mm"] == 35.0

    # ---- 7. Recommendations + farmer response ------------------------
    r = client.post("/api/recommendations/generate", params={"pan_id": pan["id"]})
    assert r.status_code == 201, r.text
    recs = r.json()
    assert len(recs) >= 1
    rec_id = recs[0]["id"]

    r = client.post(f"/api/recommendations/{rec_id}/respond",
                    json={"status": "accepted", "farmer_notes": "Will do."})
    assert r.status_code == 200
    assert r.json()["status"] == "accepted"

    r = client.get(f"/api/recommendations?pan_id={pan['id']}")
    assert r.status_code == 200

    # ---- 8. Record + verify outcome ----------------------------------
    r = client.post("/api/outcomes", json={
        "pan_id": pan["id"],
        "prediction_id": prediction["id"],
        "recommendation_id": rec_id,
        "outcome_date": "2023-07-05",
        "actual_rainfall_mm": 42.0,
        "action_taken": "harvest",
        "harvest_date": "2023-07-06",
        "actual_yield_kg": 1800.0,
        "brine_density_be": 26.1,
        "salt_thickness_mm": 14.2,
        "notes": "Heavy rain then harvested.",
    })
    assert r.status_code == 201, r.text
    outcome = r.json()
    assert outcome["risk_occurred"] is True

    r = client.post(f"/api/outcomes/{outcome['id']}/verify")
    assert r.status_code == 200
    assert r.json()["verified"] is True

    # ---- 9. Compare predictions vs actuals ---------------------------
    r = client.get("/api/evaluation/comparison")
    assert r.status_code == 200
    rows = r.json()
    assert any(row["outcome_id"] == outcome["id"] for row in rows)

    r = client.get("/api/evaluation/summary")
    assert r.status_code == 200
    summary = r.json()
    assert summary["total_outcomes"] >= 1
    assert summary["verified_outcomes"] >= 1

    # ---- 10. Closed feedback loop --------------------------------------
    r = client.post("/api/evaluation/feedback")
    assert r.status_code == 200, r.text
    feedback = r.json()
    assert feedback["ingested"] is True
    assert outcome["id"] in feedback["outcome_ids"]
    assert feedback["training_rows_added"] >= 1
    assert feedback["feedback_dataset_id"] is not None

    # twin was updated by feedback
    r = client.get(f"/api/pans/{pan['id']}/twin")
    twin_after = r.json()
    assert twin_after["state"]["days_since_last_rain"] == 0


def test_what_if_rain_regression(client, sample_dataset_path):
    """Rain must always reduce readiness/brine and raise risk vs baseline."""
    with open(sample_dataset_path, "rb") as fh:
        client.post("/api/datasets/upload", files={"file": ("reg.csv", fh, "text/csv")})
    ds = client.get("/api/datasets").json()
    ds_id = max(d["id"] for d in ds)
    client.post("/api/models/train", json={"kind": "all", "dataset_id": ds_id})
    client.post("/api/pans", json={**_pan_payload(), "pan_id": "REG-1",
                                   "area_m2": 3000.0,
                                   "twin_state": {"brine_density_be": 26.0,
                                                  "salt_thickness_mm": 12.0,
                                                  "water_depth_cm": 9.0,
                                                  "days_since_last_rain": 4}})

    pans = client.get("/api/pans").json()
    pid = next(p["id"] for p in pans if p["pan_id"] == "REG-1")

    r = client.post("/api/simulations/what-if-rain",
                    json={"pan_id": pid, "horizon_days": 7,
                          "scenario": {"rainfall_mm": 80.0, "day_offset": 2, "dry_days_after": 2}})
    assert r.status_code == 200, r.text
    impact = r.json()["impact"]
    assert impact["projected_yield_loss_kg"] >= 0
    assert impact["readiness_drop_on_day"] >= 0.0
    assert impact["max_risk_after_rain"] >= impact["max_risk_baseline"] - 1e-9