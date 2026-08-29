from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


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


class DigitalTwinOut(BaseModel):
    """Full operational digital-twin snapshot for one salt pan."""

    pan_id: int
    pan_ref: str
    timestamp: str
    last_update: str
    source: str
    forecast_source: str
    salinity_g_l: float
    water_depth_cm: float
    brine_temperature_c: float
    brine_volume_m3: float
    estimated_salt_mass_kg: float
    forecast_rainfall_mm: float
    forecast_rainfall_7d_mm: float
    rain_probability_pct: float
    predicted_depth_after_rain_cm: float
    predicted_salinity_after_rain_g_l: float
    evaporation_mm_day: float
    harvest_readiness: float
    climate_risk: float
    overflow_risk: float
    last_operation: Optional[Dict[str, Any]] = None
    demo_today: Optional[str] = None
    state: Dict[str, Any]


class SensorReadingCreate(BaseModel):
    """Telemetry payload from an in-situ sensor board (validated on ingest)."""

    pan_id: Optional[int] = Field(None, description="Numeric pan DB id (or pan_code)")
    pan_code: Optional[str] = Field(None, description="Pan reference, e.g. PAN-1 (or pan_id)")
    salinity_g_l: float = Field(..., ge=0.0, le=350.0, description="Brine salinity in g/L")
    ec_ms_cm: Optional[float] = Field(None, ge=0.0, le=300.0)
    water_depth_cm: float = Field(..., ge=0.0, le=500.0, description="Brine water depth in cm")
    brine_temperature_c: Optional[float] = Field(None, ge=-5.0, le=60.0)
    air_temperature_c: Optional[float] = Field(None, ge=-20.0, le=55.0)
    humidity_pct: Optional[float] = Field(None, ge=0.0, le=100.0)
    sensor_quality: Optional[float] = Field(None, ge=0.0, le=100.0)
    recorded_at: Optional[str] = Field(None, description="ISO-8601 timestamp (defaults to now)")

    @model_validator(mode="after")
    def _check_pan_reference(self):
        if self.pan_id is None and not self.pan_code:
            raise ValueError("Provide pan_id or pan_code to route the reading")
        return self


class SensorIngestOut(BaseModel):
    reading_id: int
    pan_id: int
    pan_ref: str
    status: str
    digital_twin: DigitalTwinOut
    prediction: Optional[Dict[str, Any]] = None
    recommendations: List[Dict[str, Any]] = []
    active_model: bool = False


# ------------------------------------------------------------------ ML models
class TrainRequest(BaseModel):
    kind: str = Field(...,
                      description=("harvest_readiness | climate_risk | climate_risk_classifier | "
                                   "harvest_readiness_classifier | harvest_time_regressor | all"))
    dataset_id: Optional[int] = None


class ModelOut(ORMModel):
    id: int
    name: str
    kind: str
    version: int
    status: str  # active | trained | deferred
    feature_names: List[str]
    metrics: Dict[str, Any]
    rows_trained: int
    test_rows: int = 0
    algorithm: str = ""
    target: str = ""
    split: Dict[str, Any] = {}
    training_errors: List[str] = []
    classes: Optional[List[str]] = None
    confusion_matrix: Optional[List[List[int]]] = None
    class_distribution: Optional[Dict[str, Dict[str, int]]] = None
    dataset_id: Optional[int]
    dataset_used: Optional[str] = None
    model_path: str = ""
    uses_proxy_labels: bool = True
    is_active: bool = False
    created_at: datetime


class LabelStatusOut(BaseModel):
    banner: str
    subtext: str
    any_active_proxy: bool
    models: Dict[str, bool]
    config_file: str
    methodology_file: str


# ------------------------------------------------------------------ Weather
class ForecastDay(BaseModel):
    date: str
    temperature_c: float
    humidity_pct: float
    wind_speed_kmh: float
    rainfall_mm: float
    precipitation_probability_pct: float
    sunshine_hours: float
    forecast_rain_mm: float = 0.0
    actual_rainfall_mm: Optional[float] = None
    id: Optional[int] = None


class WeatherForecastOut(BaseModel):
    id: int
    pan_id: Optional[int]
    source: str
    generated_at: datetime
    days: List[ForecastDay]


class WeatherActualRequest(BaseModel):
    pan_id: int
    date: str = Field(..., description="YYYY-MM-DD the forecast was for")
    actual_rainfall_mm: float = Field(..., ge=0.0, le=1000.0,
                                      description="Observed rainfall for that day")


class WeatherActualOut(BaseModel):
    pan_id: int
    date: str
    forecast_rain_mm: float
    actual_rainfall_mm: float
    source: str
    updated_at: str


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


class SimulateRainRequest(BaseModel):
    """Question asked of the Phase-9 what-if simulator."""

    rainfall_mm: float = Field(..., gt=0, le=300,
                               description="Rain event size in mm to simulate")


class SimulateRainOut(BaseModel):
    """Before/after snapshot of a single rain event on one salt pan."""

    pan_id: str
    current_salinity_g_l: float
    current_depth_cm: float
    current_volume_m3: float
    rainfall_mm: float
    rain_volume_m3: float
    predicted_depth_after_rain_cm: float
    predicted_salinity_after_rain_g_l: float
    risk_before: str  # LOW | MEDIUM | HIGH
    risk_after: str   # LOW | MEDIUM | HIGH
    predicted_harvest_delay_hours: float
    recommended_action: str
    recommendation: str


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
    action_deadline: Optional[datetime] = None
    confidence_pct: float = 0.0
    reasons: List[str] = []
    instructions: List[str] = []
    consequence_if_waited: str = ""


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
    proxy_labels_in_use: bool = False
    proxy_note: str = ""


class FeedbackResult(BaseModel):
    ingested: bool
    outcome_ids: List[int]
    twin_updated: List[int]
    training_rows_added: int
    feedback_dataset_id: Optional[int]
    models_pending_retrain: bool