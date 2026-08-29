import io

import pandas as pd
import pytest

from app.database import SessionLocal
from app.models import Pan, SensorReading, WeatherReading, HarvestOutcome, OperationEvent
from app.services.ingestion import (
    analyze_dataframe_full,
    import_rows,
    rejection_frame,
)
from app.config.domain_thresholds import get_domain_thresholds


def _csv_file(filename="data.csv", content=None):
    return {"file": (filename, io.BytesIO((content or "").encode()))}


def _weather_df():
    return pd.DataFrame({
        "timestamp": ["2023-01-01 08:00", "2023-01-01 09:00", "2023-01-01 10:00"],
        "pan_id": ["PAN-1"] * 3,
        "Forecast Rain (mm/24h)": [0.5, 12.0, 25.0],
        "Rain Probability %": [10, 40, 80],
        "Actual Rain (mm)": [0, 3, 18.5],
        "Air Temp(C)": [28, 27, 26],
        "Humidity (%)": [60, 65, 70],
        "Wind Speed (km/h)": [14, 22, 31],
    })


# ----------------------------------------------------------------------- pipeline


def test_combined_analysis_maps_columns(sample_dataset_path):
    df = pd.read_csv(sample_dataset_path)
    a, norm = analyze_dataframe_full(df)
    assert a["dataset_type"] == "combined"
    assert a["status"] == "valid"
    assert a["valid_rows"] == len(df)
    canonicals = {m["canonical"] for m in a["mappings"]}
    assert {"pan_id", "date", "brine_density_be", "temperature_c",
            "water_depth_cm", "rainfall_mm"}.issubset(canonicals)
    assert norm["pan_id"].astype(str).str.contains("PAN").all()
    # Outlier reporting is part of the quality doc.
    assert a["quality"]["outliers"]


def test_weather_analysis_converts_kmh_to_ms():
    a, norm = analyze_dataframe_full(_weather_df())
    assert a["dataset_type"] == "weather"
    assert a["status"] == "valid"
    assert a["required_missing"] == []
    mapped = {m["canonical"]: m for m in a["mappings"]}
    assert mapped["wind_speed_ms"]["original"] == "Wind Speed (km/h)"
    assert mapped["wind_speed_ms"]["converted"] is True
    assert mapped["forecast_rain_mm"]["original"] == "Forecast Rain (mm/24h)"
    assert a["conversions"], "km/h -> m/s conversion must be reported"
    assert norm["wind_speed_ms"].round(2).tolist() == [3.89, 6.11, 8.61]


def test_sensor_rows_rejected_with_reasons():
    df = pd.DataFrame({
        "timestamp": ["2023-01-01", "2023-01-02", "2023-01-03"],
        "pan_id": ["PAN-1"] * 3,
        "pan_area_m2": [2400] * 3,
        "salinity_g_L": [21, 1200, -5],
        "water_depth_cm": [12, 13, 14],
        "brine_temperature_C": ["x", 28, 29],
        "humidity_pct": [70, 75, -200],
    })
    a, norm = analyze_dataframe_full(df)
    assert a["status"] == "needs_review"
    assert a["valid_rows"] == 0
    assert a["rejected_rows"] == 3
    reasons = a["reject_reasons"]
    assert "non-numeric 'brine_temperature_c'" in reasons[0]
    assert "above max" in reasons[1]
    assert "below min" in reasons[2]
    rf = rejection_frame(norm, a)
    assert len(rf) == 3
    assert "_rejected_reason" in rf.columns


def test_duplicates_flagged():
    df = pd.DataFrame({
        "timestamp": ["2023-01-01", "2023-01-01", "2023-01-02"],
        "pan_id": ["PAN-1"] * 3,
        "pan_area_m2": [2400] * 3,
        "salinity_g_L": [21, 22, 20],
        "water_depth_cm": [12, 12, 13],
        "brine_temperature_C": [28, 28, 29],
        "humidity_pct": [70, 70, 71],
    })
    a, _ = analyze_dataframe_full(df)
    assert a["duplicates"]["count"] == 2
    assert all("duplicate" in r for r in a["reject_reasons"].values())


def test_missing_values_reported_as_counts():
    df = pd.DataFrame({
        "timestamp": ["2023-01-01", "2023-01-02"],
        "pan_id": ["PAN-1"] * 2,
        "pan_area_m2": [2400, None],
        "salinity_g_L": [21, None],
        "water_depth_cm": [12, 13],
        "brine_temperature_C": [28, None],
        "humidity_pct": [70, 71],
    })
    a, _ = analyze_dataframe_full(df)
    miss = a["quality"]["missing"]
    assert miss["salinity_g_l"] == 1
    assert miss["pan_area_m2"] == 1


def test_import_rows_weather_writes_table(db):
    a, norm = analyze_dataframe_full(_weather_df())
    summary = import_rows(db, a, norm, "weather-test")
    assert summary["imported_rows"] == 3
    assert summary["tables"] == ["weather_readings"]
    assert summary["created_pans"] == ["PAN-1"]
    rows = db.query(WeatherReading).all()
    assert len(rows) == 3
    assert rows[0].wind_speed_ms == pytest.approx(14 / 3.6, rel=1e-4)


def test_import_rows_combined_writes_sensors(sample_dataset_path):
    df = pd.read_csv(sample_dataset_path)
    a, norm = analyze_dataframe_full(df)
    session = SessionLocal()
    try:
        summary = import_rows(db=session, analysis=a, clean_df=norm, dataset_name="combined-test")
        assert summary["dataset_type"] == "combined"
        assert summary["imported_rows"] == a["valid_rows"]
        assert session.query(SensorReading).count() == summary["imported_rows"]
    finally:
        session.close()


# ----------------------------------------------------------------------- API


def test_thresholds_endpoint(client):
    r = client.get("/api/datasets/thresholds")
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["status"] == "prototype"
    assert "types" in body and "sensor" in body["types"]
    assert any(t["column"].startswith("sensor.") for t in body["thresholds"])


def test_preview_endpoint_does_not_persist(client):
    content = _weather_df().to_csv(index=False)
    r = client.post("/api/datasets/preview", files=_csv_file(content=content))
    assert r.status_code == 200
    body = r.json()
    assert body["dataset_type"] == "weather"
    assert body["missing"] == []
    assert any(m["canonical"] == "wind_speed_ms" and m["converted"] for m in body["mappings"])
    assert len(body["sample_rows"]) == 3


def test_upload_analysis_invalid_rows_import_flow(client):
    content = _weather_df().to_csv(index=False)
    r = client.post("/api/datasets/upload", files=_csv_file(content=content))
    assert r.status_code == 201
    ds = r.json()
    assert ds["status"] == "valid"
    assert ds["dataset_type"] == "weather"
    ds_id = ds["id"]

    ar = client.get(f"/api/datasets/{ds_id}/analysis")
    assert ar.status_code == 200
    assert ar.json()["status"] == "valid"

    inv = client.get(f"/api/datasets/{ds_id}/invalid_rows")
    assert inv.status_code == 200
    assert "No invalid rows" in inv.text

    pv = client.get(f"/api/datasets/{ds_id}/preview?stage=clean&n=2")
    assert pv.status_code == 200
    assert len(pv.json()["rows"]) == 2

    im = client.post(f"/api/datasets/{ds_id}/import")
    assert im.status_code == 200
    assert im.json()["summary"]["imported_rows"] == 3
    assert im.json()["dataset"]["status"] == "imported"


def test_invalid_rows_download(client):
    df = pd.DataFrame({
        "timestamp": ["2023-01-01", "2023-01-02", "2023-01-03"],
        "pan_id": ["PAN-1"] * 3,
        "pan_area_m2": [2400] * 3,
        "salinity_g_L": [21, 1200, 20],
        "water_depth_cm": [12, 13, 14],
        "brine_temperature_C": [28, 28, 29],
        "humidity_pct": [70, 75, 71],
    })
    r = client.post("/api/datasets/upload", files=_csv_file(content=df.to_csv(index=False)))
    ds_id = r.json()["id"]
    inv = client.get(f"/api/datasets/{ds_id}/invalid_rows")
    assert inv.status_code == 200
    assert "text/csv" in inv.headers["content-type"]
    assert "_rejected_reason" in inv.text
    assert "above max" in inv.text


def test_upload_missing_columns_via_api(client):
    content = "pan_id,date,temperature_c\nPAN-1,2023-04-01,32.5\n"
    r = client.post("/api/datasets/upload", files=_csv_file("tiny.csv", content=content))
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "invalid"
    assert body["validation_report"]["errors"]
    assert any("brine_density_be" in e or "salinity" in e
               for e in body["validation_report"]["errors"])