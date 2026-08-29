export interface SystemStatus {
  seeded: boolean;
  pans: number;
  models: number;
  model_kinds: Record<
    string,
    {
      available: boolean;
      id: number | null;
      version: number | null;
      metrics: ModelMetrics;
      rows_trained: number;
      uses_proxy_labels: boolean;
    }
  >;
  datasets: number;
  predictions: number;
  recommendations: number;
  outcomes: number;
  training_pool_file: string;
  feedback_pool_file: string;
}

export interface DataSet {
  id: number;
  name: string;
  filename: string;
  rows_count: number;
  columns: string[];
  dataset_type?: string | null;
  status: string;
  validation_report: {
    valid?: boolean;
    rows?: number;
    columns?: string[];
    errors?: string[];
    warnings?: string[];
    missing?: Record<string, number>;
    note?: string;
    date_range?: string[];
    promoted_to?: string;
  };
  source: string;
  created_at: string;
}

export interface ColumnMapping {
  original: string;
  canonical: string;
  converted?: boolean;
}

export interface DatasetAnalysis {
  file_name: string;
  dataset_type: string;
  detection_confidence: number;
  status: "valid" | "needs_review" | "invalid";
  valid_rows: number;
  rejected_rows: number;
  required_missing: string[];
  unmapped: string[];
  mappings: ColumnMapping[];
  renames: Record<string, { to: string; why: string }>;
  conversions: { column: string; note: string; from_unit: string; factor: number }[];
  duplicates: number;
  quality: {
    missing: Record<string, number>;
    out_of_range: Record<string, { min: number; max: number; count: number; rows: number[] }>;
    outliers: Record<string, { count: number; band: number; break_low: number; break_high: number; rows: number[]; q1: number; q3: number }>;
    non_numeric: Record<string, number>;
    valid_sample: Record<string, unknown>[];
  };
}

export interface UploadPreview {
  file_name: string;
  dataset_type: string;
  detection_confidence: number;
  required: string[];
  missing: string[];
  extra: string[];
  mappings: ColumnMapping[];
  renames: Record<string, { to: string; why: string }>;
  conversions: { column: string; note: string; from_unit: string }[];
  duplicates: number;
  sample_rows: Record<string, unknown>[];
  errors: string[];
  warnings: string[];
}

export interface ThresholdRow {
  column: string;
  min?: number | null;
  max?: number | null;
  outlier_band?: number | null;
  unit: string;
  notes: string;
}

export interface Thresholds {
  meta: { status: string; version: number; note: string };
  file: string;
  types: Record<string, { key: string; label: string; required: string[]; optional: string[] }>;
  aliases: Record<string, string[]>;
  unit_conversions: Record<string, { matches: string[]; factor: number; from_unit: string; note: string }[]>;
  thresholds: ThresholdRow[];
}

export interface ImportResult {
  dataset: DataSet;
  summary: {
    dataset_type: string;
    imported_rows: number;
    tables: string[];
    created_pans: string[];
  };
}

export interface SaltPan {
  id: number;
  pan_id: string;
  name: string;
  location: string;
  latitude: number | null;
  longitude: number | null;
  area_m2: number;
  status: string;
  twin_state: TwinState;
  created_at: string;
  updated_at: string;
}

export interface TwinState {
  water_depth_cm?: number;
  brine_density_be?: number;
  salt_thickness_mm?: number;
  days_since_last_rain?: number;
  last_rain_date?: string | null;
  last_harvest_date?: string | null;
  estimated_salt_mass_kg?: number;
  demo_today?: string;
  last_update?: string;
  [key: string]: unknown;
}

export interface ModelMetrics {
  rmse?: number;
  mae?: number;
  r2?: number;
  accuracy?: number;
  precision?: number;
  recall?: number;
  f1?: number;
  threshold?: number;
}

export interface MlModel {
  id: number;
  name: string;
  kind: string;
  version: number;
  status: string;
  feature_names: string[];
  metrics: ModelMetrics;
  rows_trained: number;
  dataset_id: number | null;
  uses_proxy_labels?: boolean;
  created_at: string;
}

export interface LabelStatus {
  banner: string;
  subtext: string;
  any_active_proxy: boolean;
  models: Record<string, boolean>;
  config_file: string;
  methodology_file: string;
}

export interface ForecastDay {
  date: string;
  temperature_c: number;
  humidity_pct: number;
  wind_speed_kmh: number;
  rainfall_mm: number;
  precipitation_probability_pct: number;
  sunshine_hours: number;
}

export interface SeriesPoint {
  date: string;
  label: string;
  temperature_c: number;
  rainfall_mm: number;
  humidity_pct: number;
  wind_speed_kmh: number;
  sunshine_hours: number;
  precipitation_probability_pct: number;
  brine_density_be: number;
  salt_thickness_mm: number;
  water_depth_cm: number;
  days_since_last_rain: number;
  readiness: number;
  risk: number;
}

export interface PredictionRun {
  id: number;
  pan_id: number;
  pan_ref: string;
  state: TwinState;
  day0: SeriesPoint;
  max_risk: number;
  min_readiness: number;
  projected_yield_kg: number;
  shap: Record<string, Record<string, number>>;
  series: SeriesPoint[];
  created_at: string;
  scenario: string;
}

export interface PredictionRecord {
  id: number;
  pan_id: number;
  model_id: number | null;
  prediction_type: string;
  scenario: string;
  score: number;
  horizon_days: number;
  prediction_date: string;
  forecast_date: string;
  features: Record<string, unknown>;
  shap_values: Record<string, Record<string, number>>;
  series: SeriesPoint[];
  created_at: string;
}

export interface SimulationImpact {
  rainfall_mm: number;
  rain_day: string;
  readiness_drop_on_day: number;
  max_risk_baseline: number;
  max_risk_after_rain: number;
  risk_increase: number;
  brine_density_drop_be: number;
  salt_thickness_loss_mm: number;
  projected_yield_loss_kg: number;
  days_setback_estimate: number;
  readiness_before: number;
  readiness_after: number;
  event_date: string;
  risk_critical: boolean;
}

export interface SimulationResult {
  pan_id: number;
  pan_ref: string;
  scenario_name: string;
  forecast_source: string;
  baseline: SeriesPoint[];
  rain_scenario: SeriesPoint[];
  impact: SimulationImpact;
}

export interface Recommendation {
  id: number;
  pan_id: number;
  prediction_id: number | null;
  recommendation_type: string;
  title: string;
  message: string;
  rationale: string;
  expected_benefit: string;
  risk_level: string;
  status: string;
  farmer_notes: string;
  created_at: string;
  responded_at: string | null;
}

export interface Outcome {
  id: number;
  pan_id: number;
  prediction_id: number | null;
  recommendation_id: number | null;
  outcome_date: string;
  actual_rainfall_mm: number;
  risk_occurred: boolean;
  action_taken: string;
  harvest_date: string | null;
  harvest_delayed_days: number | null;
  actual_yield_kg: number | null;
  brine_density_be: number | null;
  salt_thickness_mm: number | null;
  verified: boolean;
  verified_at: string | null;
  notes: string;
  feedback_ingested: boolean;
  created_at: string;
}

export interface ComparisonRow {
  outcome_id: number;
  pan_id: number;
  pan_ref: string;
  prediction_id: number | null;
  prediction_type: string;
  prediction_date: string;
  prediction_score: number | null;
  outcome_date: string;
  actual_rainfall_mm: number;
  risk_occurred: boolean;
  action_taken: string;
  actual_yield_kg: number | null;
  projected_yield_kg: number | null;
  hit: string;
  error: number | null;
  verified: boolean;
}

export interface EvaluationSummary {
  total_outcomes: number;
  verified_outcomes: number;
  risk_accuracy: number | null;
  risk_tp: number;
  risk_tn: number;
  risk_fp: number;
  risk_fn: number;
  readiness_mae: number | null;
  yield_mae_kg: number | null;
  harvest_delay_mean_days: number | null;
  recommendations: Record<string, number>;
  by_prediction_type: Record<string, number>;
  proxy_labels_in_use?: boolean;
  proxy_note?: string;
}

export interface FeedbackResult {
  ingested: boolean;
  outcome_ids: number[];
  twin_updated: number[];
  training_rows_added: number;
  feedback_dataset_id: number | null;
  models_pending_retrain: boolean;
}

export interface WeatherForecastOut {
  id: number;
  pan_id: number | null;
  source: string;
  generated_at: string;
  days: ForecastDay[];
}