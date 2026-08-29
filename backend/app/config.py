import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent


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

    # Weather source: auto | mock | live
    weather_provider: str = "auto"
    weather_default_lat: float = 19.17
    weather_default_lon: float = 74.73

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