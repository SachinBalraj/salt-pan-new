from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ORMModel(BaseModel):
    model_config = {"from_attributes": True}


# ------------------------------------------------------------------ DataSet
class DataSetOut(ORMModel):
    id: int
    name: str
    filename: str
    rows_count: int
    columns: List[str]
    dataset_type: Optional[str] = None
    status: str
    validation_report: Dict[str, Any]
    source: str
    created_at: datetime


class DataSetPreview(BaseModel):
    rows: List[Dict[str, Any]]
    columns: List[str]


# ------------------------------------------------------------------ Phase 3: dataset upload / validation
class DatasetTypeOut(BaseModel):
    key: str
    label: str
    required: List[str]
    optional: List[str]


class ThresholdOut(BaseModel):
    column: str
    min: Optional[float] = None
    max: Optional[float] = None
    outlier_band: Optional[float] = None
    unit: str = ""
    notes: str = ""


class ThresholdsOut(BaseModel):
    meta: Dict[str, Any]
    file: str
    types: Dict[str, DatasetTypeOut]
    aliases: Dict[str, List[str]]
    unit_conversions: Dict[str, List[Dict[str, Any]]]
    thresholds: List[ThresholdOut]


class ColumnMappingOut(BaseModel):
    original: str
    canonical: str
    converted: bool = False


class QualityOut(BaseModel):
    valid_rows: int
    rejected_rows: int
    missing: Dict[str, int]
    outliers: Dict[str, Dict[str, Any]]
    rejected_samples: List[Dict[str, Any]]


class DatasetAnalysisOut(BaseModel):
    file_name: str
    dataset_type: str
    detection_confidence: float
    status: str
    valid_rows: int
    rejected_rows: int
    required_missing: List[str]
    unmapped: List[str]
    mappings: List[ColumnMappingOut]
    renames: Dict[str, Dict[str, Any]]
    conversions: List[Dict[str, Any]]
    duplicates: int
    quality: Dict[str, Any]


class UploadPreviewOut(BaseModel):
    file_name: str
    dataset_type: str
    detection_confidence: float
    required: List[str]
    missing: List[str]
    extra: List[str]
    mappings: List[ColumnMappingOut]
    renames: Dict[str, Dict[str, Any]]
    conversions: List[Dict[str, Any]]
    duplicates: int
    sample_rows: List[Dict[str, Any]]
    errors: List[str]
    warnings: List[str]


class UploadOut(BaseModel):
    dataset: DataSetOut
    analysis: DatasetAnalysisOut


class ImportOut(BaseModel):
    dataset: DataSetOut
    summary: Dict[str, Any]


# ------------------------------------------------------------------ SaltPan / Twin
class PanCreate(BaseModel):
    pan_id: str = Field(..., description="Unique identifier of the salt pan")
    name: str
    location: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    area_m2: float = 1000.0
    twin_state: Optional[Dict[str, Any]] = None


class PanUpdate(BaseModel):
    name: Optional[str] = None
    location: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    area_m2: Optional[float] = None
    twin_state: Optional[Dict[str, Any]] = None


class PanOut(ORMModel):
    id: int
    pan_id: str
    name: str
    location: str
    latitude: Optional[float]
    longitude: Optional[float]
    area_m2: float
    status: str
    twin_state: Dict[str, Any]
    created_at: datetime
    updated_at: datetime


class TwinSnapshotOut(ORMModel):
    id: int
    pan_id: int
    snapshot_date: str
    source: str
    state: Dict[str, Any]
    created_at: datetime


class TwinUpdateRequest(BaseModel):
    state: Dict[str, Any] = Field(..., description="New ping of the digital twin state")
    source: str = "manual"


# ------------------------------------------------------------------ ML models
class TrainRequest(BaseModel):
    kind: str = Field(..., description="harvest_readiness | climate_risk | all")
    dataset_id: Optional[int] = None


class ModelOut(ORMModel):
    id: int
    name: str
    kind: str
    version: int
    status: str
    feature_names: List[str]
    metrics: Dict[str, Any]
    rows_trained: int
    dataset_id: Optional[int]
    created_at: datetime


# ------------------------------------------------------------------ Weather
class ForecastDay(BaseModel):
    date: str
    temperature_c: float
    humidity_pct: float
    wind_speed_kmh: float
    rainfall_mm: float
    precipitation_probability_pct: float
    sunshine_hours: float


class WeatherForecastOut(BaseModel):
    id: int
    pan_id: Optional[int]
    source: str
    generated_at: datetime
    days: List[ForecastDay]


# ------------------------------------------------------------------ Predictions / Simulation
class PredictRequest(BaseModel):
    pan_id: int
    horizon_days: int = Field(7, ge=1, le=30)
    scenario: str = "actual_forecast"  # actual_forecast | rain_simulation


class RainScenario(BaseModel):
    rainfall_mm: float = Field(..., gt=0, description="Simulated rain event size (mm)")
    day_offset: int = Field(1, ge=0, le=14, description="Which forecast day gets the rain")
    dry_days_after: int = Field(3, ge=0, le=14, description="Dry days after the rain event")


class SimulationRequest(BaseModel):
    pan_id: int
    scenario: RainScenario
    horizon_days: int = Field(7, ge=1, le=30)


class SeriesPoint(BaseModel):
    date: str
    label: str
    temperature_c: float
    rainfall_mm: float
    humidity_pct: float
    wind_speed_kmh: float
    brine_density_be: float
    salt_thickness_mm: float
    water_depth_cm: float
    days_since_last_rain: float
    readiness: float
    risk: float


class SimulationResult(BaseModel):
    pan_id: int
    scenario_name: str
    baseline: List[SeriesPoint]
    rain_scenario: List[SeriesPoint]
    impact: Dict[str, Any]


# ------------------------------------------------------------------ Recommendations
class RecommendationOut(ORMModel):
    id: int
    pan_id: int
    prediction_id: Optional[int]
    recommendation_type: str
    title: str
    message: str
    rationale: str
    expected_benefit: str
    risk_level: str
    status: str
    farmer_notes: str
    created_at: datetime
    responded_at: Optional[datetime]


class RespondRequest(BaseModel):
    status: str = Field(..., description="accepted | declined")
    farmer_notes: str = ""


# ------------------------------------------------------------------ Outcomes
class OutcomeCreate(BaseModel):
    pan_id: int
    prediction_id: Optional[int] = None
    recommendation_id: Optional[int] = None
    outcome_date: str = ""
    actual_rainfall_mm: float = 0.0
    risk_occurred: Optional[bool] = None
    action_taken: str = ""
    harvest_date: Optional[str] = None
    actual_yield_kg: Optional[float] = None
    brine_density_be: Optional[float] = None
    salt_thickness_mm: Optional[float] = None
    notes: str = ""


class OutcomeOut(ORMModel):
    id: int
    pan_id: int
    prediction_id: Optional[int]
    recommendation_id: Optional[int]
    outcome_date: str
    actual_rainfall_mm: float
    risk_occurred: bool
    action_taken: str
    harvest_date: Optional[str]
    harvest_delayed_days: Optional[int]
    actual_yield_kg: Optional[float]
    brine_density_be: Optional[float]
    salt_thickness_mm: Optional[float]
    verified: bool
    verified_at: Optional[datetime]
    notes: str
    feedback_ingested: bool
    created_at: datetime


# ------------------------------------------------------------------ Evaluation
class ComparisonRow(BaseModel):
    outcome_id: int
    pan_id: int
    pan_ref: str
    prediction_id: Optional[int]
    prediction_type: str
    prediction_date: str
    prediction_score: float
    outcome_date: str
    actual_rainfall_mm: float
    risk_occurred: bool
    action_taken: str
    actual_yield_kg: Optional[float]
    projected_yield_kg: Optional[float]
    hit: str
    error: Optional[float]
    verified: bool


class EvaluationSummary(BaseModel):
    total_outcomes: int
    verified_outcomes: int
    risk_accuracy: Optional[float]
    risk_tp: int
    risk_tn: int
    risk_fp: int
    risk_fn: int
    readiness_mae: Optional[float]
    yield_mae_kg: Optional[float]
    harvest_delay_mean_days: Optional[float]
    recommendations: Dict[str, int]
    by_prediction_type: Dict[str, int]


class FeedbackResult(BaseModel):
    ingested: bool
    outcome_ids: List[int]
    twin_updated: List[int]
    training_rows_added: int
    feedback_dataset_id: Optional[int]
    models_pending_retrain: bool