import logging
import os
import sys
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent

_MAX_UPLOAD_MB = 50  # hard ceiling for CSV uploads


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Salt Pan Decision Support System"
    environment: str = "development"
    debug: bool = True

    # SQLite by default so the app runs with zero infra in dev.
    # Docker Compose overrides this with PostgreSQL.
    database_url: str = "sqlite:///./salt_pan_dss.db"

    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    data_dir: str = str(PROJECT_DIR / "data")
    models_dir: str = str(PROJECT_DIR / "models")

    # Seed a fully-working demo on first boot (empty DB).
    auto_seed: bool = True

    # Weather source: auto (live-with-mock-fallback) | live | mock | csv
    weather_provider: str = "auto"
    # API key for the real weather API, read from the environment only.
    # Leave blank to run the whole application on deterministic mock weather.
    weather_api_key: str = ""
    # True forces the offline mock provider regardless of weather_provider.
    weather_mock_mode: bool = False
    # Path to a historical-weather CSV for the "csv" provider (missing file ->
    # falls back to mock continuation).
    weather_csv_path: str = ""
    weather_default_lat: float = 19.17
    weather_default_lon: float = 74.73

    # --- Security / reliability settings ---
    max_upload_mb: int = _MAX_UPLOAD_MB
    # Equipment safety: if True the system MUST NOT send commands to physical
    # pumps, valves, gates, or any actuator. This is a hard safety guardrail
    # for prototype / field-trial stages.
    physical_equipment_control: bool = False
    # Production deployments MUST set this to False after risk assessment.
    allow_auto_retrain: bool = True

    @field_validator("environment")
    @classmethod
    def _validate_environment(cls, v: str) -> str:
        allowed = {"development", "staging", "production", "testing"}
        if v not in allowed:
            raise ValueError(
                f"ENVIRONMENT must be one of {sorted(allowed)}, got '{v}'"
            )
        return v

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, v: str) -> str:
        if not v or not v.startswith(("sqlite", "postgresql", "mysql")):
            raise ValueError(
                "DATABASE_URL must start with sqlite, postgresql, or mysql"
            )
        # Never allow credentials logged.
        return v

    @field_validator("weather_api_key")
    @classmethod
    def _mask_weather_key(cls, v: str) -> str:
        # Allow empty (mock mode). If present, mask for logs.
        if v:
            logger.info("Weather API key loaded (masked for security)")
        return v

    def validate_startup(self) -> None:
        """Call once at startup to surface configuration issues early."""
        problems: list[str] = []

        if self.environment == "production":
            if self.debug:
                problems.append("DEBUG=true is unsafe in production")
            if "sqlite" in self.database_url:
                problems.append("SQLite is not recommended for production")
            if self.auto_seed:
                problems.append("AUTO_SEED=true should be false in production")

        if self.physical_equipment_control:
            problems.append(
                "PHYSICAL_EQUIPMENT_CONTROL=true is ENABLED — "
                "this allows the system to activate pumps/gates/valves. "
                "Set to False for prototype deployments."
            )

        if self.max_upload_mb < 1 or self.max_upload_mb > 500:
            problems.append(f"MAX_UPLOAD_MB={self.max_upload_mb} is outside 1-500 MB range")

        if problems:
            for p in problems:
                logger.warning("CONFIG WARNING: %s", p)
        else:
            logger.info("Startup configuration validated OK (env=%s)", self.environment)

    @property
    def seeds(self):
        return {"DATA_DIR": self.data_dir, "MODELS_DIR": self.models_dir}

    @property
    def data_path(self) -> Path:
        p = Path(self.data_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def models_path(self) -> Path:
        p = Path(self.models_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def raw_data_path(self) -> Path:
        return self._subdir("raw")

    @property
    def processed_data_path(self) -> Path:
        return self._subdir("processed")

    @property
    def samples_path(self) -> Path:
        return self._subdir("samples")

    def _subdir(self, name: str) -> Path:
        p = self.data_path / name
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgres")


@lru_cache
def get_settings() -> Settings:
    return Settings()