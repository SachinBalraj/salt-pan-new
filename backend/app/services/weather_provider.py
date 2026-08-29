"""Legacy import shim for the Phase-8 weather provider package.

Existing callers import `weather_provider` (a resolver instance exposing
`get_forecast` and `simulate_rain`) and the `WeatherProvider` interface name
from here. The real implementation now lives in `app.services.weather`.
"""
from app.services.weather import (
    CsvWeatherProvider,
    MockWeatherProvider,
    OpenMeteoProvider,
    WeatherProvider,
    WeatherService,
    simulate_rain,
    weather_provider,
)

__all__ = [
    "WeatherProvider",
    "WeatherService",
    "weather_provider",
    "MockWeatherProvider",
    "OpenMeteoProvider",
    "CsvWeatherProvider",
    "simulate_rain",
]