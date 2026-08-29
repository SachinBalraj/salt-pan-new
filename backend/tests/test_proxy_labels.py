"""Phase 5: proxy / simulation label handling tests."""
import datetime as dt

import pandas as pd

from app.config.proxy_labels import get_proxy_labels_config
from app.services.proxy_labels import (
    DEFAULT_BANNER,
    ensure_labels,
    leakage_map,
    methodology_markdown,
    write_methodology,
)

ROWS = [
    {"brine_density_be": 26.5, "salt_thickness_mm": 11.5, "water_depth_cm": 8.0,
     "days_since_last_rain": 6, "temperature_c": 30.0, "humidity_pct": 60.0,
     "wind_speed_kmh": 12.0, "sunshine_hours": 9.0, "rainfall_mm": 0.0,
     "precipitation_7d_forecast_mm": 5.0},
    {"brine_density_be": 21.4, "salt_thickness_mm": 3.2, "water_depth_cm": 12.0,
     "days_since_last_rain": 9, "temperature_c": 27.0, "humidity_pct": 70.0,
     "wind_speed_kmh": 9.0, "sunshine_hours": 7.0, "rainfall_mm": 0.0,
     "precipitation_7d_forecast_mm": 40.0},
]


def test_proxy_generation_is_deterministic_and_complete():
    df = pd.DataFrame(ROWS)
    aug, report = ensure_labels(df)
    assert df is not aug  # never mutates caller frame
    assert aug["harvest_readiness"].notna().all()
    assert aug["climate_risk"].notna().all()
    assert "climate_risk_class" in aug.columns
    assert "days_to_harvest" in aug.columns
    assert "yield_loss_pct" in aug.columns
    assert "recommended_action" in aug.columns
    assert (aug["harvest_readiness_source"] == "proxy").all()
    assert report["uses_proxy_labels"] is True
    assert report["uses_proxy_labels_by_kind"] == {
        "harvest_readiness": True, "climate_risk": True}
    assert report["banner"] == DEFAULT_BANNER

    aug2, _ = ensure_labels(pd.DataFrame(ROWS))
    pd.testing.assert_series_equal(aug["harvest_readiness"], aug2["harvest_readiness"])
    pd.testing.assert_series_equal(aug["climate_risk"], aug2["climate_risk"])


def test_known_value_hand_calculation():
    # readiness = 0.5*clamp((26.5-24)/4) + 0.5*clamp(11.5/15) = 0.6958 (no rain penalty, dsr=6)
    aug, _ = ensure_labels(pd.DataFrame([ROWS[0]]))
    assert round(aug.loc[0, "harvest_readiness"], 4) == 0.6958
    # risk = 0.04 + 0.55*5/80 + 0.26*11.5/15 + 0.12*(26.5-20)/8 ~ 0.3712
    assert round(aug.loc[0, "climate_risk"], 4) == 0.3712
    assert aug.loc[0, "climate_risk_class"] == "medium"
    # days_to_harvest >0 for a growing bed
    assert aug.loc[0, "days_to_harvest"] == 6.0
    # yield loss small for 5mm forecast
    assert 0.0 < aug.loc[0, "yield_loss_pct"] < 1.0
    assert aug.loc[0, "recommended_action"] == "harvest_soon"


def test_zero_thickness_is_safe():
    row = dict(ROWS[0], salt_thickness_mm=0.0, water_depth_cm=0.0)
    aug, _ = ensure_labels(pd.DataFrame([row]))
    assert aug.loc[0, "yield_loss_pct"] == 0.0  # no divide-by-zero
    assert pd.notna(aug.loc[0, "harvest_readiness"])
    assert aug.loc[0, "harvest_readiness"] == 0.5 * ((26.5 - 24.0) / 4.0)


def test_field_mode_preserves_values_and_flags_proxy_correctly():
    rows = [
        dict(ROWS[0], harvest_readiness=0.95, climate_risk=0.05,
             harvest_readiness_source="field", climate_risk_source="field"),
        dict(ROWS[1]),
    ]
    aug, report = ensure_labels(pd.DataFrame(rows))
    assert aug.loc[0, "harvest_readiness"] == 0.95
    assert aug.loc[0, "harvest_readiness_source"] == "field"
    assert aug.loc[0, "climate_risk"] == 0.05
    # unprovenanced row is proxied
    assert aug.loc[1, "harvest_readiness_source"] == "proxy"
    assert report["labels"]["harvest_readiness"]["mode"] == "mixed"
    assert report["uses_proxy_labels"] is True  # some proxy rows used


def test_full_field_mode_reports_no_proxy():
    rows = [
        {"brine_density_be": 26.5, "salt_thickness_mm": 11.5, "harvest_readiness": 0.8,
         "climate_risk": 0.2, "action_recorded": "harvest"},
    ]
    aug, report = ensure_labels(pd.DataFrame(rows), dataset_source="feedback")
    assert report["uses_proxy_labels"] is False
    assert report["labels"]["harvest_readiness"]["mode"] == "field"
    assert aug.loc[0, "harvest_readiness"] == 0.8
    # recommended_action falls back to the recorded (real) action
    assert aug.loc[0, "recommended_action"] == "harvest"
    assert aug.loc[0, "recommended_action_source"] == "field"


def test_missing_labels_are_generated_for_training():
    from app.services.data_generator import dataset_to_file, generate_dataset
    import tempfile

    df = generate_dataset(start=dt.date(2022, 1, 1), end=dt.date(2022, 6, 30),
                          pan_ids=["PAN-1"], seed=3)
    aug, report = ensure_labels(df)
    assert aug["harvest_readiness"].notna().all()
    assert aug["climate_risk"].notna().all()
    assert report["uses_proxy_labels_by_kind"]["harvest_readiness"] is True


def test_leakage_map_documents_non_independence():
    lk = leakage_map()
    assert "harvest_readiness" in lk["map"]
    assert "brine_density_be" in lk["map"]["harvest_readiness"]
    assert "salt_thickness_mm" in lk["map"]["harvest_readiness"]
    assert "note" in lk


def test_methodology_documentation_generated(tmp_path):
    text = methodology_markdown()
    assert "PROXY/SIMULATED MODEL — NOT YET FIELD VALIDATED" in text
    assert "harvest_readiness" in text
    assert "days_to_harvest" in text
    assert "yield_loss_pct" in text
    assert "recommended_action" in text
    out = tmp_path / "proxy_label_methodology.md"
    write_methodology(out)
    assert out.exists()
    assert "not an independent field validation" in out.read_text().lower() or "self-consistency" in out.read_text()


def test_label_status_endpoint(client):
    r = client.get("/api/models/label-status")
    assert r.status_code == 200
    body = r.json()
    assert body["any_active_proxy"] is True
    assert "NOT YET FIELD VALIDATED" in body["banner"]
    assert body["config_file"]
    assert body["methodology_file"]


def test_train_reports_uses_proxy_labels(client, sample_dataset_path):
    with open(sample_dataset_path, "rb") as fh:
        r = client.post("/api/datasets/upload",
                        files={"file": ("labels.csv", fh, "text/csv")})
    assert r.status_code == 201, r.text
    ds_id = r.json()["id"]

    r = client.post("/api/models/train", json={"kind": "harvest_readiness",
                                               "dataset_id": ds_id})
    assert r.status_code == 201, r.text
    trained = r.json()
    assert len(trained) == 1
    model = trained[0]
    assert model["uses_proxy_labels"] is True

    # model list also exposes the flag on ModelOut
    r = client.get("/api/models")
    assert r.status_code == 200
    listed = next(m for m in r.json() if m["id"] == model["id"])
    assert listed["uses_proxy_labels"] is True

    r = client.get(f"/api/models/{model['id']}")
    assert r.status_code == 200
    assert r.json()["uses_proxy_labels"] is True


def test_proxy_config_overridable():
    cfg = get_proxy_labels_config()
    assert cfg["meta"]["status"] == "prototype"
    assert set(("harvest_readiness", "climate_risk", "days_to_harvest",
                "yield_loss", "recommended_action")).issubset(cfg["labels"])