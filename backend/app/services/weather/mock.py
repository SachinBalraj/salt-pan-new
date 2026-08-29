"""Deterministic offline mock weather provider.

Produces the same forecast for the same (lat, lon, day) every run, so demos,
simulations and tests are fully reproducible with zero network access.
"""
from __future__ import annotations

import datetime as dt
import math
from typing import List, Optional

from app.services.weather.base import WeatherProvider


class MockWeatherProvider(WeatherProvider):
    name = "mock"

    def get_forecast(
        self,
        lat: float,
        lon: float,
        start: Optional[dt.date] = None,
        days: int = 7,
    ) -> dict:
        start = start or dt.date.today()
        return {
            "source": self.name,
            "days": self._mock_days(lat, lon, start, days),
            "generated_at": dt.datetime.utcnow().isoformat(),
        }

    def _mock_days(self, lat: float, lon: float, start: dt.date, days: int) -> List[dict]:
        out: List[dict] = []
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