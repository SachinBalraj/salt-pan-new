from __future__ import annotations

from typing import List, Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import SaltPan, WeatherForecast
from app.schemas import WeatherForecastOut
from app.services.weather_provider import weather_provider

router = APIRouter(prefix="/api/weather", tags=["weather"])


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
        pan = db.get(SaltPan, pan_id)
        if not pan:
            raise HTTPException(404, "Salt pan not found")

    if pan and not force_refresh:
        cached = (db.query(WeatherForecast)
                  .filter(WeatherForecast.pan_id == pan.id, WeatherForecast.source != "simulation")
                  .order_by(WeatherForecast.generated_at.desc()).first())
        if cached and len(cached.data) >= days:
            record = cached
            return WeatherForecastOut(
                id=record.id, pan_id=record.pan_id, source=record.source,
                generated_at=record.generated_at, days=record.data[:days],
            )

    lat = pan.latitude if pan else None
    lon = pan.longitude if pan else None
    source = None if scenario in ("auto", "") else scenario
    result = weather_provider.get_forecast(lat=lat, lon=lon, days=days, source=source)

    record = WeatherForecast(
        pan_id=pan.id if pan else None,
        source=str(result["source"]),
        data=list(result["days"]),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return WeatherForecastOut(
        id=record.id, pan_id=record.pan_id, source=record.source,
        generated_at=record.generated_at, days=record.data,
    )


def read_forecast_file(path: str) -> List[dict]:
    if path.endswith(".csv"):
        df = pd.read_csv(path)
        return df.to_dict(orient="records")
    return []