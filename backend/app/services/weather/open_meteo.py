"""Real weather API provider (Open-Meteo).

Requires an API key via WEATHER_API_KEY (never hard-coded). When the key is
empty the resolver will not use this provider and the app runs on mock weather
instead. If the live call fails, the WeatherService layer cascades to mock so
the application keeps working offline.
"""
from __future__ import annotations

import datetime as dt
from typing import List, Optional

import httpx

from app.config import Settings
from app.services.weather.base import WeatherProvider


class OpenMeteoProvider(WeatherProvider):
    name = "open_meteo"

    def __init__(self, settings: Settings):
        self.settings = settings

    def get_forecast(
        self,
        lat: float,
        lon: float,
        start: Optional[dt.date] = None,
        days: int = 7,
    ) -> dict:
        return {
            "source": self.name,
            "days": self._live_days(lat, lon, days),
            "generated_at": dt.datetime.utcnow().isoformat(),
        }

    def _live_days(self, lat: float, lon: float, days: int) -> List[dict]:
        """Calls the Open-Meteo forecast API with the optional API key."""
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": lat,
            "longitude": lon,
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,"
                     "precipitation_probability_max,windspeed_10m_max,relative_humidity_2m_max,sunshine_duration",
            "timezone": "UTC",
            "forecast_days": days,
        }
        api_key = (self.settings.weather_api_key or "").strip()
        if api_key:
            params["apikey"] = api_key
        resp = httpx.get(url, params=params, timeout=15.0)
        resp.raise_for_status()
        data = resp.json()["daily"]
        out: List[dict] = []
        for i, d in enumerate(data["time"]):
            temp_layer = (float(data["temperature_2m_max"][i]) + float(data["temperature_2m_min"][i])) / 2.0
            out.append({
                "date": d,
                "temperature_c": round(temp_layer, 1),
                "humidity_pct": round(float(data["relative_humidity_2m_max"][i]), 1),
                "wind_speed_kmh": round(float(data["windspeed_10m_max"][i]), 1),
                "rainfall_mm": round(float(data["precipitation_sum"][i]), 1),
                "precipitation_probability_pct": round(float(data["precipitation_probability_max"][i]), 1),
                "sunshine_hours": round(float(data["sunshine_duration"][i]) / 3600.0, 1),
            })
        return out