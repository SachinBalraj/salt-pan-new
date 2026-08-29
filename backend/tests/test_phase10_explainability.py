"""Phase 10: Explainability.

Specification commitments under test:
- SHAP TreeExplainer drives local attributions for the tree models (Random
  Forest classifiers/regressors included).
- Every prediction run returns the top three factors per model kind.
- Factors are human-readable: bare technical feature names never appear as the
  headline explanation.
- Exact glossary conversions:
    forecast_rain_24h_mm          -> "High rainfall expected during the next 24 hours"
    predicted_salinity_after_rain -> "Rain is expected to dilute the brine"
- Recommendations bundle: recommended action, action deadline, three reasons,
  confidence, predicted consequence if the farmer waits, step-by-step
  instructions.
"""
import datetime as dt

import pytest

from app.ml.features import FEATURE_COLUMNS, risk_features_from_state
from app.services.digital_twin import default_twin_state
from app.services.explainability import (
    FEATURE_GLOSSARY,
    build_explanation,
    context_factors,
    explain_feature,
    shap_top_factors,
)
from app.services.predictor import local_shap_values

REQUIRED = {
    "forecast_rain_24h_mm": "High rainfall expected during the next 24 hours",
    "predicted_salinity_after_rain": "Rain is expected to dilute the brine",
}


def _rainy_forecast(day0_mm=30.0, days=7, total_mm=60.0):
    out = [{"rainfall_mm": day0_mm, "date": (dt.date(2026, 9, 1) + dt.timedelta(days=i)).isoformat()}
           for i in range(days)]
    return out


# ------------------------------------------------------------------ glossary
def test_required_glossary_conversions_exact():
    for name, text in REQUIRED.items():
        assert explain_feature(name) == text
        assert FEATURE_GLOSSARY[name] == text


def test_glossary_covers_all_model_features():
    for names in FEATURE_COLUMNS.values():
        for name in names:
            assert name in FEATURE_GLOSSARY, f"{name} has no human explanation"


def test_unknown_feature_falls_back_to_readable_label():
    assert explain_feature("obscure_field") == "Obscure field"


def test_shap_top_factors_are_human_readable_and_sorted():
    factors = shap_top_factors({"salt_thickness_mm": 0.4, "temperature_c": -0.2,
                                "water_depth_cm": 0.1, "humidity_pct": 0.02}, n=3)
    assert [f["feature"] for f in factors] == [
        "salt_thickness_mm", "temperature_c", "water_depth_cm"]
    assert factors[0]["contribution"] >= factors[1]["contribution"]
    for f in factors:
        assert f["explanation"] != f["feature"]
        assert f["weight_pct"] > 0
    total = sum(f["weight_pct"] for f in factors)
    assert 0.0 < total <= 100.0


def test_shap_top_factors_empty_when_no_values():
    assert shap_top_factors(None) == []
    assert shap_top_factors({}) == []


# ------------------------------------------------------------------ context
def test_context_uses_specced_rain_and_dilution_sentences():
    st = {**default_twin_state(), "water_depth_cm": 8.0, "brine_density_be": 24.0}
    factors = {f["feature"]: f for f in context_factors(st, _rainy_forecast())}
    assert factors["forecast_rain_24h_mm"]["explanation"] == REQUIRED["forecast_rain_24h_mm"]
    assert factors["predicted_salinity_after_rain"]["explanation"] == REQUIRED["predicted_salinity_after_rain"]
    assert factors["forecast_rain_24h_mm"]["value"] == 30.0
    assert factors["predicted_salinity_after_rain"]["value"] < 228.0


def test_context_stays_truthful_when_no_rain():
    st = {**default_twin_state(), "water_depth_cm": 8.0, "brine_density_be": 24.0}
    factors = {f["feature"]: f for f in context_factors(st, _rainy_forecast(day0_mm=0, total_mm=0))}
    assert factors["forecast_rain_24h_mm"]["explanation"] == "Little or no rain expected in the next 24 hours"


# ------------------------------------------------------------------ RF models
def test_shap_tree_explainer_works_for_random_forest(client, sample_dataset_path):
    with open(sample_dataset_path, "rb") as fh:
        client.post("/api/datasets/upload", files={"file": ("rf.csv", fh, "text/csv")})
    ds_id = max(d["id"] for d in client.get("/api/datasets").json())

    r = client.post("/api/models/train", json={"kind": "climate_risk_classifier",
                                               "dataset_id": ds_id})
    assert r.status_code == 201, r.text
    clf = next(m for m in r.json() if m["kind"] == "climate_risk_classifier")
    assert clf["algorithm"] == "RandomForestClassifier"
    assert clf["status"] in ("trained", "active")

    from app.ml.model_store import load_model
    from app.config import get_settings

    model = load_model("climate_risk_classifier",
                       get_settings().models_path, version=clf["version"])["model"]
    day = {"month": 6, "temperature_c": 31.0, "humidity_pct": 62.0,
           "wind_speed_kmh": 12.0, "sunshine_hours": 9.0}
    vector = risk_features_from_state(default_twin_state(), day, precip_7d_mm=25.0,
                                      precip_prob_pct=60.0)

    shap = local_shap_values(model, vector, clf["feature_names"])
    assert shap, "TreeExplainer returned no attribution for the Random Forest"

    factors = shap_top_factors(shap, n=3)
    assert len(factors) == 3
    assert all(f["explanation"] != f["feature"] for f in factors)


# ------------------------------------------------------------------ end-to-end prediction + recommendations
def test_prediction_run_explain_bundle(client, sample_dataset_path):
    with open(sample_dataset_path, "rb") as fh:
        client.post("/api/datasets/upload", files={"file": ("xp.csv", fh, "text/csv")})
    ds_id = max(d["id"] for d in client.get("/api/datasets").json())
    for kind in ("harvest_readiness", "climate_risk"):
        r = client.post("/api/models/train", json={"kind": kind, "dataset_id": ds_id})
        assert r.status_code == 201, r.text

    r = client.post("/api/pans", json={
        "pan_id": "XP-1", "name": "Explainability Pan", "location": "L",
        "area_m2": 2000.0,
        "twin_state": {"brine_density_be": 25.0, "salt_thickness_mm": 12.0,
                       "water_depth_cm": 9.0, "days_since_last_rain": 3},
    })
    pid = r.json()["id"]

    r = client.post("/api/predictions/run",
                    json={"pan_id": pid, "horizon_days": 7, "scenario": "actual_forecast"})
    assert r.status_code == 200, r.text
    pred = r.json()
    explain = pred["explain"]
    assert explain["method"] == "shap.TreeExplainer"
    assert len(explain["harvest_readiness"]["factors"]) == 3
    assert len(explain["climate_risk"]["factors"]) == 3
    for kind in ("harvest_readiness", "climate_risk"):
        for f in explain[kind]["factors"]:
            assert f["explanation"] != f["feature"]
            assert f["explanation"] and f["feature"]
    context = {c["feature"]: c for c in explain["context"]}
    assert "forecast_rain_24h_mm" in context
    assert context["forecast_rain_24h_mm"]["explanation"] == REQUIRED["forecast_rain_24h_mm"] \
        or context["forecast_rain_24h_mm"]["explanation"].startswith("Little")
    assert "predicted_salinity_after_rain" in context


def test_build_explanation_injects_specced_sentences():
    st = {**default_twin_state(), "water_depth_cm": 8.0, "brine_density_be": 24.0}
    explain = build_explanation(st, _rainy_forecast(), {}, {
        "harvest_readiness": {"salt_thickness_mm": 0.5, "temperature_c": 0.2, "brine_density_be": 0.1},
        "climate_risk": {"precipitation_7d_forecast_mm": 0.6, "humidity_pct": 0.3, "wind_speed_kmh": 0.1},
    })
    assert explain["method"] == "shap.TreeExplainer"
    assert [f["feature"] for f in explain["harvest_readiness"]["factors"]] == [
        "salt_thickness_mm", "temperature_c", "brine_density_be"]
    assert explain["harvest_readiness"]["factors"][0]["explanation"] == "The salt bed is thick"
    texts = {c["feature"]: c["explanation"] for c in explain["context"]}
    assert texts["forecast_rain_24h_mm"] == REQUIRED["forecast_rain_24h_mm"]
    assert texts["predicted_salinity_after_rain"] == REQUIRED["predicted_salinity_after_rain"]


def test_recommendations_carry_the_six_part_contract(client, sample_dataset_path):
    with open(sample_dataset_path, "rb") as fh:
        client.post("/api/datasets/upload", files={"file": ("rec.csv", fh, "text/csv")})
    ds_id = max(d["id"] for d in client.get("/api/datasets").json())
    for kind in ("harvest_readiness", "climate_risk"):
        client.post("/api/models/train", json={"kind": kind, "dataset_id": ds_id})

    r = client.post("/api/pans", json={
        "pan_id": "REC-X", "name": "Rec Pan", "location": "L", "area_m2": 2000.0,
        "twin_state": {"brine_density_be": 25.0, "salt_thickness_mm": 12.0,
                       "water_depth_cm": 9.0, "days_since_last_rain": 3},
    })
    pid = r.json()["id"]

    r = client.post("/api/recommendations/generate", params={"pan_id": pid})
    assert r.status_code == 201, r.text
    recs = r.json()
    assert recs, "expected at least one recommendation"
    for rec in recs:
        assert rec["recommendation_type"]
        assert rec["title"]
        assert rec["action_deadline"], f"{rec['recommendation_type']} missing action deadline"
        assert len(rec["reasons"]) == 3
        assert rec["confidence_pct"] > 0
        assert rec["consequence_if_waited"], f"{rec['recommendation_type']} missing consequence"
        assert rec["consequence_if_waited"] != rec["message"]
        assert len(rec["instructions"]) == 3
        assert all(rec["instructions"])  # step-by-step, non-empty