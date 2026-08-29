"""Weather service: resolves the active provider from configuration.

Resolution rules (never hard-coded keys; everything from the environment):

* WEATHER_MOCK_MODE=true        -> always use the deterministic offline mock.
* WEATHER_PROVIDER=mock         -> mock.
* WEATHER_PROVIDER=csv          -> historical-weather CSV (mock continuation
                                   past its records; mock on missing file).
* WEATHER_PROVIDER=live         -> real weather API only when WEATHER_API_KEY
                                   is set; cascades to mock if it fails.
* WEATHER_PROVIDER=auto (default)-> real weather API when a key exists, with
                                   automatic mock fallback; no key means it
                                   runs entirely on mock weather.

The key invariant: **without an API key the complete application still works
on mock weather data**.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, Optional

from app.config import Settings, get_settings
from app.services.weather.base import WeatherProvider, simulate_rain
from app.services.weather.csv_provider import CsvWeatherProvider
from app.services.weather.mock import MockWeatherProvider
from app.services.weather.open_meteo import OpenMeteoProvider


class WeatherService:
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.mock = MockWeatherProvider()
        self.open_meteo = OpenMeteoProvider(self.settings)
        self.csv = CsvWeatherProvider(self.settings)
        self.simulate_rain = simulate_rain

    # ------------------------------------------------------------------
    def _has_key(self) -> bool:
        return bool((self.settings.weather_api_key or "").strip())

    def _active(self) -> WeatherProvider:
        mode = (self.settings.weather_provider or "auto").lower()
        if self.settings.weather_mock_mode or mode == "mock":
            return self.mock
        if mode == "csv":
            return self.csv
        if not self._has_key():
            return self.mock  # no key -> the app still works on mock weather
        return self.open_meteo

    def _select(self, source: Optional[str]) -> WeatherProvider:
        s = (source or "").strip().lower()
        if self.settings.weather_mock_mode:
            return self.mock
        if s == "mock":
            return self.mock
        if s == "csv":
            return self.csv
        if s in ("live", "open_meteo"):
            return self.open_meteo if self._has_key() else self.mock
        return self._active()

    # ------------------------------------------------------------------
    def get_forecast(
        self,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        start: Optional[dt.date] = None,
        days: int = 7,
        source: Optional[str] = None,
    ) -> Dict[str, object]:
        lat = lat if lat is not None else self.settings.weather_default_lat
        lon = lon if lon is not None else self.settings.weather_default_lon
        days = max(1, min(int(days), 30))

        provider = self._select(source)
        try:
            result = provider.get_forecast(lat=lat, lon=lon, start=start, days=days)
        except Exception:
            # Any provider outage still leaves the application working on mock.
            fallback = self._select("mock")
            result = fallback.get_forecast(lat=lat, lon=lon, start=start, days=days)
            result = {**result, "source": f"{result['source']} (fallback)"}
        return result


weather_provider = WeatherService()