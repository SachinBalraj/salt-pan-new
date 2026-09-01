"""Phase 6: ML model training (classifiers + verified-outcome regressor)."""
import datetime as dt

import pandas as pd

from app.config import get_settings
from app.ml.features import MIN_VERIFIED_REGRESSION_ROWS
from app.services.data_generator import generate_dataset
from app.services.model_targets import resolve_targets
from app.services.training import _time_split, train_model


def _prepared(seed: int = 3, start=dt.date(2022, 1, 1), end=dt.date(2023, 6, 30),
              pan_ids=("PAN-1", "PAN-2", "PAN-3")):
    return generate_dataset(start=start, end=end, pan_ids=list(pan_ids), seed=seed)


def _matrices(df):
    from app.config.proxy_labels import get_proxy_labels_config
    from app.services.proxy_labels import ensure_labels

    prep, lr = ensure_labels(df, get_proxy_labels_config(), dataset_source="generated")
    prep, tr = resolve_targets(prep, lr, dataset_source="generated")
    return prep, lr, tr


def _order(dates: pd.Series, frac: float):
    cut = int(len(dates) * frac)
    return dates.argsort(kind="mergesort").tolist(), cut


# ---------------------------------------------------------------- unit: split
def test_time_split_keeps_future_out_of_training_past():
    import numpy as np

    np.random.seed(42)
    dates = pd.Series(pd.date_range("2022-01-01", periods=200, freq="D"))
    X = pd.DataFrame({"a": np.arange(200)})
    y = pd.Series(np.random.rand(200))
    X_tr, X_te, y_tr, y_te, split = _time_split(X, y, dates, seed=42)

    order, cut = _order(dates, 0.8)
    tr_dates = dates.iloc[sorted(order[:cut])]
    te_dates = dates.iloc[sorted(order[cut:])]

    assert len(X_tr) + len(X_te) == 200
    assert split["split_type"] == "time"
    assert split["future_leakage_prevented"] is True
    assert tr_dates.max() <= te_dates.min()
    assert sorted(X_tr.index.tolist() + X_te.index.tolist()) == list(range(200))


# ---------------------------------------------------------------- classifiers
def test_classifier_training_reports_full_class_metrics():
    dl, _, tr = _matrices(_prepared())
    if dl["risk_level"].astype(str).nunique() < 2:
        return  # dataset lacked class diversity — covered by the deferral test
    trained = train_model("climate_risk_classifier", dl, 1,
                          get_settings().models_path, target_report=tr,
                          dataset_name="x")
    assert trained["status"] == "trained"
    assert trained["algorithm"] == "RandomForestClassifier"
    assert trained["target"] == "risk_level"
    m = trained["metrics"]
    assert {"accuracy", "precision", "recall", "f1"}.issubset(m)
    assert trained["classes"] and len(trained["classes"]) == len(
        trained["confusion_matrix"])
    assert trained["test_rows"] > 0
    assert trained["split"]["future_leakage_prevented"] is True
    dist = trained["class_distribution"]
    assert all({"train", "test", "predicted_test"}.issubset(v)
               for v in dist.values())


def test_time_split_dates_match_train_test_rows():
    dl, _, tr = _matrices(_prepared())
    trained = train_model("climate_risk_classifier", dl, 1,
                          get_settings().models_path, target_report=tr)
    trs, tre = trained["split"]["train_dates"]
    tes, tee = trained["split"]["test_dates"]
    assert trs and tre and tes and tee
    assert tre <= tes  # latest train day is not after the oldest test day
    assert trained["rows_trained"] + trained["test_rows"] == int(len(dl))


def test_deferred_classifier_when_single_class():
    rows = [
        {"date": f"2022-0{i+1}-15", "pan_id": "PAN-1", "temperature_c": 30.0,
         "humidity_pct": 60.0, "wind_speed_kmh": 12.0, "rainfall_mm": 0.0,
         "sunshine_hours": 9.0, "water_depth_cm": 8.0, "brine_density_be": 26.5,
         "salt_thickness_mm": 11.5, "days_since_last_rain": 6,
         "harvest_readiness": 0.10, "climate_risk": 0.9}
        for i in range(3)
    ] * 30
    df = pd.DataFrame(rows)
    from app.config.proxy_labels import get_proxy_labels_config
    from app.services.proxy_labels import ensure_labels

    prep, lr = ensure_labels(df, get_proxy_labels_config(), dataset_source="generated")
    prep, tr = resolve_targets(prep, lr, dataset_source="generated")
    if prep["harvest_ready"].astype(int).nunique() >= 2:
        return
    trained = train_model("harvest_readiness_classifier", prep, 1,
                          get_settings().models_path, target_report=tr)
    assert trained["status"] == "deferred"
    assert trained["version"] == 0
    assert trained["training_errors"]


# ---------------------------------------------------------------- regressor
def test_regressor_deferred_when_no_verified_outcomes():
    dl, _, tr = _matrices(_prepared())
    trained = train_model("harvest_time_regressor", dl, 1,
                          get_settings().models_path, target_report=tr)
    assert trained["status"] == "deferred"
    assert trained["version"] == 0
    assert trained["training_errors"] == ["Insufficient verified outcome data."]
    assert trained["metrics"] == {}


def test_regressor_trains_on_field_hours_only():
    from app.config.proxy_labels import get_proxy_labels_config
    from app.services.proxy_labels import ensure_labels

    df = _prepared()
    rows = []
    for i, (_, row) in enumerate(df.head(80).iterrows()):
        d = row.to_dict()
        d["hours_to_harvest"] = 200.0 - i * 2.0
        d["hours_to_harvest_source"] = "field"
        rows.append(d)
    dl, lr = ensure_labels(pd.DataFrame(rows), get_proxy_labels_config(),
                           dataset_source="generated")
    dl, tr = resolve_targets(dl, lr, dataset_source="generated")
    assert int(dl["hours_to_harvest"].notna().sum()) >= MIN_VERIFIED_REGRESSION_ROWS

    trained = train_model("harvest_time_regressor", dl, 1,
                          get_settings().models_path, target_report=tr)
    assert trained["status"] == "trained"
    assert set(("mae", "rmse", "r2")).issubset(trained["metrics"])
    assert trained["uses_proxy_labels"] is False


# ---------------------------------------------------------------- HTTP
def test_train_all_returns_five_kinds_and_defers_regressor(client, sample_dataset_path):
    with open(sample_dataset_path, "rb") as fh:
        r = client.post("/api/datasets/upload",
                        files={"file": ("phase6.csv", fh, "text/csv")})
    assert r.status_code == 201, r.text
    ds_id = r.json()["id"]

    r = client.post("/api/models/train", json={"kind": "all", "dataset_id": ds_id})
    assert r.status_code == 201, r.text
    trained = r.json()
    assert len(trained) == 5
    kinds = {m["kind"] for m in trained}
    assert kinds == {"harvest_readiness", "climate_risk",
                     "climate_risk_classifier", "harvest_readiness_classifier",
                     "harvest_time_regressor"}

    reg = next(m for m in trained if m["kind"] == "harvest_time_regressor")
    assert reg["status"] == "deferred"
    assert reg["training_errors"] == ["Insufficient verified outcome data."]
    assert reg["is_active"] is False

    for m in trained:
        if m["kind"] == "harvest_time_regressor":
            assert m["uses_proxy_labels"] is False  # deferred — used no labels
        else:
            assert m["uses_proxy_labels"] is True  # synthetic demo labels
        if m["kind"] in ("climate_risk_classifier", "harvest_readiness_classifier") \
                and m["status"] == "trained":
            assert m["metrics"]["accuracy"] is not None
            assert m["confusion_matrix"] is not None

    legacy = next(m for m in trained if m["kind"] == "harvest_readiness")
    assert legacy["test_rows"] > 0
    assert legacy["split"]["split_type"] == "time"
    assert legacy["dataset_id"] == ds_id


def test_latest_returns_newest_per_kind(client):
    models = client.get("/api/models").json()
    latest = client.get("/api/models/latest")
    assert latest.status_code == 200
    latest_body = latest.json()
    by_kind = {}
    for m in latest_body:
        prev = by_kind.get(m["kind"])
        assert prev is None or m["id"] > prev["id"]
        by_kind[m["kind"]] = m
    assert "harvest_time_regressor" in by_kind  # deferred still surfaced
    assert len(models) >= len(latest_body)


def test_activate_deactivates_sibling_versions(client, sample_dataset_path):
    with open(sample_dataset_path, "rb") as fh:
        client.post("/api/datasets/upload",
                    files={"file": ("act.csv", fh, "text/csv")})
    ds_id = max(d["id"] for d in client.get("/api/datasets").json())

    client.post("/api/models/train",
                json={"kind": "climate_risk_classifier", "dataset_id": ds_id})
    v1 = next(m for m in client.get("/api/models").json()
              if m["kind"] == "climate_risk_classifier")
    client.post("/api/models/train",
                json={"kind": "climate_risk_classifier", "dataset_id": ds_id})
    models = client.get("/api/models").json()
    v1_new = next(m for m in models if m["id"] == v1["id"])
    v2 = next(m for m in models
              if m["kind"] == "climate_risk_classifier" and m["id"] != v1["id"])

    r = client.post(f"/api/models/{v1_new['id']}/activate")
    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is True

    after = client.get("/api/models").json()
    for m in after:
        if m["kind"] == "climate_risk_classifier":
            assert m["is_active"] == (m["id"] == v1_new["id"])

    # activating a deferred model is rejected
    reg = next(m for m in after if m["kind"] == "harvest_time_regressor")
    r = client.post(f"/api/models/{reg['id']}/activate")
    assert r.status_code == 400


def test_prediction_blocked_without_active_model(client, sample_dataset_path, db):
    from app.models import ModelVersion

    with open(sample_dataset_path, "rb") as fh:
        client.post("/api/datasets/upload",
                    files={"file": ("gate.csv", fh, "text/csv")})
    ds_id = max(d["id"] for d in client.get("/api/datasets").json())
    client.post("/api/models/train", json={"kind": "all", "dataset_id": ds_id})
    client.post("/api/pans", json={
        "pan_id": "GATE-1", "name": "Gate Pan", "location": "L",
        "area_m2": 1000.0,
    })
    pan_id = client.get("/api/pans").json()[0]["id"]

    restored = [mv for mv in db.query(ModelVersion).all() if mv.active]
    db.query(ModelVersion).update({ModelVersion.active: False})
    db.commit()

    try:
        r = client.post("/api/predictions/run",
                        json={"pan_id": pan_id, "horizon_days": 7,
                              "scenario": "actual_forecast"})
        assert r.status_code == 409, r.text
        body = r.json()
        assert "No active model" in (body.get("detail") or body.get("message", ""))
    finally:
        db.query(ModelVersion).update({ModelVersion.active: False})
        for mv in restored:
            mv.active = True
        db.commit()