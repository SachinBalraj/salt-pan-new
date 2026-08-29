"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, fmt, readinessTone, riskTone } from "@/lib/api";
import { Badge, Card, Meter, Spinner, Stat } from "@/components/ui";
import { PanSelect } from "./common";

const topShap = (shap: Record<string, number> | undefined, n = 3) =>
  Object.entries(shap ?? {})
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
    .slice(0, n)
    .map(([k, v]) => ({ k, v }));

export default function PredictPanel() {
  const qc = useQueryClient();
  const { data: pans } = useQuery({ queryKey: ["pans"], queryFn: api.pans });
  const { data: status } = useQuery({
    queryKey: ["status"],
    queryFn: api.status,
  });
  const [panId, setPanId] = useState<number>(0);
  const [horizon, setHorizon] = useState(7);
  const selected = pans?.find((p) => p.id === panId) ?? pans?.[0];
  const noActiveModel = !status?.any_active_model;

  const run = useMutation({
    mutationFn: () => api.runPrediction(selected!.id, horizon, "actual_forecast"),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["predictions"] });
      qc.invalidateQueries({ queryKey: ["status"] });
    },
  });

  const r = run.data;
  const rt = readinessTone(r?.day0.readiness ?? 0);
  const rk = riskTone(r?.max_risk ?? 0);

  return (
    <div className="space-y-5">
      <Card
        title="Climate-risk & harvest-readiness prediction"
        subtitle="Digital-twin physics stepped through the 7-day forecast, scored by the trained ML models and explained with SHAP TreeExplainer"
        right={
          <div className="flex items-center gap-2">
            <div className="w-52">
              <PanSelect value={selected?.id ?? 0} onChange={setPanId} />
            </div>
            <select
              className="rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm text-slate-100"
              value={horizon}
              onChange={(e) => setHorizon(Number(e.target.value))}
            >
              {[3, 7, 14].map((d) => (
                <option key={d} value={d}>{d} days</option>
              ))}
            </select>
            <button
              onClick={() => run.mutate()}
              disabled={run.isPending || !selected || noActiveModel}
              className="rounded-lg bg-brine-500 px-3 py-2 text-sm font-medium text-brine-950 transition hover:bg-brine-400 disabled:opacity-40"
              title={noActiveModel ? "No active model — train one in the Models tab first" : undefined}
            >
              {run.isPending ? "Predicting…" : "Run prediction"}
            </button>
          </div>
        }
      >
        {noActiveModel && (
          <div className="rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-200">
            Prediction is disabled because there is no active trained model.
            Train a model from the Models tab, or restart with AUTO_SEED=true
            (Demo seed) to activate one.
          </div>
        )}
        {run.isError && (
          <div className="rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-200">
            {run.error instanceof Error ? run.error.message : "Prediction failed."}
          </div>
        )}
        {!r ? (
          <Spinner label="Select a pan and run the prediction." />
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <div className="rounded-lg border border-white/5 bg-black/20 p-3">
                <div className="text-[11px] uppercase tracking-wider text-slate-500">Readiness today</div>
                <div className={`mt-1 text-2xl font-black ${rt.text}`}>{fmt.pct(r.day0.readiness)}</div>
                <div className="mt-2"><Meter value={r.day0.readiness} tone={rt.bar} /></div>
              </div>
              <div className="rounded-lg border border-white/5 bg-black/20 p-3">
                <div className="text-[11px] uppercase tracking-wider text-slate-500">Peak risk (horizon)</div>
                <div className={`mt-1 text-2xl font-black ${rk.text}`}>{fmt.pct(r.max_risk)}</div>
                <div className="mt-2"><Meter value={r.max_risk} tone={rk.bar} /></div>
              </div>
              <Stat label="Brine density" value={fmt.be(r.day0.brine_density_be)} tone="text-sky-300" />
              <Stat label="Projected yield" value={`${fmt.kg(r.projected_yield_kg)} kg`} tone="text-brine-300" />
            </div>

            <div className="mt-5">
              <div className="mb-2 text-sm font-semibold text-slate-300">Forecast edge — readiness vs risk</div>
              <ResponsiveContainer width="100%" height={280}>
                <LineChart data={r.series}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e3a52" />
                  <XAxis dataKey="label" stroke="#64748b" tick={{ fontSize: 11 }} />
                  <YAxis domain={[0, 1]} stroke="#64748b" tick={{ fontSize: 11 }} />
                  <Tooltip contentStyle={{ background: "#0b1521", border: "1px solid #1f3a4d", borderRadius: 8 }} />
                  <Legend />
                  <Line type="monotone" dataKey="readiness" name="Harvest readiness" stroke="#10b981" strokeWidth={2.5} dot={false} />
                  <Line type="monotone" dataKey="risk" name="Climate risk" stroke="#ef4444" strokeWidth={2.5} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>

            <div className="mt-5 grid gap-4 lg:grid-cols-2">
              {(
                [
                  ["harvest_readiness", "What drives readiness?", "#10b981"],
                  ["climate_risk", "What drives climate risk?", "#ef4444"],
                ] as const
              ).map(([kind, title, color]) => {
                const factors = r.explain?.[kind]?.factors?.length
                  ? r.explain[kind].factors
                  : topShap(r.shap[kind]).map(({ k, v }) => ({
                      feature: k,
                      contribution: v,
                      weight_pct: 100,
                      explanation: k.replaceAll("_", " "),
                    }));
                return (
                  <div key={kind}>
                    <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">{title}</div>
                    <div className="space-y-1.5">
                      {factors.map((f) => (
                        <div key={f.feature} className="rounded-lg border border-white/5 bg-black/20 px-3 py-2 text-xs">
                          <div className="flex items-center justify-between gap-2">
                            <span className="text-slate-100">{f.explanation}</span>
                            <span style={{ color }} className="shrink-0 font-mono tabular-nums">
                              {f.contribution >= 0 ? `+${f.contribution.toFixed(2)}` : f.contribution.toFixed(2)}
                            </span>
                          </div>
                          <div className="mt-1 flex items-center justify-between gap-2 text-[10px] text-slate-500">
                            <span className="truncate">insight: {f.feature}</span>
                            <span className="shrink-0">drives {f.weight_pct}% of the signal</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>

            {(r.explain?.context?.length ?? 0) > 0 && (
              <div className="mt-5">
                <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
                  Next 24 hours at a glance
                </div>
                <div className="space-y-1.5">
                  {(r.explain?.context ?? []).map((c) => (
                    <div key={c.feature} className="rounded-lg border border-brine-500/20 bg-brine-500/5 px-3 py-2 text-xs text-slate-200">
                      {c.explanation}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </Card>

      <Card title="Recent predictions" subtitle="Stored prediction runs (scenario, score, horizon)">
        {r ? (
          <div className="flex flex-wrap gap-2 text-xs text-slate-400">
            <Badge className="border-brine-500/40 bg-brine-500/15 text-brine-300">#{r.id}</Badge>
            <span>Readiness {fmt.pct(r.day0.readiness)}</span>
            <span>·</span>
            <span>Max risk {fmt.pct(r.max_risk)}</span>
            <span>·</span>
            <span>{r.series.length}-day series</span>
          </div>
        ) : (
          <p className="text-sm text-slate-500">No prediction run yet.</p>
        )}
      </Card>
    </div>
  );
}