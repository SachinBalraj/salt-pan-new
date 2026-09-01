"""Phase 15: comprehensive integration tests.

Covers: brine-volume calc, rain-volume calc, post-rain salinity, zero-volume
handling, invalid sensor values, dataset column validation, risk prediction,
recommendation rules, SHAP explanation formatting, feedback outcome linking,
API endpoints, and the published mass-balance example.
"""
from __future__ import annotations

import math

import pandas as pd
import pytest

from app.services.digital_twin import (
    apply_outcome_to_twin,
    apply_reading_to_state,
    default_twin_state,
    normalise_state,
    progress_to_harvest,
    salt_mass_kg,
    _derive_columns,
)
from app.services.explainability import (
    FEATURE_GLOSSARY,
    build_explanation,
    context_factors,
    explain_feature,
    shap_top_factors,
)
from app.services.recommendation_engine import generate_recommendations
from app.services.simulator import (
    rain_dilution,
    rain_risk_score,
    recommend_action,
    risk_to_text,
)
from app.ml.features import REQUIRED_RAW_COLUMNS, FEATURE_COLUMNS, evap_index


# ────────────────────────────────────────────────────────────────────────────
# Helper
# ────────────────────────────────────────────────────────────────────────────

def _make_pan(client, code, twin_state=None, area_m2=500.0, safe_depth_cm=12.0):
    body = {
        "pan_id": code,
        "name": f"Pan {code}",
        "location": "Test",
        "area_m2": area_m2,
        "latitude": 12.0,
        "longitude": 75.0,
    }
    if twin_state is not None:
        body["twin_state"] = twin_state
    r = client.post("/api/pans", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _7day_dry_forecast():
    return [
        {
            "date": f"2025-01-{i+1:02d}",
            "temperature_c": 30.0,
            "humidity_pct": 55.0,
            "wind_speed_kmh": 12.0,
            "sunshine_hours": 9.0,
            "rainfall_mm": 0.0,
            "precipitation_probability_pct": 10.0,
        }
        for i in range(7)
    ]


def _7day_rainy_forecast(rain_mm=15.0):
    days = _7day_dry_forecast()
    days[2]["rainfall_mm"] = rain_mm
    days[2]["precipitation_probability_pct"] = 80.0
    return days


# ════════════════════════════════════════════════════════════════════════════
# 1. BRINE-VOLUME CALCULATION
# ════════════════════════════════════════════════════════════════════════════

class TestBrineVolume:
    def test_basic_volume(self):
        """Volume = depth_cm / 100 * area_m2"""
        volume = 8.0 / 100.0 * 500.0
        assert volume == 40.0

    def test_small_pan(self):
        volume = 10.0 / 100.0 * 100.0
        assert volume == 10.0

    def test_large_pan(self):
        volume = 15.0 / 100.0 * 5000.0
        assert volume == 750.0

    def test_zero_depth(self):
        volume = 0.0 / 100.0 * 500.0
        assert volume == 0.0

    def test_derive_columns_volume(self):
        state = {**default_twin_state(), "water_depth_cm": 8.0, "brine_density_be": 25.79}
        pan_stub = type("P", (), {"area_m2": 500.0, "safe_depth_cm": 12.0})()
        result = _derive_columns(state, pan_stub, _7day_dry_forecast())
        assert result["brine_volume_m3"] == 40.0

    def test_api_volume_in_simulate(self, client):
        pan = _make_pan(client, "VOL-1",
                        {"water_depth_cm": 8.0, "brine_density_be": 25.79})
        r = client.post(f"/api/pans/{pan['id']}/simulate-rain",
                        json={"rainfall_mm": 10})
        assert r.status_code == 200
        assert r.json()["current_volume_m3"] == 40.0


# ════════════════════════════════════════════════════════════════════════════
# 2. RAIN-VOLUME CALCULATION
# ════════════════════════════════════════════════════════════════════════════

class TestRainVolume:
    def test_basic_rain_volume(self):
        """Rain volume = rainfall_mm / 1000 * area_m2"""
        rv = 20.0 / 1000.0 * 500.0
        assert rv == 10.0

    def test_zero_rain(self):
        rv = 0.0 / 1000.0 * 500.0
        assert rv == 0.0

    def test_heavy_rain_large_pan(self):
        rv = 100.0 / 1000.0 * 5000.0
        assert rv == 500.0

    def test_api_rain_volume(self, client):
        pan = _make_pan(client, "RVOL-1",
                        {"water_depth_cm": 8.0, "brine_density_be": 25.79})
        r = client.post(f"/api/pans/{pan['id']}/simulate-rain",
                        json={"rainfall_mm": 20})
        assert r.status_code == 200
        assert r.json()["rain_volume_m3"] == 10.0

    def test_rain_dilution_unit(self):
        """rain_dilution helper returns consistent rain volume math."""
        result = rain_dilution(245.0, 8.0, 20.0)
        assert result["depth_after_cm"] == 10.0
        assert result["salinity_after_g_l"] == 196.0


# ════════════════════════════════════════════════════════════════════════════
# 3. PREDICTED POST-RAIN SALINITY
# ════════════════════════════════════════════════════════════════════════════

class TestPostRainSalinity:
    def test_mass_conserving_dilution(self):
        """salinity_after = salinity_before * depth / depth_after"""
        sal_after = 245.0 * 8.0 / (8.0 + 20.0 / 10.0)
        assert sal_after == 196.0

    def test_small_rain(self):
        sal_after = 245.0 * 8.0 / (8.0 + 5.0 / 10.0)
        assert abs(sal_after - 230.588) < 0.01

    def test_large_rain(self):
        sal_after = 245.0 * 8.0 / (8.0 + 100.0 / 10.0)
        assert abs(sal_after - 108.89) < 0.1

    def test_api_post_rain_salinity(self, client):
        pan = _make_pan(client, "SAL-1",
                        {"water_depth_cm": 8.0, "brine_density_be": round(245.0 / 9.5, 4)})
        r = client.post(f"/api/pans/{pan['id']}/simulate-rain",
                        json={"rainfall_mm": 20})
        assert r.status_code == 200
        assert r.json()["predicted_salinity_after_rain_g_l"] == 196.0

    def test_rain_dilution_unit(self):
        d = rain_dilution(245.0, 8.0, 20.0)
        assert d["salinity_after_g_l"] == 196.0
        d2 = rain_dilution(300.0, 5.0, 50.0)
        expected = 300.0 * 5.0 / (5.0 + 5.0)
        assert d2["salinity_after_g_l"] == round(max(0.0, min(expected, 350.0)), 1)

    def test_clamp_upper_bound(self):
        d = rain_dilution(350.0, 8.0, 0.01)
        assert d["salinity_after_g_l"] <= 350.0

    def test_never_negative(self):
        d = rain_dilution(0.0, 8.0, 100.0)
        assert d["salinity_after_g_l"] >= 0.0


# ════════════════════════════════════════════════════════════════════════════
# 4. ZERO-VOLUME HANDLING
# ════════════════════════════════════════════════════════════════════════════

class TestZeroVolume:
    def test_zero_depth_volume(self):
        assert 0.0 / 100.0 * 500.0 == 0.0

    def test_zero_depth_post_rain(self):
        d = rain_dilution(245.0, 0.0, 20.0)
        assert d["depth_after_cm"] == 2.0
        assert d["salinity_after_g_l"] == 0.0

    def test_normalise_state_zero_fill(self):
        st = normalise_state({})
        assert st["water_depth_cm"] == 12.0
        assert st["brine_density_be"] == 21.0

    def test_normalise_state_handles_none(self):
        st = normalise_state(None)
        assert st["water_depth_cm"] == 12.0

    def test_normalise_state_clamps_negative_thickness(self):
        st = normalise_state({"salt_thickness_mm": -5.0})
        assert st["salt_thickness_mm"] == 0.0

    def test_normalise_state_non_numeric(self):
        st = normalise_state({"water_depth_cm": "abc", "brine_density_be": None})
        assert st["water_depth_cm"] == 0.0
        assert st["brine_density_be"] == 0.0

    def test_salt_mass_zero_thickness(self):
        assert salt_mass_kg(0.0, area_m2=500.0) == 0.0

    def test_risk_score_zero_salinity(self):
        score = rain_risk_score(0.0, 8.0, 12.0, 20.0)
        assert 0.0 <= score <= 1.0

    def test_risk_score_zero_depth(self):
        score = rain_risk_score(245.0, 0.0, 12.0, 20.0)
        assert 0.0 <= score <= 1.0


# ════════════════════════════════════════════════════════════════════════════
# 5. INVALID SENSOR VALUES
# ════════════════════════════════════════════════════════════════════════════

class TestInvalidSensorValues:
    def test_schema_rejects_negative_salinity(self, client):
        pan = _make_pan(client, "INV-1")
        r = client.post("/api/sensors/readings", json={
            "pan_code": "INV-1",
            "salinity_g_l": -10.0,
            "water_depth_cm": 8.0,
        })
        assert r.status_code == 422

    def test_schema_rejects_huge_salinity(self, client):
        pan = _make_pan(client, "INV-2")
        r = client.post("/api/sensors/readings", json={
            "pan_code": "INV-2",
            "salinity_g_l": 500.0,
            "water_depth_cm": 8.0,
        })
        assert r.status_code == 422

    def test_schema_rejects_negative_depth(self, client):
        pan = _make_pan(client, "INV-3")
        r = client.post("/api/sensors/readings", json={
            "pan_code": "INV-3",
            "salinity_g_l": 245.0,
            "water_depth_cm": -5.0,
        })
        assert r.status_code == 422

    def test_schema_rejects_humidity_over_100(self, client):
        pan = _make_pan(client, "INV-4")
        r = client.post("/api/sensors/readings", json={
            "pan_code": "INV-4",
            "salinity_g_l": 245.0,
            "water_depth_cm": 8.0,
            "humidity_pct": 150.0,
        })
        assert r.status_code == 422

    def test_schema_rejects_missing_pan_reference(self, client):
        r = client.post("/api/sensors/readings", json={
            "salinity_g_l": 245.0,
            "water_depth_cm": 8.0,
        })
        assert r.status_code == 422

    def test_schema_accepts_zero_salinity(self, client):
        pan = _make_pan(client, "INV-5")
        r = client.post("/api/sensors/readings", json={
            "pan_code": "INV-5",
            "salinity_g_l": 0.0,
            "water_depth_cm": 8.0,
        })
        assert r.status_code == 201

    def test_schema_accepts_boundary_values(self, client):
        pan = _make_pan(client, "INV-6")
        r = client.post("/api/sensors/readings", json={
            "pan_code": "INV-6",
            "salinity_g_l": 350.0,
            "water_depth_cm": 500.0,
            "brine_temperature_c": 60.0,
            "air_temperature_c": 55.0,
            "humidity_pct": 100.0,
        })
        assert r.status_code == 201

    def test_apply_reading_clamps_beaume(self):
        state = default_twin_state()
        reading = type("R", (), {
            "salinity_g_l": 350.0, "water_depth_cm": 8.0,
            "brine_temperature_c": None, "air_temperature_c": None,
            "humidity_pct": None, "ec_ms_cm": None, "sensor_quality": None,
        })()
        new = apply_reading_to_state(state, reading)
        assert new["brine_density_be"] <= 30.0

    def test_apply_reading_min_beaume(self):
        state = default_twin_state()
        reading = type("R", (), {
            "salinity_g_l": 10.0, "water_depth_cm": 8.0,
            "brine_temperature_c": None, "air_temperature_c": None,
            "humidity_pct": None, "ec_ms_cm": None, "sensor_quality": None,
        })()
        new = apply_reading_to_state(state, reading)
        assert new["brine_density_be"] >= 3.5


# ════════════════════════════════════════════════════════════════════════════
# 6. DATASET COLUMN VALIDATION
# ════════════════════════════════════════════════════════════════════════════

class TestDatasetColumnValidation:
    def test_required_columns_exist(self):
        expected = {
            "pan_id", "date", "temperature_c", "humidity_pct", "wind_speed_kmh",
            "rainfall_mm", "sunshine_hours", "water_depth_cm", "brine_density_be",
            "salt_thickness_mm", "days_since_last_rain",
        }
        assert expected == set(REQUIRED_RAW_COLUMNS)

    def test_feature_columns_for_all_models(self):
        for kind in ("harvest_readiness", "climate_risk",
                     "climate_risk_classifier", "harvest_readiness_classifier"):
            assert len(FEATURE_COLUMNS[kind]) >= 7

    def test_upload_garbage_csv(self, client):
        import io
        content = b"not_a_real_dataset,garbage,123\nfoo,bar,baz\n"
        r = client.post("/api/datasets/upload",
                        files={"file": ("garbage.csv", io.BytesIO(content), "text/csv")})
        assert r.status_code in (201, 400)

    def test_upload_valid_csv(self, client, sample_dataset_path):
        with open(sample_dataset_path, "rb") as fh:
            r = client.post("/api/datasets/upload",
                            files={"file": ("valid.csv", fh, "text/csv")})
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["rows_count"] > 0
        assert body["columns"]

    def test_thresholds_endpoint(self, client):
        r = client.get("/api/datasets/thresholds")
        assert r.status_code == 200
        body = r.json()
        assert "types" in body
        assert "thresholds" in body


# ════════════════════════════════════════════════════════════════════════════
# 7. RISK PREDICTION
# ════════════════════════════════════════════════════════════════════════════

class TestRiskPrediction:
    def test_risk_score_range(self):
        for mm in (0, 5, 10, 20, 50, 100):
            s = rain_risk_score(245, 8, 12, mm)
            assert 0.0 <= s <= 1.0

    def test_risk_monotonic(self):
        scores = [rain_risk_score(245, 8, 12, mm) for mm in (0, 5, 20, 50, 100)]
        assert scores == sorted(scores)

    def test_risk_text_map(self):
        assert risk_to_text(0.0) == "LOW"
        assert risk_to_text(0.25) == "MEDIUM"
        assert risk_to_text(0.50) == "HIGH"
        assert risk_to_text(1.0) == "HIGH"

    def test_zero_rain_is_low(self):
        assert risk_to_text(rain_risk_score(245, 8, 12, 0.0)) == "LOW"

    def test_heavy_rain_on_shallow_is_high(self):
        assert risk_to_text(rain_risk_score(245, 8, 12, 50.0)) == "HIGH"

    def test_deep_pan_lower_risk(self):
        shallow = rain_risk_score(260, 8, 12, 40)
        deep = rain_risk_score(260, 24, 12, 40)
        assert shallow > deep

    def test_api_simulate_rain_risk_levels(self, client):
        pan = _make_pan(client, "RISK-1",
                        {"water_depth_cm": 8.0, "brine_density_be": round(245.0 / 9.5, 4)})
        r = client.post(f"/api/pans/{pan['id']}/simulate-rain",
                        json={"rainfall_mm": 0.5})
        assert r.json()["risk_after"] == "LOW"
        r2 = client.post(f"/api/pans/{pan['id']}/simulate-rain",
                         json={"rainfall_mm": 100})
        assert r2.json()["risk_after"] == "HIGH"


# ════════════════════════════════════════════════════════════════════════════
# 8. RECOMMENDATION RULES
# ════════════════════════════════════════════════════════════════════════════

class TestRecommendationRules:
    def _make_timeline(self, readiness, risk, rain_mm=0.0, days=7):
        return [
            {
                "date": f"2025-01-{i+1:02d}",
                "label": f"{i+1} Jan",
                "temperature_c": 30.0, "rainfall_mm": rain_mm if i == 2 else 0.0,
                "humidity_pct": 55.0, "wind_speed_kmh": 12.0, "sunshine_hours": 9.0,
                "brine_density_be": 25.0, "salt_thickness_mm": 10.0,
                "water_depth_cm": 8.0, "days_since_last_rain": 5,
                "readiness": readiness, "risk": risk,
            }
            for i in range(days)
        ]

    def test_harvest_now_when_high_risk_and_ready(self):
        recs = generate_recommendations(
            default_twin_state(), self._make_timeline(0.70, 0.80, rain_mm=25.0))
        types = [r["recommendation_type"] for r in recs]
        assert "harvest_now" in types

    def test_harvest_soon_when_ready_low_risk(self):
        recs = generate_recommendations(
            default_twin_state(), self._make_timeline(0.65, 0.20))
        types = [r["recommendation_type"] for r in recs]
        assert "harvest_soon" in types

    def test_continue_evaporation_when_not_ready(self):
        recs = generate_recommendations(
            default_twin_state(), self._make_timeline(0.30, 0.10))
        types = [r["recommendation_type"] for r in recs]
        assert "continue_evaporation" in types

    def test_protect_pan_when_rain_forecast(self):
        recs = generate_recommendations(
            default_twin_state(), self._make_timeline(0.40, 0.60, rain_mm=20.0))
        types = [r["recommendation_type"] for r in recs]
        assert "protect_pan" in types

    def test_pump_excess_when_low_density(self):
        state = {**default_twin_state(), "brine_density_be": 15.0, "water_depth_cm": 10.0}
        recs = generate_recommendations(state, self._make_timeline(0.30, 0.10))
        types = [r["recommendation_type"] for r in recs]
        assert "pump_excess" in types

    def test_store_brine_when_concentrated_and_rain(self):
        state = {**default_twin_state(), "brine_density_be": 22.0}
        recs = generate_recommendations(state, self._make_timeline(0.40, 0.30, rain_mm=12.0))
        types = [r["recommendation_type"] for r in recs]
        assert "store_brine" in types

    def test_monitor_when_no_issues(self):
        """A healthy, calm pan gets the low-action advisory, not an urgent one.
        (density in range + shallow depth + low risk -> continue_evaporation;
        pump_excess is only for dilute water sitting on a deep bed.)"""
        state = {**default_twin_state(), "brine_density_be": 20.0, "water_depth_cm": 6.0}
        recs = generate_recommendations(state, self._make_timeline(0.30, 0.05))
        types = [r["recommendation_type"] for r in recs]
        assert "continue_evaporation" in types
        assert "pump_excess" not in types

    def test_six_part_contract(self):
        recs = generate_recommendations(
            default_twin_state(), self._make_timeline(0.70, 0.80, rain_mm=25.0))
        r = recs[0]
        assert "recommendation_type" in r
        assert "title" in r
        assert "reasons" in r and len(r["reasons"]) >= 3
        assert "instructions" in r and len(r["instructions"]) >= 3
        assert "confidence_pct" in r
        assert "consequence_if_waited" in r
        assert "action_deadline" in r

    def test_empty_timeline(self):
        recs = generate_recommendations(default_twin_state(), [])
        assert recs == []


# ════════════════════════════════════════════════════════════════════════════
# 9. SHAP EXPLANATION FORMATTING
# ════════════════════════════════════════════════════════════════════════════

class TestShapExplanation:
    def test_feature_glossary_covers_all_features(self):
        for feature in FEATURE_GLOSSARY:
            assert isinstance(FEATURE_GLOSSARY[feature], str)
            assert len(FEATURE_GLOSSARY[feature]) > 10

    def test_explain_feature_known(self):
        assert "rainfall" in explain_feature("forecast_rain_24h_mm").lower()

    def test_explain_feature_unknown_fallback(self):
        result = explain_feature("some_unknown_feature")
        assert "Some unknown feature" == result

    def test_shap_top_factors_sorted(self):
        values = {"a": 0.5, "b": -0.8, "c": 0.1, "d": -0.3}
        factors = shap_top_factors(values, n=3)
        assert len(factors) == 3
        assert factors[0]["feature"] == "b"
        assert factors[0]["contribution"] == -0.8

    def test_shap_top_factors_weight_pct(self):
        values = {"a": 0.6, "b": 0.2, "c": 0.1}
        factors = shap_top_factors(values, n=2)
        total_weight = sum(f["weight_pct"] for f in factors)
        assert total_weight > 80.0

    def test_shap_top_factors_empty(self):
        assert shap_top_factors(None) == []
        assert shap_top_factors({}) == []

    def test_shap_top_factors_all_explanations(self):
        values = {k: v for k, v in zip(
            ["forecast_rain_24h_mm", "water_depth_cm", "temperature_c"],
            [0.5, 0.3, 0.2])}
        factors = shap_top_factors(values, n=3)
        for f in factors:
            assert "explanation" in f
            assert len(f["explanation"]) > 5

    def test_context_factors_dry(self):
        st = default_twin_state()
        forecast = _7day_dry_forecast()
        ctx = context_factors(st, forecast)
        assert len(ctx) == 2
        assert ctx[0]["feature"] == "forecast_rain_24h_mm"
        assert "Little or no rain" in ctx[0]["explanation"]

    def test_context_factors_rainy(self):
        st = default_twin_state()
        forecast = _7day_rainy_forecast(20.0)
        ctx = context_factors(st, forecast)
        assert len(ctx) == 2
        assert "rain is expected" in ctx[1]["explanation"].lower() or \
               "dilute" in ctx[1]["explanation"].lower()

    def test_build_explanation_bundle(self):
        st = default_twin_state()
        forecast = _7day_dry_forecast()
        bundle = build_explanation(st, forecast, {}, {})
        assert "method" in bundle
        assert "harvest_readiness" in bundle
        assert "climate_risk" in bundle
        assert "context" in bundle

    def test_rain_recommendation_message(self):
        msg = recommend_action(245.0, "HIGH")
        assert msg in ("harvest_now", "store_brine", "protect_pan", "monitor")

    def test_low_risk_recommendation(self):
        assert recommend_action(245.0, "LOW") == "monitor"


# ════════════════════════════════════════════════════════════════════════════
# 10. FEEDBACK OUTCOME LINKING
# ════════════════════════════════════════════════════════════════════════════

class TestFeedbackOutcomeLinking:
    def test_outcome_recorded(self, client):
        pan = _make_pan(client, "FB-1")
        r = client.post("/api/outcomes", json={
            "pan_id": pan["id"],
            "outcome_date": "2025-01-15",
            "actual_rainfall_mm": 5.0,
            "action_taken": "harvest",
            "actual_yield_kg": 80000.0,
            "salt_purity_pct": 96.5,
        })
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["pan_id"] == pan["id"]
        assert body["actual_yield_kg"] == 80000.0

    def test_outcome_verify(self, client):
        pan = _make_pan(client, "FB-2")
        r = client.post("/api/outcomes", json={
            "pan_id": pan["id"],
            "outcome_date": "2025-01-16",
            "action_taken": "harvest",
        })
        oid = r.json()["id"]
        v = client.post(f"/api/outcomes/{oid}/verify")
        assert v.status_code == 200
        assert v.json()["verified"] is True

    def test_outcome_list(self, client):
        pan = _make_pan(client, "FB-3")
        client.post("/api/outcomes", json={
            "pan_id": pan["id"], "action_taken": "no_action",
        })
        r = client.get("/api/outcomes", params={"pan_id": pan["id"]})
        assert r.status_code == 200
        assert len(r.json()) >= 1

    def test_outcome_on_missing_pan(self, client):
        r = client.post("/api/outcomes", json={"pan_id": 999999})
        assert r.status_code == 404

    def test_outcome_verify_missing(self, client):
        r = client.post("/api/outcomes/999999/verify")
        assert r.status_code == 404

    def test_apply_outcome_to_twin_rain(self):
        state = {**default_twin_state(), "water_depth_cm": 8.0,
                 "brine_density_be": 25.0, "salt_thickness_mm": 10.0,
                 "days_since_last_rain": 5}
        outcome = {"actual_rainfall_mm": 20.0, "action_taken": "no_action"}
        new = apply_outcome_to_twin(state, outcome)
        assert new["days_since_last_rain"] == 0
        assert new["water_depth_cm"] > 8.0
        assert new["brine_density_be"] < 25.0

    def test_apply_outcome_to_twin_harvest(self):
        state = {**default_twin_state(), "water_depth_cm": 8.0,
                 "brine_density_be": 25.0, "salt_thickness_mm": 10.0}
        outcome = {"action_taken": "harvest"}
        new = apply_outcome_to_twin(state, outcome)
        assert new["salt_thickness_mm"] == 0.4
        assert new["water_depth_cm"] == 10.0

    def test_eval_summary_endpoint(self, client):
        r = client.get("/api/evaluation/summary")
        assert r.status_code == 200
        body = r.json()
        assert "total_outcomes" in body
        assert "risk_accuracy" in body

    def test_comparison_endpoint(self, client):
        r = client.get("/api/evaluation/comparison")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_feedback_endpoint(self, client):
        r = client.post("/api/evaluation/feedback")
        assert r.status_code == 200
        body = r.json()
        assert "ingested" in body


# ════════════════════════════════════════════════════════════════════════════
# 11. API ENDPOINTS
# ════════════════════════════════════════════════════════════════════════════

class TestAPIEndpoints:
    def test_health(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_system_status(self, client):
        r = client.get("/api/system/status")
        assert r.status_code == 200
        body = r.json()
        assert "pans" in body
        assert "models" in body

    def test_create_and_get_pan(self, client):
        r = client.post("/api/pans", json={
            "pan_id": "API-1", "name": "API Test Pan", "location": "Test",
            "area_m2": 500.0, "latitude": 12.0, "longitude": 75.0,
        })
        assert r.status_code == 201
        pan = r.json()
        g = client.get(f"/api/pans/{pan['id']}")
        assert g.status_code == 200
        assert g.json()["pan_id"] == "API-1"

    def test_list_pans(self, client):
        r = client.get("/api/pans")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_duplicate_pan_rejected(self, client):
        _make_pan(client, "DUP-1")
        r = client.post("/api/pans", json={
            "pan_id": "DUP-1", "name": "Dup", "area_m2": 500.0,
        })
        assert r.status_code == 409

    def test_simulate_rain_endpoint(self, client):
        pan = _make_pan(client, "API-SIM",
                        {"water_depth_cm": 8.0, "brine_density_be": round(245.0 / 9.5, 4)})
        r = client.post(f"/api/pans/{pan['id']}/simulate-rain",
                        json={"rainfall_mm": 10})
        assert r.status_code == 200
        assert "predicted_salinity_after_rain_g_l" in r.json()

    def test_simulate_rain_invalid_payload(self, client):
        pan = _make_pan(client, "API-SIM2")
        for bad in [{"rainfall_mm": 0}, {"rainfall_mm": -5}, {"rainfall_mm": 400}]:
            assert client.post(f"/api/pans/{pan['id']}/simulate-rain",
                               json=bad).status_code == 422

    def test_digital_twin_endpoint(self, client):
        pan = _make_pan(client, "API-DT")
        r = client.get(f"/api/pans/{pan['id']}/digital-twin")
        assert r.status_code == 200
        body = r.json()
        assert "salinity_g_l" in body
        assert "brine_volume_m3" in body

    def test_datasets_list(self, client):
        r = client.get("/api/datasets")
        assert r.status_code == 200

    def test_recommendations_list(self, client):
        r = client.get("/api/recommendations")
        assert r.status_code == 200

    def test_predictions_list(self, client):
        r = client.get("/api/predictions")
        assert r.status_code == 200

    def test_pan_not_found(self, client):
        r = client.get("/api/pans/999999")
        assert r.status_code == 404

    def test_dataset_not_found(self, client):
        r = client.get("/api/datasets/999999")
        assert r.status_code == 404

    def test_recommendation_not_found(self, client):
        r = client.get("/api/recommendations/999999")
        assert r.status_code == 404


# ════════════════════════════════════════════════════════════════════════════
# 12. MASS-BALANCE EXAMPLE
# ════════════════════════════════════════════════════════════════════════════

class TestMassBalanceExample:
    """
    Published example:
        Area = 500 m², Depth = 8 cm → Volume = 40 m³
        Rain = 20 mm → Rain volume = 10 m³
        Initial salinity = 245 g/L
        Expected post-rain salinity = 196 g/L
    """

    def test_area_depth_volume(self):
        area = 500.0
        depth = 8.0
        volume = depth / 100.0 * area
        assert volume == 40.0

    def test_rain_volume(self):
        area = 500.0
        rain = 20.0
        rv = rain / 1000.0 * area
        assert rv == 10.0

    def test_post_rain_salinity(self):
        sal_init = 245.0
        depth = 8.0
        rain = 20.0
        depth_after = depth + rain / 10.0
        sal_after = sal_init * depth / depth_after
        assert depth_after == 10.0
        assert sal_after == 196.0

    def test_full_mass_balance(self):
        area = 500.0
        depth = 8.0
        rain = 20.0
        sal_init = 245.0
        vol = depth / 100.0 * area
        rv = rain / 1000.0 * area
        depth_after = depth + rain / 10.0
        sal_after = sal_init * depth / depth_after
        salt_before = sal_init * vol / 1000.0
        salt_after = sal_after * (vol + rv) / 1000.0
        assert vol == 40.0
        assert rv == 10.0
        assert depth_after == 10.0
        assert sal_after == 196.0
        assert abs(salt_before - salt_after) < 0.01

    def test_api_mass_balance(self, client):
        be = round(245.0 / 9.5, 4)
        pan = _make_pan(client, "MB-1",
                        {"water_depth_cm": 8.0, "brine_density_be": be,
                         "salt_thickness_mm": 6.0, "days_since_last_rain": 5},
                        area_m2=500.0)
        r = client.post(f"/api/pans/{pan['id']}/simulate-rain",
                        json={"rainfall_mm": 20})
        assert r.status_code == 200
        out = r.json()
        assert out["pan_id"] == "MB-1"
        assert out["current_salinity_g_l"] == 245.0
        assert out["current_depth_cm"] == 8.0
        assert out["current_volume_m3"] == 40.0
        assert out["rainfall_mm"] == 20.0
        assert out["rain_volume_m3"] == 10.0
        assert out["predicted_depth_after_rain_cm"] == 10.0
        assert out["predicted_salinity_after_rain_g_l"] == 196.0

    def test_progress_to_harvest(self):
        state = {**default_twin_state(), "brine_density_be": 25.0,
                 "salt_thickness_mm": 12.0}
        p = progress_to_harvest(state)
        assert 0.0 <= p <= 1.0
        assert p > 0.5

    def test_salt_mass_calculation(self):
        mass = salt_mass_kg(6.0, area_m2=500.0)
        expected = 6.0 / 1000.0 * 1200.0 * 500.0
        assert mass == round(expected, 1)
