from __future__ import annotations

import datetime as dt
import math
from typing import Dict, List, Optional

import httpx

from app.config import Settings, get_settings


class WeatherProvider:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    # ------------------------------------------------------------------
    def _mock_days(self, lat: float, lon: float, start: dt.date, days: int) -> List[dict]:
        out: List[dict] = []
        year = start.year
        for i in range(days):
            day = start + dt.timedelta(days=i)
            # deterministic pseudo-random noise per (lat, lon, date)
            h = (hash(f"{lat:.3f}|{lon:.3f}|{day.isoformat()}") & 0xFFFF)
            r1 = (h % 997) / 997.0
            r2 = ((h * 31 + 11) % 997) / 997.0
            doy = float(day.timetuple().tm_yday)
            annual = 2 * math.pi * (doy - 120) / 365.0
            monsoon = max(math.sin(2 * math.pi * (doy - 180) / 200.0), 0.0)
            temp = 28.0 + 6.0 * math.cos(annual) + r1 * 3.0 - 1.5
            rain = 0.0
            if r2 < (0.07 + 0.55 * monsoon):
                rain = round(max(0.0, 2.0 * (4.0 ** r2) * (0.4 + 0.6 * monsoon)), 1)
            hum = min(100.0, max(15.0, 52.0 - 18.0 * math.cos(annual)
                                 + 22.0 * monsoon + r1 * 12.0))
            wind = max(0.0, 9.0 + 6.0 * monsoon + r2 * 14.0)
            sun = max(0.0, min(13.0, 11.0 - 2.2 * monsoon - rain / 30.0 + r1 * 2.0))
            out.append({
                "date": day.strftime("%Y-%m-%d"),
                "temperature_c": round(temp, 1),
                "humidity_pct": round(hum, 1),
                "wind_speed_kmh": round(wind, 1),
                "rainfall_mm": rain,
                "precipitation_probability_pct": round(min(98.0, 5.0 + rain * 6.5 + monsoon * 25.0 + r2 * 10.0), 1),
                "sunshine_hours": round(sun, 1),
            })
        return out

    def _live_days(self, lat: float, lon: float, days: int) -> List[dict]:
        """Calls the Open-Meteo public API (no key required)."""
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": lat,
            "longitude": lon,
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,"
                     "precipitation_probability_max,windspeed_10m_max,relative_humidity_2m_max,sunshine_duration",
            "timezone": "UTC",
            "forecast_days": days,
        }
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
        provider = (source or self.settings.weather_provider or "auto").lower()
        start = start or dt.date.today()

        used = "mock"
        result: Optional[List[dict]] = None
        if provider in ("auto", "live"):
            try:
                result = self._live_days(lat, lon, days)
                used = "open_meteo"
            except Exception:
                result = None
                if provider == "live":
                    raise RuntimeError("Live weather provider unavailable (Open-Meteo). "
                                       "Run with WEATHER_PROVIDER=mock for offline mode.")
        if result is None:
            result = self._mock_days(lat, lon, start, days)
            used = "mock"
        return {"source": used, "days": result, "generated_at": dt.datetime.utcnow().isoformat()}

    @staticmethod
    def simulate_rain(days: List[dict], rainfall_mm: float, day_offset: int,
                      dry_days_after: int = 3) -> List[dict]:
        """Inject a synthetic rain event into a forecast timeline."""
        out = [dict(d) for d in days]
        idx = max(0, min(day_offset, len(out) - 1))
        out[idx]["rainfall_mm"] = round(float(rainfall_mm), 1)
        out[idx]["precipitation_probability_pct"] = 98.0
        out[idx]["humidity_pct"] = min(100.0, float(out[idx]["humidity_pct"]) + 18.0)
        out[idx]["sunshine_hours"] = round(max(0.0, float(out[idx]["sunshine_hours"]) - 4.0), 1)
        for j in range(idx + 1, min(idx + 1 + dry_days_after, len(out))):
            out[j]["rainfall_mm"] = 0.0
            out[j]["precipitation_probability_pct"] = max(0.0, float(out[j]["precipitation_probability_pct"]) - 35.0)
            out[j]["humidity_pct"] = min(100.0, float(out[j]["humidity_pct"]) + 6.0)
        return out


weather_provider = WeatherProvider()