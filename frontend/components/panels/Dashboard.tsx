"use client";

import { useQuery } from "@tanstack/react-query";
import { api, fmt, readinessTone, riskTone, severityColor } from "@/lib/api";
import { Badge, Card, Meter, Spinner, Stat } from "@/components/ui";
import { PanSelect } from "./common";
import { useState } from "react";

export default function Dashboard() {
  const status = useQuery({ queryKey: ["status"], queryFn: api.status });
  const { data: pans, isLoading: pansLoading } = useQuery({
    queryKey: ["pans"],
    queryFn: api.pans,
  });
  const summary = useQuery({
    queryKey: ["eval-summary"],
    queryFn: api.evaluationSummary,
  });

  const [panId, setPanId] = useState<number>(0);
  const selected = pans?.find((p) => p.id === panId || panId === 0) ?? pans?.[0];
  const twin = useQuery({
    queryKey: ["twin", selected?.id],
    queryFn: () => api.panTwin(selected!.id),
    enabled: !!selected?.id,
  });

  const recs = useQuery({
    queryKey: ["recs", selected?.id],
    queryFn: () => api.recommendations(selected?.id),
    enabled: !!selected?.id,
  });

  const s = status.data;
  if (status.isLoading) return <Spinner label="Loading system status…" />;

  const readiness = twin.data?.progress_to_harvest ?? 0;
  const risk = twin.data?.state?.risk ?? 0;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold text-slate-100">Operations overview</h2>
          <p className="text-sm text-slate-400">
            AI Digital Twin • climate-resilient salt pan management
          </p>
        </div>
        <Badge className={s?.seeded ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-300" : "border-amber-500/40 bg-amber-500/15 text-amber-300"}>
          {s?.seeded ? "Demo seeded & models trained" : "Not seeded"}
        </Badge>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-6">
        <Stat label="Salt pans" value={s?.pans ?? 0} tone="text-brine-300" />
        <Stat label="ML models" value={s?.models ?? 0} tone="text-brine-300" />
        <Stat
          label="Datasets"
          value={s?.datasets ?? 0}
          tone="text-slate-100"
        />
        <Stat
          label="Predictions"
          value={s?.predictions ?? 0}
          tone="text-slate-100"
        />
        <Stat
          label="Recommendations"
          value={s?.recommendations ?? 0}
          tone="text-slate-100"
        />
        <Stat label="Outcomes" value={s?.outcomes ?? 0} tone="text-slate-100" />
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card
          title="Live digital twin"
          subtitle="Choose a pan to inspect its state and forecast edge"
          right={
            <div className="w-56">
              <PanSelect value={selected?.id ?? 0} onChange={setPanId} />
            </div>
          }
        >
          {twin.isLoading || !twin.data ? (
            <Spinner label="Loading twin…" />
          ) : (
            <div>
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-xl font-bold text-slate-100">
                    {twin.data.pan.pan_id}
                  </div>
                  <div className="text-xs text-slate-500">
                    {twin.data.pan.name} · {twin.data.pan.location}
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-2xl font-black text-brine-300">
                    {Math.round(readiness * 100)}%
                  </div>
                  <div className="text-[11px] uppercase tracking-wider text-slate-500">
                    harvest progress
                  </div>
                </div>
              </div>
              <div className="mt-3">
                <Meter
                  value={readiness}
                  label="Progress to harvest"
                  tone="bg-brine-400"
                />
              </div>
              <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
                <Stat label="Brine" value={fmt.be(twin.data.state.brine_density_be ?? 0)} tone="text-sky-300" />
                <Stat label="Salt layer" value={`${fmt.mm(twin.data.state.salt_thickness_mm ?? 0)}`} tone="text-slate-100" />
                <Stat label="Water depth" value={fmt.cm(twin.data.state.water_depth_cm ?? 0)} tone="text-slate-100" />
                <Stat label="Est. mass" value={`${fmt.kg(twin.data.state.estimated_salt_mass_kg)} kg`} tone="text-brine-300" />
              </div>
              <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-400">
                <span>
                  Days since rain:{" "}
                  <b className="text-slate-200">
                    {twin.data.state.days_since_last_rain}
                  </b>
                </span>
                <span>•</span>
                <span>
                  Last rain:{" "}
                  <b className="text-slate-200">
                    {fmt.date(twin.data.state.last_rain_date)}
                  </b>
                </span>
                <span>•</span>
                <span>
                  Twin refresh:{" "}
                  <b className="text-slate-200">
                    {fmt.date(twin.data.state.last_update)}
                  </b>
                </span>
              </div>
            </div>
          )}
        </Card>

        <Card
          title="Latest advice"
          subtitle="Recommendations generated for the selected pan"
          right={
            <div className="flex gap-2">
              <Badge className={severityColor("low")}>
                {(recs.data ?? []).filter((r) => r.status === "pending").length}{" "}
                pending
              </Badge>
              <Badge className="border-white/10 bg-white/5 text-slate-300">
                {(recs.data ?? []).filter((r) => r.status === "accepted").length} accepted
              </Badge>
            </div>
          }
        >
          {recs.isLoading ? (
            <Spinner label="Loading recommendations…" />
          ) : (recs.data ?? []).length === 0 ? (
            <p className="text-sm text-slate-500">
              No recommendations yet. Go to the Recommendations tab and press{" "}
              <b>Generate</b>.
            </p>
          ) : (
            <ul className="space-y-2.5">
              {(recs.data ?? []).slice(0, 3).map((r) => (
                <li
                  key={r.id}
                  className="rounded-lg border border-white/5 bg-black/20 p-3"
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-sm font-semibold text-slate-200">
                      {r.title}
                    </div>
                    <Badge className={severityColor(r.risk_level)}>
                      {r.risk_level}
                    </Badge>
                  </div>
                  <div className="mt-1 line-clamp-2 text-xs text-slate-400">
                    {r.message}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <div>
        <Card
          title="Model performance"
          subtitle="Validation metrics of the trained machine-learning models (legacy scorers, Phase-6 classifiers & regressor)"
        >
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {Object.entries(s?.model_kinds ?? {}).map(([kind, m]) => (
              <div
                key={kind}
                className="rounded-lg border border-white/5 bg-black/20 p-3"
              >
                <div className="text-[11px] uppercase tracking-wider text-slate-500">
                  {kind.replaceAll("_", " ")}
                </div>
                {!m.available ? (
                  <div className="mt-1 text-sm text-amber-400">Not trained</div>
                ) : m.version === 0 ? (
                  <div className="mt-1 text-sm text-red-400">Deferred — insufficient outcome data</div>
                ) : (
                  <>
                    {m.algorithm?.startsWith("RandomForestClassifier") ? (
                      <div className="mt-1 text-lg font-bold text-emerald-400">
                        Acc {m.metrics.accuracy?.toFixed(3) ?? "—"}
                      </div>
                    ) : (
                      <div className="mt-1 text-lg font-bold text-emerald-400">
                        R² {m.metrics.r2?.toFixed(3) ?? "—"}
                      </div>
                    )}
                    <div className="text-[11px] text-slate-500">
                      {m.metrics.mae !== undefined && <>MAE {m.metrics.mae.toFixed(3)} · </>}
                      {m.metrics.rmse !== undefined && <>RMSE {m.metrics.rmse.toFixed(3)} · </>}
                      {m.metrics.accuracy !== undefined && <>Acc {m.metrics.accuracy.toFixed(3)} · </>}
                      {m.metrics.f1 !== undefined && <>F1 {m.metrics.f1.toFixed(3)}</>}
                    </div>
                    <div className="mt-1 text-[10px] text-slate-600">
                      v{m.version} · {m.rows_trained} rows{m.active ? " · active" : ""}
                    </div>
                  </>
                )}
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}