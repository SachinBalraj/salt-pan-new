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
  Outcome,
  PredictionRecord,
  PredictionRun,
  Recommendation,
  SaltPan,
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
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: init?.body instanceof FormData
      ? undefined
      : { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, String(detail));
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

export const forecastToDays = (f: { days: ForecastDay[] }) => f.days;