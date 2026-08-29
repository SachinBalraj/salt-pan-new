from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
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
    dataset_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # sensor|weather|operations|combined
    status: Mapped[str] = mapped_column(String(32), default="uploaded")  # uploaded|valid|needs_review|invalid|imported|promoted
    validation_report: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(32), default="upload")  # upload|generated|feedback
    created_at: Mapped[datetime] = mapped_column(DateTime, default=UTC)


class Pan(Base):
    """A salt production pan (crystalliser / condenser bed)."""

    __tablename__ = "pans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pan_code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    area_m2: Mapped[float] = mapped_column(Float, default=1000.0)
    safe_depth_cm: Mapped[float] = mapped_column(Float, default=12.0)
    safe_storage_available: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=UTC)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=UTC, onupdate=UTC)

    sensor_readings: Mapped[list["SensorReading"]] = relationship(
        back_populates="pan", cascade="all, delete-orphan")
    weather_readings: Mapped[list["WeatherReading"]] = relationship(
        back_populates="pan", cascade="all, delete-orphan")
    twin_states: Mapped[list["DigitalTwinState"]] = relationship(
        back_populates="pan", cascade="all, delete-orphan")
    predictions: Mapped[list["Prediction"]] = relationship(
        back_populates="pan", cascade="all, delete-orphan")
    recommendations: Mapped[list["Recommendation"]] = relationship(
        back_populates="pan", cascade="all, delete-orphan")
    harvest_outcomes: Mapped[list["HarvestOutcome"]] = relationship(
        back_populates="pan", cascade="all, delete-orphan")
    operation_events: Mapped[list["OperationEvent"]] = relationship(
        back_populates="pan", cascade="all, delete-orphan",
        foreign_keys="OperationEvent.pan_id")


class SensorReading(Base):
    """In-situ sensor board telemetry for a pan (EC, depth, temps, humidity)."""

    __tablename__ = "sensor_readings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pan_id: Mapped[int] = mapped_column(ForeignKey("pans.id"), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=UTC)
    salinity_g_l: Mapped[float] = mapped_column(Float, default=0.0)
    ec_ms_cm: Mapped[float] = mapped_column(Float, default=0.0)
    water_depth_cm: Mapped[float] = mapped_column(Float, default=0.0)
    brine_temperature_c: Mapped[float] = mapped_column(Float, default=0.0)
    air_temperature_c: Mapped[float] = mapped_column(Float, default=0.0)
    humidity_pct: Mapped[float] = mapped_column(Float, default=0.0)
    sensor_quality: Mapped[float] = mapped_column(Float, default=100.0)  # 0-100
    source: Mapped[str] = mapped_column(String(64), default="in-situ_sensor")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=UTC)

    pan: Mapped["Pan"] = relationship(back_populates="sensor_readings")


class WeatherReading(Base):
    """One day of forecast (or actual, post-hoc) weather resolution for a pan."""

    __tablename__ = "weather_readings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pan_id: Mapped[Optional[int]] = mapped_column(ForeignKey("pans.id"), nullable=True, index=True)
    forecast_generated_at: Mapped[datetime] = mapped_column(DateTime, default=UTC)
    forecast_for: Mapped[Optional[datetime]] = mapped_column(Date, nullable=True)
    forecast_rain_mm: Mapped[float] = mapped_column(Float, default=0.0)
    rain_probability_pct: Mapped[float] = mapped_column(Float, default=0.0)
    actual_rainfall_mm: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    temperature_c: Mapped[float] = mapped_column(Float, default=0.0)
    humidity_pct: Mapped[float] = mapped_column(Float, default=0.0)
    wind_speed_ms: Mapped[float] = mapped_column(Float, default=0.0)
    solar_radiation_wm2: Mapped[float] = mapped_column(Float, default=0.0)
    cloud_cover_pct: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[str] = mapped_column(String(64), default="mock")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=UTC)

    pan: Mapped[Optional["Pan"]] = relationship(back_populates="weather_readings")


class DigitalTwinState(Base):
    """Time-series rows representing the digital twin of a pan.

    Derived columns (rain / salinity projections) are physical predictions made
    from the latest forecast at `timestamp`; `state_json` keeps the full
    internal state for feature engineering and history.
    """

    __tablename__ = "digital_twin_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pan_id: Mapped[int] = mapped_column(ForeignKey("pans.id"), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=UTC)
    brine_volume_m3: Mapped[float] = mapped_column(Float, default=0.0)
    estimated_salt_mass_kg: Mapped[float] = mapped_column(Float, default=0.0)
    evaporation_mm_day: Mapped[float] = mapped_column(Float, default=0.0)
    predicted_rain_volume_m3: Mapped[float] = mapped_column(Float, default=0.0)
    predicted_depth_after_rain_cm: Mapped[float] = mapped_column(Float, default=0.0)
    predicted_salinity_after_rain_g_l: Mapped[float] = mapped_column(Float, default=0.0)
    harvest_readiness: Mapped[float] = mapped_column(Float, default=0.0)
    climate_risk: Mapped[float] = mapped_column(Float, default=0.0)
    overflow_risk: Mapped[float] = mapped_column(Float, default=0.0)
    state_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=UTC)

    pan: Mapped["Pan"] = relationship(back_populates="twin_states")


class ModelVersion(Base):
    """A trained model artefact (harvest-readiness or climate-risk)."""

    __tablename__ = "model_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    model_type: Mapped[str] = mapped_column(String(64), nullable=False)  # harvest_readiness | climate_risk
    version: Mapped[int] = mapped_column(Integer, default=1)
    model_path: Mapped[str] = mapped_column(String(1024), default="")
    trained_at: Mapped[datetime] = mapped_column(DateTime, default=UTC)
    training_rows: Mapped[int] = mapped_column(Integer, default=0)
    training_start_date: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    training_end_date: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    metrics_json: Mapped[dict] = mapped_column(JSON, default=dict)
    feature_names_json: Mapped[list] = mapped_column(JSON, default=list)
    uses_proxy_labels: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=UTC)

    predictions: Mapped[list["Prediction"]] = relationship(back_populates="model_version")


class Prediction(Base):
    """A scored forecast: readiness + risk probabilities for a pan."""

    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pan_id: Mapped[int] = mapped_column(ForeignKey("pans.id"), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=UTC)
    model_version_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("model_versions.id"), nullable=True)
    risk_level: Mapped[str] = mapped_column(String(16), default="low")  # low | medium | high
    risk_probability: Mapped[float] = mapped_column(Float, default=0.0)
    harvest_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    harvest_probability: Mapped[float] = mapped_column(Float, default=0.0)
    predicted_harvest_hours: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    predicted_yield_kg: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_pct: Mapped[float] = mapped_column(Float, default=0.0)
    input_snapshot_json: Mapped[dict] = mapped_column(JSON, default=dict)
    shap_values_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=UTC)

    pan: Mapped["Pan"] = relationship(back_populates="predictions")
    model_version: Mapped[Optional["ModelVersion"]] = relationship(back_populates="predictions")
    recommendations: Mapped[list["Recommendation"]] = relationship(back_populates="prediction")
    harvest_outcomes: Mapped[list["HarvestOutcome"]] = relationship(back_populates="prediction")


class Recommendation(Base):
    """Operator-facing advice generated from a prediction."""

    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recommendation_code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    pan_id: Mapped[int] = mapped_column(ForeignKey("pans.id"), index=True)
    prediction_id: Mapped[Optional[int]] = mapped_column(ForeignKey("predictions.id"), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=UTC)
    recommended_action: Mapped[str] = mapped_column(String(64), nullable=False)
    action_deadline: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    reason_1: Mapped[str] = mapped_column(Text, default="")
    reason_2: Mapped[str] = mapped_column(Text, default="")
    reason_3: Mapped[str] = mapped_column(Text, default="")
    instruction_1: Mapped[str] = mapped_column(Text, default="")
    instruction_2: Mapped[str] = mapped_column(Text, default="")
    instruction_3: Mapped[str] = mapped_column(Text, default="")
    confidence_pct: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending|accepted|declined|expired
    operator_accepted: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    operator_response_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=UTC)

    pan: Mapped["Pan"] = relationship(back_populates="recommendations")
    prediction: Mapped[Optional["Prediction"]] = relationship(back_populates="recommendations")
    harvest_outcomes: Mapped[list["HarvestOutcome"]] = relationship(back_populates="recommendation")
    operation_events: Mapped[list["OperationEvent"]] = relationship(
        back_populates="recommendation", cascade="all, delete-orphan")


class OperationEvent(Base):
    """Logged field operation (drain, transfer, pump, protection, response)."""

    __tablename__ = "operation_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pan_id: Mapped[int] = mapped_column(ForeignKey("pans.id"), index=True)
    recommendation_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("recommendations.id"), nullable=True)
    event_timestamp: Mapped[datetime] = mapped_column(DateTime, default=UTC)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_pan_id: Mapped[Optional[int]] = mapped_column(ForeignKey("pans.id"), nullable=True)
    destination_pan_id: Mapped[Optional[int]] = mapped_column(ForeignKey("pans.id"), nullable=True)
    transferred_volume_l: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pump_duration_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    drained_volume_l: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    protection_applied: Mapped[bool] = mapped_column(Boolean, default=False)
    operator_notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=UTC)

    pan: Mapped["Pan"] = relationship(back_populates="operation_events",
                                      foreign_keys=[pan_id])
    recommendation: Mapped[Optional["Recommendation"]] = relationship(
        back_populates="operation_events")


class HarvestOutcome(Base):
    """Verified result from the field for a harvested pan / rain event."""

    __tablename__ = "harvest_outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pan_id: Mapped[int] = mapped_column(ForeignKey("pans.id"), index=True)
    recommendation_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("recommendations.id"), nullable=True)
    harvest_date: Mapped[str] = mapped_column(String(32), default="")
    actual_yield_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    salt_purity_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    actual_rainfall_mm: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rain_damage: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    yield_loss_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    outcome_notes: Mapped[str] = mapped_column(Text, default="")
    details_json: Mapped[dict] = mapped_column(JSON, default=dict)
    prediction_id: Mapped[Optional[int]] = mapped_column(ForeignKey("predictions.id"), nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    feedback_ingested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=UTC)

    pan: Mapped["Pan"] = relationship(back_populates="harvest_outcomes")
    prediction: Mapped[Optional["Prediction"]] = relationship(back_populates="harvest_outcomes")
    recommendation: Mapped[Optional["Recommendation"]] = relationship(back_populates="harvest_outcomes")