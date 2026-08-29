"""Phase 7: Digital twin for every salt pan + real-time sensor ingestion."""
from app.models import ModelVersion, Recommendation, SensorReading


def _pan_payload(code: str, name: str = "Phase7 Test Pan"):
    return {
        "pan_id": code,
        "name": name,
        "location": "Testville",
        "area_m2": 2000.0,
        "latitude": 12.0,
        "longitude": 75.0,
    }


def _make_pan(client, code: str):
    r = client.post("/api/pans", json=_pan_payload(code))
    assert r.status_code == 201, r.text
    assert r.json()["pan_id"] == code
    return r.json()


def _reading(**overrides):
    body = {
        "pan_code": "PH7-A",
        "salinity_g_l": 190.0,
        "ec_ms_cm": 160.0,
        "water_depth_cm": 4.2,
        "brine_temperature_c": 29.5,
        "air_temperature_c": 31.0,
        "humidity_pct": 62.0,
        "sensor_quality": 96.0,
    }
    body.update(overrides)
    return body


def _deactivate_all(db):
    restored = [mv.id for mv in db.query(ModelVersion).all() if mv.active]
    db.query(ModelVersion).update({ModelVersion.active: False})
    db.commit()
    return restored


def _restore_active(db, restored):
    db.query(ModelVersion).update({ModelVersion.active: False})
    for mid in restored:
        mv = db.get(ModelVersion, mid)
        if mv:
            mv.active = True
    db.commit()


# ---------------------------------------------------------------- ingestion
def test_sensor_reading_saves_and_updates_twin(client, db):
    pan = _make_pan(client, "PH7-A")
    body = _reading(recorded_at="2026-08-29T10:00:00Z")

    r = client.post("/api/sensors/readings", json=body)
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["pan_id"] == pan["id"]
    assert out["pan_ref"] == "PH7-A"
    assert out["status"] == "ok"

    twin = out["digital_twin"]
    assert twin["pan_ref"] == "PH7-A"
    assert twin["salinity_g_l"] == 190.0
    assert twin["water_depth_cm"] == 4.2
    assert twin["brine_temperature_c"] == 29.5
    assert twin["brine_volume_m3"] == round(4.2 / 100.0 * 2000.0, 2)
    assert twin["estimated_salt_mass_kg"] == 9600.0  # 4mm bed on 2000 m2
    assert twin["forecast_rainfall_mm"] >= 0.0
    assert twin["predicted_depth_after_rain_cm"] >= 4.2
    assert 0.0 <= twin["harvest_readiness"] <= 1.0
    assert 0.0 <= twin["climate_risk"] <= 1.0
    assert "plateau" not in twin.get("last_update", "")  # sanity no-op

    # recorded_at honoured on the persisted row
    row = db.get(SensorReading, out["reading_id"])
    assert row is not None
    assert row.pan_id == pan["id"]
    assert row.salinity_g_l == 190.0
    assert str(row.timestamp) == "2026-08-29 10:00:00"


def test_sensor_reading_routes_by_pan_code(client):
    pan = _make_pan(client, "PH7-B")
    body = _reading(pan_code="PH7-B", pan_id=None)
    r = client.post("/api/sensors/readings", json=body)
    assert r.status_code == 201, r.text
    assert r.json()["pan_id"] == pan["id"]


def test_invalid_readings_rejected(client):
    pan = _make_pan(client, "PH7-C")
    pan_id = pan["id"]

    # missing required depth
    body = _reading(pan_id=pan_id, pan_code=None)
    body.pop("water_depth_cm")
    assert client.post("/api/sensors/readings", json=body).status_code == 422

    # salinity outside the physical band
    body = _reading(pan_id=pan_id, pan_code=None, salinity_g_l=900.0)
    assert client.post("/api/sensors/readings", json=body).status_code == 422

    # brine temperature out of range
    body = _reading(pan_id=pan_id, pan_code=None, brine_temperature_c=100.0)
    assert client.post("/api/sensors/readings", json=body).status_code == 422

    # no pan reference at all
    body = _reading(pan_id=None, pan_code=None)
    assert client.post("/api/sensors/readings", json=body).status_code == 422


def test_reading_for_unknown_pan_404(client):
    body = _reading(pan_id=999999, pan_code=None)
    assert client.post("/api/sensors/readings", json=body).status_code == 404
    body = _reading(pan_id=None, pan_code="NOPE-99")
    assert client.post("/api/sensors/readings", json=body).status_code == 404


# ---------------------------------------------------------------- twin view
def test_digital_twin_endpoint_exposes_all_required_fields(client):
    pan = _make_pan(client, "PH7-D")
    r = client.get(f"/api/pans/{pan['id']}/digital-twin")
    assert r.status_code == 200, r.text
    twin = r.json()
    for field in (
        "salinity_g_l", "water_depth_cm", "brine_temperature_c", "brine_volume_m3",
        "estimated_salt_mass_kg", "forecast_rainfall_mm", "rain_probability_pct",
        "predicted_depth_after_rain_cm", "predicted_salinity_after_rain_g_l",
        "evaporation_mm_day", "harvest_readiness", "climate_risk",
        "last_operation", "last_update",
    ):
        assert field in twin, field
    assert twin["pan_id"] == pan["id"]
    assert twin["pan_ref"] == "PH7-D"


def test_digital_twin_404_for_missing_pan(client):
    assert client.get("/api/pans/999999/digital-twin").status_code == 404


# ------------------------------------------------- model gate on ingestion
def test_sensor_ingest_skips_prediction_without_active_model(client, db):
    pan = _make_pan(client, "PH7-E")
    restored = _deactivate_all(db)
    try:
        body = _reading(pan_id=pan["id"], pan_code=None, water_depth_cm=8.5)
        r = client.post("/api/sensors/readings", json=body)
        assert r.status_code == 201, r.text
        out = r.json()
        assert out["active_model"] is False
        assert out["prediction"] is None
        assert out["recommendations"] == []
        # sensors still drive the twin
        assert out["digital_twin"]["water_depth_cm"] == 8.5
    finally:
        _restore_active(db, restored)


def test_sensor_ingest_runs_prediction_and_refreshes_recommendations(
        client, db, sample_dataset_path):
    pan = _make_pan(client, "PH7-F")
    restored = _deactivate_all(db)

    # self-contained: upload a dataset, train the five kinds, activate one.
    with open(sample_dataset_path, "rb") as fh:
        r = client.post("/api/datasets/upload",
                        files={"file": ("phase7.csv", fh, "text/csv")})
    assert r.status_code == 201, r.text
    ds_id = r.json()["id"]
    r = client.post("/api/models/train", json={"kind": "all", "dataset_id": ds_id})
    assert r.status_code == 201, r.text
    latest = client.get("/api/models/latest").json()
    ready = next(m for m in latest if m["kind"] == "harvest_readiness")
    r = client.post(f"/api/models/{ready['id']}/activate")
    assert r.status_code == 200, r.text

    try:
        body = _reading(pan_id=pan["id"], pan_code=None,
                        salinity_g_l=240.0, water_depth_cm=6.0)
        r1 = client.post("/api/sensors/readings", json=body)
        assert r1.status_code == 201, r1.text
        out1 = r1.json()
        assert out1["active_model"] is True
        assert out1["prediction"] is not None
        assert len(out1["prediction"]["series"]) == 7
        assert 0.0 <= out1["prediction"]["day0"]["readiness"] <= 1.0
        assert len(out1["recommendations"]) >= 1
        assert all(rec["status"] == "pending" for rec in out1["recommendations"])

        # a fresh reading retrains no model but re-runs the pipeline and
        # replaces the stale pending advice with a new set.
        body = _reading(pan_id=pan["id"], pan_code=None,
                        salinity_g_l=200.0, water_depth_cm=7.5)
        r2 = client.post("/api/sensors/readings", json=body)
        assert r2.status_code == 201, r2.text
        out2 = r2.json()
        assert out2["prediction"]["id"] != out1["prediction"]["id"]
        assert out2["digital_twin"]["water_depth_cm"] == 7.5
        assert len(out2["recommendations"]) >= 1

        pending = (db.query(Recommendation)
                   .filter(Recommendation.pan_id == pan["id"],
                           Recommendation.status == "pending").count())
        expired = (db.query(Recommendation)
                   .filter(Recommendation.pan_id == pan["id"],
                           Recommendation.status == "expired").count())
        assert pending == len(out2["recommendations"])
        assert expired == len(out1["recommendations"])
        readings = db.query(SensorReading).filter(SensorReading.pan_id == pan["id"]).count()
        assert readings == 2
    finally:
        _restore_active(db, restored)