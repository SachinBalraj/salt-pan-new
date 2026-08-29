from __future__ import annotations

import datetime as dt
from typing import List, Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Pan, WeatherReading
from app.schemas import WeatherForecastOut
from app.services.weather_provider import weather_provider

router = APIRouter(prefix="/api/weather", tags=["weather"])


def _parse_date(value) -> Optional[dt.date]:
    try:
        return dt.date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _days_to_rows(pan_id: Optional[int], days: list, source: str) -> List[WeatherReading]:
    gen_at = dt.datetime.utcnow()
    return [
        WeatherReading(
            pan_id=pan_id,
            forecast_generated_at=gen_at,
            forecast_for=_parse_date(d.get("date")),
            forecast_rain_mm=float(d.get("rainfall_mm", 0.0)),
            rain_probability_pct=float(d.get("precipitation_probability_pct", 0.0)),
            temperature_c=float(d.get("temperature_c", 0.0)),
            humidity_pct=float(d.get("humidity_pct", 0.0)),
            wind_speed_ms=round(float(d.get("wind_speed_kmh", 0.0)) / 3.6, 2),
            solar_radiation_wm2=round(float(d.get("sunshine_hours", 0.0)) * 100.0, 1),
            cloud_cover_pct=round(max(0.0, 100.0 - float(d.get("sunshine_hours", 0.0)) * 8.0), 1),
            source=source,
        )
        for d in days
    ]


def _rows_to_forecast(rows: List[WeatherReading]) -> WeatherForecastOut:
    batch = sorted(rows, key=lambda r: r.forecast_for or dt.date.max)
    return WeatherForecastOut(
        id=rows[0].id,
        pan_id=rows[0].pan_id,
        source=rows[0].source,
        generated_at=rows[0].forecast_generated_at,
        days=[
            {
                "date": r.forecast_for.isoformat() if r.forecast_for else "",
                "temperature_c": r.temperature_c,
                "humidity_pct": r.humidity_pct,
                "wind_speed_kmh": round(r.wind_speed_ms * 3.6, 1),
                "rainfall_mm": r.forecast_rain_mm,
                "precipitation_probability_pct": r.rain_probability_pct,
                "sunshine_hours": round(r.solar_radiation_wm2 / 100.0, 1),
            }
            for r in batch
        ],
    )


@router.get("/forecast", response_model=WeatherForecastOut)
def get_forecast(
    pan_id: Optional[int] = None,
    days: int = 7,
    scenario: str = "auto",
    force_refresh: bool = False,
    db: Session = Depends(get_db),
):
    pan = None
    if pan_id is not None:
        pan = db.get(Pan, pan_id)
        if not pan:
            raise HTTPException(404, "Salt pan not found")

    if pan and not force_refresh:
        latest = (db.query(WeatherReading)
                  .filter(WeatherReading.pan_id == pan.id)
                  .order_by(WeatherReading.forecast_generated_at.desc())
                  .first())
        if latest:
            gen_at = latest.forecast_generated_at
            batch = (db.query(WeatherReading)
                     .filter(WeatherReading.pan_id == pan.id,
                             WeatherReading.forecast_generated_at == gen_at)
                     .all())
            if len(batch) >= days:
                return _rows_to_forecast(sorted(batch, key=lambda r: r.forecast_for or dt.date.max)[:days])

    lat = pan.latitude if pan else None
    lon = pan.longitude if pan else None
    source = None if scenario in ("auto", "") else scenario
    result = weather_provider.get_forecast(lat=lat, lon=lon, days=days, source=source)

    rows = _days_to_rows(pan.id if pan else None, list(result["days"]), str(result["source"]))
    for row in rows:
        db.add(row)
    db.commit()
    db.refresh(rows[0])
    return _rows_to_forecast(rows)


def read_forecast_file(path: str) -> List[dict]:
    if path.endswith(".csv"):
        df = pd.read_csv(path)
        return df.to_dict(orient="records")
    return []