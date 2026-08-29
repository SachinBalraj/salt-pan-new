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
import {
  Badge,
  Button,
  Card,
  EmptyState,
  inputCls,
  Spinner,
} from "@/components/ui";
import { useDatasets } from "./common";

export default function ModelsPanel() {
  const qc = useQueryClient();
  const { data: models, isLoading } = useQuery({
    queryKey: ["models"],
    queryFn: api.models,
  });
  const { data: datasets } = useDatasets();

  const [kind, setKind] = useState("all");
  const [datasetId, setDatasetId] = useState("");
  const [shapFor, setShapFor] = useState<number | null>(null);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const training = useMutation({
    mutationFn: () =>
      api.train({
        kind,
        dataset_id: datasetId ? Number(datasetId) : null,
      }),
    onSuccess: (created) => {
      setMsg({
        kind: "ok",
        text: `Trained ${created.map((m) => m.kind).join(", ")} (v${created.map((m) => m.version).join("/v")}).`,
      });
      qc.invalidateQueries({ queryKey: ["models"] });
      qc.invalidateQueries({ queryKey: ["status"] });
    },
    onError: (e: Error) => setMsg({ kind: "err", text: e.message }),
  });

  const shap = useQuery({
    queryKey: ["shap", shapFor],
    queryFn: () => api.modelShap(shapFor!),
    enabled: !!shapFor,
  });

  if (isLoading) return <Spinner label="Loading models…" />;

  return (
    <div className="space-y-5">
      <Card
        title="Train machine-learning models"
        subtitle="GradientBoosting regressors with cross-validated metrics and global SHAP feature importance"
      >
        <div className="grid max-w-3xl grid-cols-1 gap-3 sm:grid-cols-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-400">
              Model kind
            </label>
            <select
              className={inputCls}
              value={kind}
              onChange={(e) => setKind(e.target.value)}
            >
              <option value="all">Both models</option>
              <option value="harvest_readiness">Harvest readiness</option>
              <option value="climate_risk">Climate risk</option>
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

      <Card title="Registered models" subtitle="Latest versions listed first">
        {(models ?? []).length === 0 ? (
          <EmptyState>No models trained yet — press Train or restart with AUTO_SEED=true.</EmptyState>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-white/10 text-[11px] uppercase tracking-wider text-slate-500">
                  <th className="py-2 pr-4">ID</th>
                  <th className="py-2 pr-4">Kind</th>
                  <th className="py-2 pr-4">Version</th>
                  <th className="py-2 pr-4">Rows</th>
                  <th className="py-2 pr-4">MAE</th>
                  <th className="py-2 pr-4">RMSE</th>
                  <th className="py-2 pr-4">R²</th>
                  <th className="py-2 pr-4">Accuracy</th>
                  <th className="py-2 text-right">SHAP</th>
                </tr>
              </thead>
              <tbody>
                {models?.map((m) => (
                  <tr key={m.id} className="border-b border-white/5">
                    <td className="py-2 pr-4 text-slate-500">#{m.id}</td>
                    <td className="py-2 pr-4 font-medium text-slate-200">
                      {m.name}
                    </td>
                    <td className="py-2 pr-4">
                      <Badge className="border-brine-500/40 bg-brine-500/15 text-brine-300">
                        v{m.version}
                      </Badge>
                    </td>
                    <td className="py-2 pr-4 tabular-nums text-slate-400">
                      {m.rows_trained.toLocaleString()}
                    </td>
                    <td className="py-2 pr-4 tabular-nums text-slate-300">
                      {m.metrics.mae?.toFixed(4)}
                    </td>
                    <td className="py-2 pr-4 tabular-nums text-slate-300">
                      {m.metrics.rmse?.toFixed(4)}
                    </td>
                    <td className="py-2 pr-4 tabular-nums text-slate-300">
                      {m.metrics.r2?.toFixed(3)}
                    </td>
                    <td className="py-2 pr-4 tabular-nums text-slate-300">
                      {m.metrics.accuracy?.toFixed(3)}
                    </td>
                    <td className="py-2 text-right">
                      <Button variant="ghost" onClick={() => setShapFor(m.id)}>
                        Explain
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

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