from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

UTC = datetime.utcnow


def utcnow() -> datetime:
    return datetime.utcnow()


class DataSet(Base):
    """An uploaded / generated salt-pan dataset (raw rows)."""

    __tablename__ = "datasets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    filepath: Mapped[str] = mapped_column(String(1024), nullable=False)
    rows_count: Mapped[int] = mapped_column(Integer, default=0)
    columns: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="uploaded")  # uploaded|validating|valid|invalid|promoted
    validation_report: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(32), default="upload")  # upload|generated|feedback
    created_at: Mapped[datetime] = mapped_column(DateTime, default=UTC)

    ml_models: Mapped[list["MLModel"]] = relationship(back_populates="dataset")


class SaltPan(Base):
    __tablename__ = "salt_pans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pan_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    location: Mapped[str] = mapped_column(String(255), default="")
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    area_m2: Mapped[float] = mapped_column(Float, default=1000.0)
    status: Mapped[str] = mapped_column(String(32), default="active")
    # Digital twin live state, e.g. {water_depth_cm, brine_density_be, salt_thickness_mm,
    # last_rain_date, last_harvest_date, estimated_salt_mass_kg, notes}
    twin_state: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=UTC)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=UTC, onupdate=UTC)

    predictions: Mapped[list["Prediction"]] = relationship(back_populates="pan", cascade="all, delete-orphan")
    recommendations: Mapped[list["Recommendation"]] = relationship(back_populates="pan", cascade="all, delete-orphan")
    outcomes: Mapped[list["Outcome"]] = relationship(back_populates="pan", cascade="all, delete-orphan")
    snapshots: Mapped[list["TwinSnapshot"]] = relationship(back_populates="pan", cascade="all, delete-orphan")


class MLModel(Base):
    __tablename__ = "ml_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)  # harvest_readiness | climate_risk
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="trained")
    artifact_path: Mapped[str] = mapped_column(String(1024), default="")
    feature_names: Mapped[list] = mapped_column(JSON, default=list)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    rows_trained: Mapped[int] = mapped_column(Integer, default=0)
    dataset_id: Mapped[Optional[int]] = mapped_column(ForeignKey("datasets.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=UTC)

    dataset: Mapped[Optional["DataSet"]] = relationship(back_populates="ml_models")
    predictions: Mapped[list["Prediction"]] = relationship(back_populates="model")


class WeatherForecast(Base):
    __tablename__ = "weather_forecasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pan_id: Mapped[Optional[int]] = mapped_column(ForeignKey("salt_pans.id"), nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="mock")  # open_meteo | mock
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=UTC)
    data: Mapped[list] = mapped_column(JSON, default=list)  # list of daily forecast dicts


class Prediction(Base):
    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pan_id: Mapped[int] = mapped_column(ForeignKey("salt_pans.id"), index=True)
    model_id: Mapped[Optional[int]] = mapped_column(ForeignKey("ml_models.id"), nullable=True)
    prediction_type: Mapped[str] = mapped_column(String(64), nullable=False)  # harvest_readiness | climate_risk | combined
    scenario: Mapped[str] = mapped_column(String(64), default="actual_forecast")  # actual_forecast | rain_simulation
    score: Mapped[float] = mapped_column(Float, default=0.0)
    horizon_days: Mapped[int] = mapped_column(Integer, default=7)
    prediction_date: Mapped[str] = mapped_column(String(32), default="")
    forecast_date: Mapped[str] = mapped_column(String(32), default="")
    features: Mapped[dict] = mapped_column(JSON, default=dict)
    shap_values: Mapped[dict] = mapped_column(JSON, default=dict)
    series: Mapped[list] = mapped_column(JSON, default=list)  # daily timeline for charts
    created_at: Mapped[datetime] = mapped_column(DateTime, default=UTC)

    pan: Mapped["SaltPan"] = relationship(back_populates="predictions")
    model: Mapped[Optional["MLModel"]] = relationship(back_populates="predictions")
    recommendations: Mapped[list["Recommendation"]] = relationship(back_populates="prediction")
    outcomes: Mapped[list["Outcome"]] = relationship(back_populates="prediction")


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pan_id: Mapped[int] = mapped_column(ForeignKey("salt_pans.id"), index=True)
    prediction_id: Mapped[Optional[int]] = mapped_column(ForeignKey("predictions.id"), nullable=True)
    recommendation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    rationale: Mapped[str] = mapped_column(Text, default="")
    expected_benefit: Mapped[str] = mapped_column(String(512), default="")
    risk_level: Mapped[str] = mapped_column(String(32), default="low")  # low | medium | high
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending|accepted|declined|expired
    farmer_notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=UTC)
    responded_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    pan: Mapped["SaltPan"] = relationship(back_populates="recommendations")
    prediction: Mapped[Optional["Prediction"]] = relationship(back_populates="recommendations")
    outcomes: Mapped[list["Outcome"]] = relationship(back_populates="recommendation")


class Outcome(Base):
    """Actual recorded outcome for a pan (rainfall, actions, harvest, yield)."""

    __tablename__ = "outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pan_id: Mapped[int] = mapped_column(ForeignKey("salt_pans.id"), index=True)
    prediction_id: Mapped[Optional[int]] = mapped_column(ForeignKey("predictions.id"), nullable=True)
    recommendation_id: Mapped[Optional[int]] = mapped_column(ForeignKey("recommendations.id"), nullable=True)
    outcome_date: Mapped[str] = mapped_column(String(32), default="")
    actual_rainfall_mm: Mapped[float] = mapped_column(Float, default=0.0)
    risk_occurred: Mapped[bool] = mapped_column(Boolean, default=False)
    action_taken: Mapped[str] = mapped_column(String(128), default="")
    harvest_date: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    harvest_delayed_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    actual_yield_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    brine_density_be: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    salt_thickness_mm: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    feedback_ingested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=UTC)

    pan: Mapped["SaltPan"] = relationship(back_populates="outcomes")
    prediction: Mapped[Optional["Prediction"]] = relationship(back_populates="outcomes")
    recommendation: Mapped[Optional["Recommendation"]] = relationship(back_populates="outcomes")


class TwinSnapshot(Base):
    """Immutable historical snapshots that let the twin 'learn' from feedback."""

    __tablename__ = "twin_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pan_id: Mapped[int] = mapped_column(ForeignKey("salt_pans.id"), index=True)
    snapshot_date: Mapped[str] = mapped_column(String(32), default="")
    source: Mapped[str] = mapped_column(String(64), default="seed")  # seed|forecast|simulation|outcome_feedback
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=UTC)

    pan: Mapped["SaltPan"] = relationship(back_populates="snapshots")