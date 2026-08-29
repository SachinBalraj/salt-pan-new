"""Weather provider interface shared by every concrete source.

A provider's job is to return the same canonical *day-dict* shape whether the
forecast came from a live weather API, the deterministic offline mock or a
historical CSV, so callers never care which source was used:

  {
      "date": "YYYY-MM-DD",
      "temperature_c": float,
      "humidity_pct": float,
      "wind_speed_kmh": float,
      "rainfall_mm": float,             # the forecast/estimate for that day
      "precipitation_probability_pct": float,
      "sunshine_hours": float,
      "actual_rainfall_mm": float|None, # optional: already-observed rainfall
  }
"""
from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from typing import Dict, List, Optional


class WeatherProvider(ABC):
    """Provider interface for weather / forecast sources."""

    name = "abstract"

    @abstractmethod
    def get_forecast(
        self,
        lat: float,
        lon: float,
        start: Optional[dt.date],
        days: int,
    ) -> Dict[str, object]:
        """Return {'source': str, 'generated_at': str, 'days': [day-dict, ...]}."""


def simulate_rain(
    days: List[dict], rainfall_mm: float, day_offset: int,
    dry_days_after: int = 3,
) -> List[dict]:
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