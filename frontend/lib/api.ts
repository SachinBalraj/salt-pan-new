import type {
  ComparisonRow,
  DataSet,
  DatasetAnalysis,
  DigitalTwinOut,
  EvaluationSummary,
  FeedbackResult,
  ForecastDay,
  ImportResult,
  LabelStatus,
  MlModel,
  OperationEvent,
  Outcome,
  PredictionRecord,
  PredictionRun,
  Recommendation,
  RetrainResult,
  SaltPan,
  SensorReading,
  SimulateRainOut,
  SimulationResult,
  SystemStatus,
  Thresholds,
  UploadPreview,
  WeatherForecastOut,
} from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  detail?: string;
  constructor(status: number, message: string, detail?: string) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

/**
 * Maps HTTP status codes to human-readable messages so the user never sees
 * raw "Internal Server Error" or cryptic 4xx codes.
 */
function friendlyErrorMessage(status: number, raw: string): string {
  if (status === 413) return "The file is too large. Please split it into smaller files and try again.";
  if (status === 415) return "Unsupported file type. Please upload a CSV or TSV file.";
  if (status === 400) return raw || "The request was invalid. Check your input and try again.";
  if (status === 401 || status === 403) return "You do not have permission to perform this action.";
  if (status === 404) return "The requested resource was not found.";
  if (status === 409) return raw || "This action conflicts with the current state. Refresh and try again.";
  if (status === 422) return "Some values in your request were not valid. Please review and fix them.";
  if (status === 500) return raw || "The server encountered an error. Please try again later.";
  if (status === 502 || status === 503) return "The server is temporarily unavailable. Please try again in a moment.";
  if (status === 504) return "The request timed out. The server may be under heavy load.";
  if (status === 0) return "Could not connect to the server. Check your network connection.";
  return raw || `An unexpected error occurred (HTTP ${status}).`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      headers: init?.body instanceof FormData
        ? undefined
        : { "Content-Type": "application/json", ...(init?.headers ?? {}) },
      ...init,
    });
  } catch (err) {
    // Network error — server unreachable
    throw new ApiError(0, friendlyErrorMessage(0, ""), "Could not connect to the API server.");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? body.message ?? detail;
    } catch {
      /* keep statusText */
    }
    const friendly = friendlyErrorMessage(res.status, String(detail));
    throw new ApiError(res.status, friendly, String(detail));
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const get = <T>(path: string) => request<T>(path);
const post = <T>(path: string, body?: unknown, init?: RequestInit) =>
  request<T>(path, {
    method: "POST",
    ...(body !== undefined
      ? { body: body instanceof FormData ? body : JSON.stringify(body) }
      : {}),
    ...init,
  });

export const api = {
  get,
  post,

  // ---- system
  status: () => get<SystemStatus>("/api/system/status"),
  health: () => get<{ status: string }>("/api/health"),

  // ---- datasets
  datasets: () => get<DataSet[]>("/api/datasets"),
  datasetThresholds: () => get<Thresholds>("/api/datasets/thresholds"),
  datasetPreview: (id: number, n = 10, stage = "raw") =>
    get<{ columns: string[]; rows: Record<string, unknown>[] }>(
      `/api/datasets/${id}/preview?n=${n}&stage=${stage}`,
    ),
  datasetAnalysis: (id: number) =>
    get<DatasetAnalysis>(`/api/datasets/${id}/analysis`),
  previewUpload: (
    file: File,
    opts: { dataset_type?: string; field_mapping?: Record<string, string> } = {},
  ) => {
    const fd = new FormData();
    fd.append("file", file);
    if (opts.dataset_type) fd.append("dataset_type", opts.dataset_type);
    if (opts.field_mapping) fd.append("field_mapping", JSON.stringify(opts.field_mapping));
    return post<UploadPreview>("/api/datasets/preview", fd);
  },
  uploadDataset: (
    file: File,
    opts: { dataset_type?: string; field_mapping?: Record<string, string> } = {},
  ) => {
    const fd = new FormData();
    fd.append("file", file);
    if (opts.dataset_type) fd.append("dataset_type", opts.dataset_type);
    if (opts.field_mapping) fd.append("field_mapping", JSON.stringify(opts.field_mapping));
    return post<DataSet>("/api/datasets/upload", fd);
  },
  validateDataset: (id: number) => post<DataSet>(`/api/datasets/${id}/validate`),
  promoteDataset: (id: number) => post<DataSet>(`/api/datasets/${id}/promote`),
  importDataset: (id: number) => post<ImportResult>(`/api/datasets/${id}/import`),
  invalidRowsUrl: (id: number) => `${API_BASE}/api/datasets/${id}/invalid_rows`,

  // ---- pans
  pans: () => get<SaltPan[]>("/api/pans"),
  createPan: (body: Record<string, unknown>) => post<SaltPan>("/api/pans", body),
  panTwin: (id: number) =>
    get<{ pan: SaltPan; state: SaltPan["twin_state"]; progress_to_harvest: number }>(
      `/api/pans/${id}/twin`,
    ),
  updateTwin: (id: number, state: Record<string, unknown>, source = "manual") =>
    post<SaltPan>(`/api/pans/${id}/twin`, { state, source }),
  digitalTwin: (id: number) => get<DigitalTwinOut>(`/api/pans/${id}/digital-twin`),
  panSensors: (id: number) => get<SensorReading[]>(`/api/pans/${id}/sensors`),
  panOperations: (id: number) =>
    get<OperationEvent[]>(`/api/pans/${id}/operations`),

  // ---- models
  models: () => get<MlModel[]>("/api/models"),
  modelLatest: () => get<MlModel[]>("/api/models/latest"),
  modelLabelStatus: () => get<LabelStatus>("/api/models/label-status"),
  train: (body: { kind: string; dataset_id?: number | null }) =>
    post<MlModel[]>("/api/models/train", body),
  activateModel: (id: number) =>
    post<MlModel>(`/api/models/${id}/activate`),
  modelShap: (id: number) =>
    get<{ model_id: number; kind: string; shap_importance: { feature: string; importance: number }[] }>(
      `/api/models/${id}/shap`,
    ),

  // ---- weather
  forecast: (panId: number | null, days = 7, scenario = "auto", force = false) =>
    get<WeatherForecastOut>(
      `/api/weather/forecast?pan_id=${panId ?? ""}&days=${days}&scenario=${scenario}&force_refresh=${force}`,
    ),

  // ---- predictions
  runPrediction: (panId: number, horizon = 7, scenario = "actual_forecast") =>
    post<PredictionRun>("/api/predictions/run", {
      pan_id: panId,
      horizon_days: horizon,
      scenario,
    }),
  predictions: (panId?: number) =>
    get<PredictionRecord[]>(`/api/predictions?pan_id=${panId ?? ""}`),

  // ---- simulations
  simulateRain: (body: {
    pan_id: number;
    horizon_days: number;
    scenario: { rainfall_mm: number; day_offset: number; dry_days_after: number };
  }) => post<SimulationResult>("/api/simulations/what-if-rain", body),
  simulatePanRain: (panId: number, rainfallMm: number) =>
    post<SimulateRainOut>(`/api/pans/${panId}/simulate-rain`, { rainfall_mm: rainfallMm }),

  // ---- recommendations
  recommendations: (panId?: number, status?: string) =>
    get<Recommendation[]>(
      `/api/recommendations?pan_id=${panId ?? ""}&status=${status ?? ""}`,
    ),
  generateRecommendations: (panId: number) =>
    post<Recommendation[]>(`/api/recommendations/generate?pan_id=${panId}`),
  respondRecommendation: (
    id: number,
    body: { status: "accepted" | "declined"; farmer_notes: string },
  ) => post<Recommendation>(`/api/recommendations/${id}/respond`, body),
  completeRecommendation: (id: number) =>
    post<Recommendation>(`/api/recommendations/${id}/complete`),

  // ---- outcomes
  outcomes: (panId?: number) =>
    get<Outcome[]>(`/api/outcomes?pan_id=${panId ?? ""}`),
  createOutcome: (body: Record<string, unknown>) =>
    post<Outcome>("/api/outcomes", body),
  verifyOutcome: (id: number) => post<Outcome>(`/api/outcomes/${id}/verify`),

  // ---- evaluation
  comparison: () => get<ComparisonRow[]>("/api/evaluation/comparison"),
  evaluationSummary: () => get<EvaluationSummary>("/api/evaluation/summary"),
  ingestFeedback: (outcomeIds?: number[]) =>
    post<FeedbackResult>(
      `/api/evaluation/feedback?outcome_ids=${(outcomeIds ?? []).join(",")}`,
    ),
  retrainWithFeedback: () => post<RetrainResult>("/api/evaluation/retrain"),
};

export const fmt = {
  kg(n?: number | null): string {
    if (n === null || n === undefined) return "—";
    return Number(n).toLocaleString("en-IN", { maximumFractionDigits: 0 });
  },
  mm(n?: number | null): string {
    if (n === null || n === undefined) return "—";
    return `${Number(n).toFixed(1)} mm`;
  },
  be(n?: number | null): string {
    if (n === null || n === undefined) return "—";
    return `${Number(n).toFixed(1)} °Bé`;
  },
  cm(n?: number | null): string {
    if (n === null || n === undefined) return "—";
    return `${Number(n).toFixed(1)} cm`;
  },
  pct(n?: number | null): string {
    if (n === null || n === undefined) return "—";
    return `${Math.round(Number(n) * 100)}%`;
  },
  temp(n?: number): string {
    return `${Number(n ?? 0).toFixed(1)} °C`;
  },
  date(s?: string | null): string {
    if (!s) return "—";
    return new Date(s).toLocaleDateString("en-IN", {
      day: "2-digit",
      month: "short",
      year: "numeric",
    });
  },
  lit(n?: number | null): string {
    if (n === null || n === undefined) return "—";
    return `${Number(n).toLocaleString("en-IN", { maximumFractionDigits: 0 })} L`;
  },
  hours(n?: number | null): string {
    if (n === null || n === undefined) return "—";
    return `${Number(n).toFixed(0)} min`;
  },
};

export const severityColor = (level: string) =>
  level === "high"
    ? "bg-red-500/15 text-red-300 border-red-500/40"
    : level === "medium" || level === "accepted"
      ? "bg-amber-500/15 text-amber-300 border-amber-500/40"
      : level === "low"
        ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/40"
        : "bg-sky-500/15 text-sky-300 border-sky-500/40";

export const riskTone = (score: number) =>
  score >= 0.65
    ? { text: "text-red-400", bar: "bg-red-500" }
    : score >= 0.4
      ? { text: "text-amber-300", bar: "bg-amber-400" }
      : { text: "text-emerald-400", bar: "bg-emerald-500" };

export const readinessTone = (score: number) =>
  score >= 0.7
    ? { text: "text-emerald-400", bar: "bg-emerald-500" }
    : score >= 0.45
      ? { text: "text-amber-300", bar: "bg-amber-400" }
      : { text: "text-sky-400", bar: "bg-sky-500" };

export const recStatusTone = (status: string) =>
  status === "accepted"
    ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-300"
    : status === "declined" || status === "rejected"
      ? "border-slate-400/40 bg-slate-500/15 text-slate-300"
      : status === "completed"
        ? "border-brine-500/40 bg-brine-500/15 text-brine-300"
        : status === "expired"
          ? "border-zinc-500/40 bg-zinc-500/15 text-zinc-300"
          : "border-amber-500/40 bg-amber-500/15 text-amber-300";

export const forecastToDays = (f: { days: ForecastDay[] }) => f.days;