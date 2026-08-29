"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "@/lib/api";
import type { MlModel } from "@/lib/types";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  inputCls,
  Spinner,
} from "@/components/ui";
import { useDatasets } from "./common";

const KIND_OPTIONS: { value: string; label: string }[] = [
  { value: "all", label: "All five models" },
  { value: "harvest_readiness", label: "Harvest readiness (regressor)" },
  { value: "climate_risk", label: "Climate risk (regressor)" },
  { value: "climate_risk_classifier", label: "Climate risk classifier" },
  { value: "harvest_readiness_classifier", label: "Harvest readiness classifier" },
  { value: "harvest_time_regressor", label: "Harvest time regressor" },
];

function ProxyNotice() {
  const { data: status } = useQuery({
    queryKey: ["label-status"],
    queryFn: api.modelLabelStatus,
  });
  if (!status || !status.any_active_proxy) return null;
  return (
    <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3">
      <p className="text-sm font-bold tracking-wide text-amber-200">
        PROXY/SIMULATED MODEL — NOT YET FIELD VALIDATED
      </p>
      <p className="mt-1 text-xs text-amber-200/70">{status.subtext}</p>
      <p className="mt-1 break-all text-[10px] text-amber-200/50">
        Active rule file: {status.config_file}
      </p>
    </div>
  );
}

function Metric({ label, value }: { label: string; value?: unknown }) {
  if (value === undefined || value === null) return null;
  return (
    <div className="rounded-lg border border-white/10 bg-white/5 px-3 py-2">
      <p className="text-[10px] uppercase tracking-wider text-slate-500">{label}</p>
      <p className="text-sm font-semibold tabular-nums text-slate-200">
        {typeof value === "number" ? value.toFixed(4) : String(value)}
      </p>
    </div>
  );
}

function ModelDetail({
  model,
  onShowShap,
}: {
  model: MlModel;
  onShowShap: (id: number) => void;
}) {
  const [showFeatures, setShowFeatures] = useState(false);
  const metrics = model.metrics ?? {};
  const split = model.split ?? {};
  const dates = split.train_dates?.filter(Boolean);
  return (
    <div className="mt-4 space-y-4 rounded-xl border border-brine-500/20 bg-brine-500/5 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-bold text-slate-100">
            {model.name}{" "}
            <span className="font-normal text-slate-400">· {model.algorithm}</span>
          </p>
          <p className="mt-0.5 text-xs text-slate-400">
            Target: <span className="font-mono text-slate-300">{model.target || "—"}</span>
            {" · "}
            Dataset: {model.dataset_used ?? `#${model.dataset_id ?? "—"}`}
            {" · "}
            v{model.version}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {model.is_active && (
            <Badge className="border-emerald-500/40 bg-emerald-500/15 text-emerald-300">
              ACTIVE
            </Badge>
          )}
          {model.uses_proxy_labels === false ? (
            <Badge className="border-emerald-500/40 bg-emerald-500/15 text-emerald-300"
                   title="Trained on real field measurements">
              FIELD LABELS
            </Badge>
          ) : (
            <Badge className="border-amber-500/40 bg-amber-500/15 text-amber-300"
                   title="Trained on proxy/simulated labels — not field validated">
              PROXY LABELS
            </Badge>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Metric label="Training rows" value={model.rows_trained} />
        <Metric label="Test rows" value={model.test_rows} />
        <Metric label="Date range" value={(dates ?? []).join(" → ") || (split.dataset_range ?? [""]).join(" → ")} />
        <Metric label="Split" value={split.split_type} />
      </div>

      {model.training_errors.length > 0 && (
        <div className="rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2">
          <p className="text-xs font-bold text-red-300">Training errors</p>
          {model.training_errors.map((e) => (
            <p key={e} className="text-xs text-red-200/80">{e}</p>
          ))}
        </div>
      )}

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        <Metric label="MAE" value={metrics.mae} />
        <Metric label="RMSE" value={metrics.rmse} />
        <Metric label="R²" value={metrics.r2} />
        <Metric label="Accuracy" value={metrics.accuracy} />
        <Metric label="Macro F1" value={metrics.f1} />
      </div>

      {model.class_distribution && (
        <div className="overflow-x-auto rounded-lg border border-white/10">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-white/10 text-[10px] uppercase tracking-wider text-slate-500">
                <th className="px-3 py-1.5">Class</th>
                <th className="px-3 py-1.5">Train</th>
                <th className="px-3 py-1.5">Test</th>
                <th className="px-3 py-1.5">Predicted</th>
                <th className="px-3 py-1.5">Confusion</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(model.class_distribution).map(([cls, d]) => (
                <tr key={cls} className="border-b border-white/5">
                  <td className="px-3 py-1.5 font-mono text-slate-300">{cls}</td>
                  <td className="px-3 py-1.5 tabular-nums text-slate-400">{d.train}</td>
                  <td className="px-3 py-1.5 tabular-nums text-slate-400">{d.test}</td>
                  <td className="px-3 py-1.5 tabular-nums text-slate-400">{d.predicted_test}</td>
                  <td className="px-3 py-1.5 font-mono text-[11px] text-slate-500">
                    {model.confusion_matrix
                      ?.map((row) => row.join(" "))
                      .join(" / ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Button variant="ghost" onClick={() => setShowFeatures((v) => !v)}>
          {showFeatures ? "Hide features" : "Show features"}
        </Button>
        {["harvest_readiness", "climate_risk"].includes(model.kind) && (
          <Button variant="ghost" onClick={() => onShowShap(model.id)}>
            Explain (SHAP)
          </Button>
        )}
      </div>
      {showFeatures && (
        <div className="max-h-40 overflow-y-auto rounded-lg border border-white/10 bg-white/5 p-3">
          <code className="font-mono text-[11px] leading-relaxed text-slate-300">
            {model.feature_names.join(", ")}
          </code>
        </div>
      )}
    </div>
  );
}

export default function ModelsPanel() {
  const qc = useQueryClient();
  const { data: models, isLoading, refetch } = useQuery({
    queryKey: ["models"],
    queryFn: api.models,
  });
  const { data: latest } = useQuery({
    queryKey: ["models-latest"],
    queryFn: api.modelLatest,
  });
  const { data: datasets } = useDatasets();

  const [kind, setKind] = useState("all");
  const [datasetId, setDatasetId] = useState("");
  const [shapFor, setShapFor] = useState<number | null>(null);
  const [detail, setDetail] = useState<number | null>(null);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const training = useMutation({
    mutationFn: () =>
      api.train({
        kind,
        dataset_id: datasetId ? Number(datasetId) : null,
      }),
    onSuccess: (created) => {
      const trained = created.filter((m) => m.status === "trained");
      const deferred = created.filter((m) => m.status === "deferred");
      const flagged = created.filter((m) => m.uses_proxy_labels);
      const note =
        flagged.length > 0
          ? " PROXY/SIMULATED labels in use — not yet field validated."
          : " Trained on real field labels.";
      const parts: string[] = [];
      if (trained.length)
        parts.push(trained.map((m) => `${m.kind} v${m.version}`).join(", "));
      if (deferred.length)
        parts.push(deferred.map((m) => `${m.kind} deferred`).join(", "));
      setMsg({
        kind: "ok",
        text: `Trained ${parts.join("; ")}.${note}`,
      });
      qc.invalidateQueries({ queryKey: ["models"] });
      qc.invalidateQueries({ queryKey: ["models-latest"] });
      qc.invalidateQueries({ queryKey: ["status"] });
      qc.invalidateQueries({ queryKey: ["label-status"] });
    },
    onError: (e: Error) => setMsg({ kind: "err", text: e.message }),
  });

  const activate = useMutation({
    mutationFn: (id: number) => api.activateModel(id),
    onSuccess: (m) => {
      setMsg({ kind: "ok", text: `Activated ${m.name} v${m.version}.` });
      qc.invalidateQueries({ queryKey: ["models"] });
      qc.invalidateQueries({ queryKey: ["models-latest"] });
      qc.invalidateQueries({ queryKey: ["status"] });
      qc.invalidateQueries({ queryKey: ["label-status"] });
    },
    onError: (e: Error) => setMsg({ kind: "err", text: e.message }),
  });

  const shap = useQuery({
    queryKey: ["shap", shapFor],
    queryFn: () => api.modelShap(shapFor!),
    enabled: !!shapFor,
  });

  if (isLoading) return <Spinner label="Loading models…" />;

  const proxyModels = (models ?? []).filter((m) => m.uses_proxy_labels);
  const detailModel = (models ?? []).find((m) => m.id === detail);

  return (
    <div className="space-y-5">
      {proxyModels.length > 0 && <ProxyNotice />}

      <Card
        title="Train machine-learning models"
        subtitle="Three supervised Phase-6 models (RandomForest classifiers + verified-outcome regressor) plus the legacy gradient-boosting scorers"
      >
        <div className="grid max-w-4xl grid-cols-1 gap-3 sm:grid-cols-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-400">
              Model kind
            </label>
            <select
              className={inputCls}
              value={kind}
              onChange={(e) => setKind(e.target.value)}
            >
              {KIND_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-400">
              Training dataset
            </label>
            <select
              className={inputCls}
              value={datasetId}
              onChange={(e) => setDatasetId(e.target.value)}
            >
              <option value="">Latest / promoted</option>
              {(datasets ?? []).map((d) => (
                <option key={d.id} value={d.id}>
                  #{d.id} {d.name} ({d.rows_count} rows)
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-end">
            <Button
              onClick={() => training.mutate()}
              disabled={training.isPending}
            >
              {training.isPending ? "Training…" : "Train models"}
            </Button>
          </div>
        </div>
        {msg && (
          <p className={`mt-3 text-sm ${msg.kind === "ok" ? "text-emerald-400" : "text-red-400"}`}>
            {msg.text}
          </p>
        )}
      </Card>

      {latest && latest.length > 0 && (
        <Card title="Latest models" subtitle="Newest trained version per model kind">
          <div className="flex flex-wrap gap-2">
            {latest.map((m) => (
              <button
                key={m.id}
                onClick={() => refetch()}
                className={`rounded-lg border px-3 py-2 text-left transition ${
                  m.is_active
                    ? "border-emerald-500/40 bg-emerald-500/10"
                    : m.status === "deferred"
                      ? "border-red-500/30 bg-red-500/5"
                      : "border-white/10 bg-white/5"
                }`}
              >
                <p className="text-xs font-semibold text-slate-200">{m.name}</p>
                <p className="text-[10px] text-slate-400">
                  {m.algorithm} · v{m.version} · {m.rows_trained} rows
                </p>
              </button>
            ))}
          </div>
        </Card>
      )}

      <Card title="Registered models" subtitle="Click a row for training details">
        {(models ?? []).length === 0 ? (
          <EmptyState>No models trained yet — press Train or restart with AUTO_SEED=true.</EmptyState>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-white/10 text-[11px] uppercase tracking-wider text-slate-500">
                  <th className="py-2 pr-4">ID</th>
                  <th className="py-2 pr-4">Model</th>
                  <th className="py-2 pr-4">Algo</th>
                  <th className="py-2 pr-4">Version</th>
                  <th className="py-2 pr-4">Train/Test</th>
                  <th className="py-2 pr-4">Labels</th>
                  <th className="py-2 pr-4">MAE</th>
                  <th className="py-2 pr-4">R²</th>
                  <th className="py-2 pr-4">Accuracy</th>
                  <th className="py-2 pr-4">Active</th>
                  <th className="py-2 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {models?.map((m) => (
                  <tr key={m.id} className="border-b border-white/5">
                    <td className="py-2 pr-4 text-slate-500">#{m.id}</td>
                    <td className="py-2 pr-4">
                      <button
                        className="text-left font-medium text-slate-200 hover:text-brine-300"
                        onClick={() => setDetail(m.id)}
                      >
                        {m.name}
                      </button>
                    </td>
                    <td className="py-2 pr-4 text-xs text-slate-400">{m.algorithm || "—"}</td>
                    <td className="py-2 pr-4">
                      {m.status === "deferred" ? (
                        <Badge className="border-red-500/40 bg-red-500/15 text-red-300">
                          deferred
                        </Badge>
                      ) : (
                        <Badge className="border-brine-500/40 bg-brine-500/15 text-brine-300">
                          v{m.version}
                        </Badge>
                      )}
                    </td>
                    <td className="py-2 pr-4 tabular-nums text-slate-400">
                      {m.rows_trained}/{m.test_rows}
                    </td>
                    <td className="py-2 pr-4">
                      {m.uses_proxy_labels === false ? (
                        <Badge className="border-emerald-500/40 bg-emerald-500/15 text-emerald-300"
                               title="Trained on real field measurements">
                          FIELD
                        </Badge>
                      ) : (
                        <Badge className="border-amber-500/40 bg-amber-500/15 text-amber-300"
                               title="Trained on proxy/simulated labels — not field validated">
                          PROXY
                        </Badge>
                      )}
                    </td>
                    <td className="py-2 pr-4 tabular-nums text-slate-300">
                      {m.metrics.mae?.toFixed(4)}
                    </td>
                    <td className="py-2 pr-4 tabular-nums text-slate-300">
                      {m.metrics.r2?.toFixed(3)}
                    </td>
                    <td className="py-2 pr-4 tabular-nums text-slate-300">
                      {m.metrics.accuracy?.toFixed(3)}
                    </td>
                    <td className="py-2 pr-4">
                      {m.is_active ? (
                        <span className="inline-block h-2 w-2 rounded-full bg-emerald-400" />
                      ) : (
                        <span className="inline-block h-2 w-2 rounded-full bg-slate-600" />
                      )}
                    </td>
                    <td className="py-2 text-right">
                      {m.status !== "deferred" && !m.is_active && (
                        <Button
                          variant="ghost"
                          onClick={() => activate.mutate(m.id)}
                          disabled={activate.isPending}
                        >
                          Activate
                        </Button>
                      )}
                      {m.status !== "deferred" &&
                        ["harvest_readiness", "climate_risk"].includes(m.kind) && (
                          <Button variant="ghost" onClick={() => setShapFor(m.id)}>
                            Explain
                          </Button>
                        )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {detailModel && <ModelDetail model={detailModel} onShowShap={setShapFor} />}

      {shapFor && (
        <Card
          title="SHAP feature importance"
          subtitle={
            shap.data ? `Global importance for ${shap.data.kind} (TreeExplainer)` : undefined
          }
          right={
            <Button variant="ghost" onClick={() => setShapFor(null)}>
              Close
            </Button>
          }
        >
          {shap.isLoading ? (
            <Spinner label="Computing SHAP…" />
          ) : (shap.data?.shap_importance ?? []).length === 0 ? (
            <EmptyState>No SHAP values stored for this model.</EmptyState>
          ) : (
            <ResponsiveContainer width="100%" height={Math.min(
              420,
              (shap.data?.shap_importance.length ?? 8) * 40 + 60,
            )}>
              <BarChart
                data={shap.data?.shap_importance.slice(0, 10)}
                layout="vertical"
                margin={{ left: 40, right: 24 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#1e3a52" />
                <XAxis type="number" stroke="#64748b" tick={{ fontSize: 11 }} />
                <YAxis
                  type="category"
                  dataKey="feature"
                  width={170}
                  stroke="#64748b"
                  tick={{ fontSize: 11 }}
                />
                <Tooltip
                  contentStyle={{
                    background: "#0b1521",
                    border: "1px solid #1f3a4d",
                    borderRadius: 8,
                  }}
                />
                <Bar dataKey="importance" fill="#24aecd" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </Card>
      )}
    </div>
  );
}