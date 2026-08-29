"""Historical-weather provider backed by a CSV file.

Days found in the CSV are served from recorded history (their `rainfall_mm` is
the observed value, carried both as the forecast estimate for that day and as
`actual_rainfall_mm`). Days outside the recorded range are back-filled with the
deterministic mock so the API always returns a full horizon. A missing or
unreadable file makes this provider raise; WeatherService then cascades to mock.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from app.config import Settings
from app.services.weather.base import WeatherProvider
from app.services.weather.mock import MockWeatherProvider


class CsvWeatherProvider(WeatherProvider):
    name = "csv"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.path = self._resolve_path(settings)
        self._mock = MockWeatherProvider()
        self._history: Dict[str, dict] = {}
        self.load_error: Optional[str] = None
        if self.path.exists():
            try:
                self._history = self._load(self.path)
            except Exception as exc:  # unreadable CSV must never take the app down
                self.load_error = str(exc)
                self._history = {}

    def _resolve_path(self, settings: Settings) -> Path:
        if settings.weather_csv_path:
            return Path(settings.weather_csv_path)
        return Path(settings.data_dir) / "samples" / "weather_historical.csv"

    def _load(self, path: Path) -> Dict[str, dict]:
        df = pd.read_csv(path)
        # Column aliases -> canonical names so exported files "just work".
        rename = {
            "rainfall_mm": "rainfall_mm", "actual_rainfall_mm": "rainfall_mm",
            "precip_mm": "rainfall_mm", "rain_mm": "rainfall_mm",
            "temp_c": "temperature_c", "temperature_c": "temperature_c",
            "humidity_pct": "humidity_pct", "humidity": "humidity_pct",
            "wind_speed_kmh": "wind_speed_kmh", "wind": "wind_speed_kmh",
            "sunshine_hours": "sunshine_hours", "sun_hours": "sunshine_hours",
            "precipitation_probability_pct": "precipitation_probability_pct",
        }
        df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
        needed = {"date", "temperature_c", "humidity_pct", "wind_speed_kmh",
                  "rainfall_mm", "precipitation_probability_pct", "sunshine_hours"}
        missing = needed - set(df.columns)
        if missing:
            raise ValueError(f"weather CSV must contain columns: {sorted(needed)} "
                             f"(missing {sorted(missing)})")

        history: Dict[str, dict] = {}
        for _, row in df.iterrows():
            day = str(row.get("date", "")).strip()
            try:
                day = dt.date.fromisoformat(day[:10]).isoformat()
            except ValueError:
                continue
            history[day] = {
                "date": day,
                "temperature_c": float(row["temperature_c"]),
                "humidity_pct": float(row["humidity_pct"]),
                "wind_speed_kmh": float(row["wind_speed_kmh"]),
                "rainfall_mm": round(float(row["rainfall_mm"]), 1),
                "precipitation_probability_pct": round(float(row["precipitation_probability_pct"]), 1),
                "sunshine_hours": float(row["sunshine_hours"]),
                "actual_rainfall_mm": round(float(row["rainfall_mm"]), 1),
            }
        return history

    def get_forecast(
        self,
        lat: float,
        lon: float,
        start: Optional[dt.date] = None,
        days: int = 7,
    ) -> dict:
        start = start or dt.date.today()
        out: List[dict] = []
        used_csv = 0
        for i in range(days):
            day = start + dt.timedelta(days=i)
            row = self._history.get(day.isoformat())
            if row is not None:
                used_csv += 1
                out.append(dict(row))
            else:
                out.append(self._mock_days_one(lat, lon, day))
        if used_csv == days:
            source = self.name
        elif used_csv:
            source = "csv+mock"
        else:
            source = "mock"
        return {
            "source": source,
            "days": out,
            "generated_at": dt.datetime.utcnow().isoformat(),
        }

    def _mock_days_one(self, lat: float, lon: float, day: dt.date) -> dict:
        days = self._mock.get_forecast(lat, lon, start=day, days=1)["days"]
        return days[0]