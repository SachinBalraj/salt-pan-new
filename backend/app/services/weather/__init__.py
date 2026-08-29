"""Weather provider package: pluggable forecast sources for the DSS.

Public surface:
    weather_provider      -> the configured WeatherService singleton
    WeatherProvider       -> the provider interface (ABC)
    MockWeatherProvider / OpenMeteoProvider / CsvWeatherProvider
"""
from app.services.weather.base import WeatherProvider, simulate_rain
from app.services.weather.csv_provider import CsvWeatherProvider
from app.services.weather.mock import MockWeatherProvider
from app.services.weather.open_meteo import OpenMeteoProvider
from app.services.weather.service import WeatherService, weather_provider

__all__ = [
    "WeatherProvider",
    "WeatherService",
    "weather_provider",
    "MockWeatherProvider",
    "OpenMeteoProvider",
    "CsvWeatherProvider",
    "simulate_rain",
]