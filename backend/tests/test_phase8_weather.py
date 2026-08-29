"""Phase 8: weather service — provider interface (mock / live / csv),
environment-driven config, no-key mock guarantee, forecast-vs-actual storage."""
import datetime as dt
import os

import pandas as pd

from app.config import Settings
from app.services.weather.service import WeatherService

LAT, LON = 12.0, 75.0


def _svc(**overrides):
    base = dict(weather_provider="auto", weather_api_key="", weather_mock_mode=False,
                weather_csv_path="", weather_default_lat=LAT, weather_default_lon=LON)
    base.update(overrides)
    return WeatherService(Settings(**base))


def _write_csv(path, start: dt.date, n: int) -> str:
    rows = [{
        "date": (start + dt.timedelta(days=i)).isoformat(),
        "temperature_c": 30.0 + i,
        "humidity_pct": 60.0,
        "wind_speed_kmh": 12.0,
        "rainfall_mm": 10.0 + i,
        "precipitation_probability_pct": 20.0,
        "sunshine_hours": 9.0,
    } for i in range(n)]
    pd.DataFrame(rows).to_csv(path, index=False)
    return str(path)


# ------------------------------------------------------------ provider modes
def test_provider_resolves_mock_without_api_key():
    for svc in (_svc(),                          # auto, no key
                _svc(weather_provider="mock"),   # explicit mock
                _svc(weather_provider="live", weather_api_key="x",
                     weather_mock_mode=True)):   # mock kill-switch wins
        result = svc.get_forecast(LAT, LON, days=3)
        assert result["source"] == "mock"
        assert len(result["days"]) == 3
        for day in result["days"]:
            assert "actual_rainfall_mm" not in day or day["actual_rainfall_mm"] is None


def test_provider_explicit_live_without_key_still_mocks():
    # No API key present: no real API call is attempted, mock is used — the
    # complete application keeps working.
    svc = _svc()
    result = svc.get_forecast(LAT, LON, days=2, source="live")
    assert result["source"] == "mock"


def test_provider_live_with_key_falls_back_on_outage():
    svc = _svc(weather_provider="live", weather_api_key="secretvalue")

    def boom(*args, **kwargs):
        raise RuntimeError("live API down")

    svc.open_meteo.get_forecast = boom
    result = svc.get_forecast(LAT, LON, days=3)
    assert result["source"].startswith("mock")
    assert "fallback" in result["source"]
    assert len(result["days"]) == 3


def test_mock_is_deterministic_within_a_process():
    svc = _svc()
    a = svc.get_forecast(LAT, LON, start=dt.date(2026, 8, 1), days=5)
    b = svc.get_forecast(LAT, LON, start=dt.date(2026, 8, 1), days=5)
    assert a["days"] == b["days"]


# ----------------------------------------------------------------- csv mode
def test_csv_provider_serves_history_and_mock_continuation(tmp_path):
    start = dt.date(2026, 8, 1)
    path = _write_csv(tmp_path / "hist.csv", start, 2)
    svc = _svc(weather_provider="csv", weather_csv_path=path)

    result = svc.get_forecast(LAT, LON, start=start - dt.timedelta(days=1), days=3)
    assert result["source"] == "csv+mock"
    assert len(result["days"]) == 3
    # first day is before the history: mock, with no observed rainfall
    assert result["days"][0].get("actual_rainfall_mm") is None
    assert result["days"][0]["date"] == (start - dt.timedelta(days=1)).isoformat()
    # csv-recorded days carry the observed rainfall in actual_rainfall_mm
    for i, day in enumerate(result["days"][1:]):
        assert day["actual_rainfall_mm"] == 10.0 + i
        assert day["rainfall_mm"] == 10.0 + i


def test_csv_provider_all_days_in_history_reports_csv(tmp_path):
    start = dt.date(2026, 8, 1)
    path = _write_csv(tmp_path / "hist.csv", start, 3)
    svc = _svc(weather_provider="csv", weather_csv_path=path)
    result = svc.get_forecast(LAT, LON, start=start, days=3)
    assert result["source"] == "csv"
    assert all(d["actual_rainfall_mm"] is not None for d in result["days"])


def test_csv_provider_missing_file_falls_back_to_mock(tmp_path):
    svc = _svc(weather_provider="csv",
               weather_csv_path=str(tmp_path / "does_not_exist.csv"))
    result = svc.get_forecast(LAT, LON, days=2)
    assert result["source"] == "mock"
    assert len(result["days"]) == 2


def test_csv_provider_broken_file_does_not_crash(tmp_path):
    broken = tmp_path / "broken.csv"
    broken.write_text("nonsense,columns\n1,2,3\n")
    svc = _svc(weather_provider="csv", weather_csv_path=str(broken))
    assert svc.csv.load_error is not None
    result = svc.get_forecast(LAT, LON, days=2)
    assert result["source"] == "mock"


# ------------------------------------------- API: forecast vs actual storage
def _make_pan(client, code):
    r = client.post("/api/pans", json={
        "pan_id": code, "name": "Weather Pan", "location": "L",
        "area_m2": 1000.0, "latitude": LAT, "longitude": LON,
    })
    assert r.status_code == 201, r.text
    return r.json()


def test_forecast_stores_forecast_and_actual_rainfall_separately(client):
    pan = _make_pan(client, "WX-1")

    r = client.get(f"/api/weather/forecast?pan_id={pan['id']}&days=2&scenario=mock")
    assert r.status_code == 200, r.text
    forecast = r.json()
    assert len(forecast["days"]) == 2
    day0 = forecast["days"][0]
    assert day0["forecast_rain_mm"] == day0["rainfall_mm"]
    assert "id" in day0
    assert day0["actual_rainfall_mm"] is None

    # an observed amount lands only on the actual column
    r = client.post("/api/weather/actual", json={
        "pan_id": pan["id"], "date": day0["date"], "actual_rainfall_mm": 22.5})
    assert r.status_code == 200, r.text
    recorded = r.json()
    assert recorded["actual_rainfall_mm"] == 22.5
    assert recorded["forecast_rain_mm"] == day0["forecast_rain_mm"]
    assert recorded["forecast_rain_mm"] != 22.5  # the forecast is left untouched

    # the stored (cached) forecast now shows both columns separately
    r = client.get(f"/api/weather/forecast?pan_id={pan['id']}&days=2")
    assert r.status_code == 200, r.text
    day0_after = r.json()["days"][0]
    assert day0_after["actual_rainfall_mm"] == 22.5
    assert day0_after["forecast_rain_mm"] == day0["forecast_rain_mm"]


def test_record_actual_rainfall_rejections(client):
    pan = _make_pan(client, "WX-2")

    assert client.post("/api/weather/actual", json={
        "pan_id": 999999, "date": "2026-08-29", "actual_rainfall_mm": 5.0}).status_code == 404
    assert client.post("/api/weather/actual", json={
        "pan_id": pan["id"], "date": "not-a-date", "actual_rainfall_mm": 5.0}).status_code == 400
    assert client.post("/api/weather/actual", json={
        "pan_id": pan["id"], "date": "2026-08-29", "actual_rainfall_mm": -2.0}).status_code == 422
    assert client.post("/api/weather/actual", json={
        "pan_id": pan["id"], "date": "2026-08-29", "actual_rainfall_mm": 5.0}).status_code == 404