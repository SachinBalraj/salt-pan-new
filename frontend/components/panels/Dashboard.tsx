"use client";

import { useQuery } from "@tanstack/react-query";
import { api, fmt, readinessTone, riskTone, recStatusTone } from "@/lib/api";
import { Badge, Card, Meter, Spinner, Stat } from "@/components/ui";
import { PanSelect } from "./common";
import { useLang, t } from "@/lib/i18n";
import type { DigitalTwinOut, Recommendation } from "@/lib/types";

const ACTION_TONE: Record<string, string> = {
  harvest_now: "border-red-500/40 bg-red-500/15 text-red-300",
  protect_pan: "border-red-500/40 bg-red-500/15 text-red-300",
  store_brine: "border-red-500/40 bg-red-500/15 text-red-300",
  harvest_soon: "border-amber-500/40 bg-amber-500/15 text-amber-300",
  pump_excess: "border-amber-500/40 bg-amber-500/15 text-amber-300",
  continue_evaporation: "border-emerald-500/40 bg-emerald-500/15 text-emerald-300",
  monitor: "border-emerald-500/40 bg-emerald-500/15 text-emerald-300",
};

function actionBadge(action: string) {
  return (
    `border px-2.5 py-1 text-sm font-bold ` +
    (ACTION_TONE[action] ?? "border-sky-500/40 bg-sky-500/15 text-sky-300")
  );
}

function ActionCard({ rec, twin }: { rec?: Recommendation; twin?: DigitalTwinOut }) {
  const { lang } = useLang();
  if (!rec || !twin) {
    return (
      <p className="text-sm text-slate-500">
        No active recommendation for this pan. Open the Recommendations page and
        press <b>Generate</b>.
      </p>
    );
  }
  const action = rec.recommendation_type;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge className={actionBadge(action)}>
          {t(rec.title, lang)}
        </Badge>
        <Badge className={recStatusTone(rec.status)}>{t(rec.status, lang)}</Badge>
        {rec.action_deadline && (
          <span className="text-xs text-slate-500">
            act by {fmt.date(rec.action_deadline)}
          </span>
        )}
      </div>
      <p className="text-sm leading-relaxed text-slate-300">{t(rec.message, lang)}</p>
      <div className="rounded-lg border border-white/5 bg-black/30 px-3 py-2 text-xs text-slate-400">
        <b className="text-slate-300">Why: </b>
        {t(rec.reasons?.filter(Boolean)[0], lang)}
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
        <span>Confidence {Math.round(rec.confidence_pct)}%</span>
        <span>•</span>
        <span>
          {t("Last update", lang)}: {fmt.date(twin.last_update)}{" "}
          {twin.last_update?.includes("T") ? new Date(twin.last_update).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" }) : ""}
        </span>
      </div>
    </div>
  );
}

export default function Dashboard({ onOpenPan }: { onOpenPan?: (id: number) => void }) {
  const { lang } = useLang();
  const status = useQuery({ queryKey: ["status"], queryFn: api.status });
  const { data: pans, isLoading: pansLoading } = useQuery({
    queryKey: ["pans"],
    queryFn: api.pans,
  });

  const twins = useQuery({
    queryKey: ["dts-all"],
    queryFn: async () => {
      const list = await api.pans();
      return Promise.all(list.map((p) => api.digitalTwin(p.id)));
    },
    enabled: !pansLoading,
  });

  const recs = useQuery({
    queryKey: ["recs-all-active"],
    queryFn: () => api.recommendations(undefined, "pending"),
  });

  if (pansLoading || status.isLoading) return <Spinner label="Loading dashboard…" />;
  const list = pans ?? [];
  const dts = twins.data ?? [];
  const pending = recs.data ?? [];

  const byPan = (panId: number) => dts.find((d) => d.pan_id === panId);

  const highRisk = dts.filter((d) => d.climate_risk >= 0.65).length;
  const harvestReady = dts.filter((d) => d.harvest_readiness >= 0.55).length;

  const selected = list[0];
  const twin = byPan(selected?.id ?? -1);
  const pr = twin?.rain_probability_pct ?? 0;
  const rainNow = pr >= 70 ? "text-red-400" : pr >= 40 ? "text-amber-300" : "text-emerald-400";
  const latestPending = pending.find((r) => r.pan_id === selected?.id) ?? pending[0];
  const rain7 = dts.length ? dts.reduce((a, d) => a + (d.forecast_rainfall_7d_mm ?? 0), 0) / dts.length : 0;
  const maxDepth = Math.max(0, ...dts.map((d) => d.water_depth_cm ?? 0));
  const maxSal = Math.max(0, ...dts.map((d) => d.salinity_g_l ?? 0));

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold text-slate-100">Farmer dashboard</h2>
          <p className="text-sm text-slate-400">
            Live digital twins across all salt pans · refreshed from forecasts, sensors and outcomes
          </p>
        </div>
        <Badge
          className={
            status.data?.seeded
              ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-300"
              : "border-amber-500/40 bg-amber-500/15 text-amber-300"
          }
        >
          {status.data?.seeded ? "System ready" : "Setup required"}
        </Badge>
      </div>

      {/* Fleet KPI strip */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Total pans" value={String(list.length)} tone="text-slate-100" sub="digital twin instances" />
        <Stat label="High-risk pans" value={String(highRisk)} tone={highRisk ? "text-red-400" : "text-emerald-400"} sub="climate risk ≥ 65%" />
        <Stat label="Harvest-ready" value={String(harvestReady)} tone="text-emerald-400" sub="readiness ≥ 55%" />
        <Stat label="Active alerts" value={String(pending.length)} tone={pending.length ? "text-amber-300" : "text-emerald-400"} sub="recommendations awaiting action" />
      </div>

      {/* Live conditions of the lead pan */}
      <Card
        title="Current field conditions"
        subtitle={selected ? `${selected.pan_id} · ${selected.name} · ${selected.location}` : "No pans yet"}
        right={
          <div className="w-56">
            <PanSelect value={selected?.id ?? 0} onChange={() => {}} allowAll allValue={list[0]?.id ?? 0} />
          </div>
        }
      >
        {dts.length === 0 ? (
          <p className="text-sm text-slate-500">
            No digital twins yet. Create a pan in the Setup wizard to begin.
          </p>
        ) : (
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Current salinity" value={twin ? `${fmt.kg(Math.round(twin.salinity_g_l))} g/L` : "—"} tone={readinessTone(twin?.harvest_readiness ?? 0).text} sub="sea of brine concentration" />
            <Stat label="Water depth" value={twin ? fmt.cm(twin.water_depth_cm) : "—"} tone={twin && twin.water_depth_cm > (twin as any).state?.safe_depth_cm ? "text-red-400" : "text-slate-100"} sub="over the salt bed" />
            <Stat label="Rain probability" value={twin ? fmt.pct(pr / 100) : "—"} tone={rainNow} sub="next 24 h" />
            <Stat label="Forecast rainfall" value={twin ? `${fmt.mm(twin.forecast_rainfall_7d_mm)} (7d)` : "—"} tone={twin && twin.forecast_rainfall_7d_mm >= 10 ? "text-red-400" : "text-sky-300"} sub={`fleet avg ${fmt.mm(rain7)}`} />
          </div>
        )}
      </Card>

      {/* Recommended action */}
      <div className="grid gap-5 lg:grid-cols-2">
        <Card
          title={t("Recommended action", lang)}
          subtitle={`Highest-priority advice for ${selected?.pan_id ?? "the fleet"}`}
          right={
            selected ? (
              <button
                className="rounded-lg border border-white/10 px-3 py-1.5 text-xs text-slate-300 transition hover:bg-white/5"
                onClick={() => onOpenPan?.(selected.id)}
              >
                Open pan details →
              </button>
            ) : undefined
          }
        >
          <ActionCard rec={latestPending} twin={twin} />
        </Card>

        <Card title="Pan status board" subtitle="Tap a pan to open its full details">
          {list.length === 0 ? (
            <p className="text-sm text-slate-500">No pans registered.</p>
          ) : (
            <ul className="space-y-2.5">
              {list.map((p) => {
                const d = byPan(p.id);
                const r = d?.harvest_readiness ?? 0;
                const risk = d?.climate_risk ?? 0;
                const rt = readinessTone(r);
                const rk = riskTone(risk);
                return (
                  <li key={p.id}>
                    <button
                      className="w-full rounded-lg border border-white/5 bg-black/20 p-3 text-left transition hover:border-brine-500/30"
                      onClick={() => onOpenPan?.(p.id)}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="text-sm font-semibold text-slate-200">
                          {p.pan_id} <span className="font-normal text-slate-500">· {p.name}</span>
                        </div>
                        <div className="flex items-center gap-2 text-[11px]">
                          <span className={`rounded-md px-1.5 py-0.5 font-semibold ${rk.text}`}>
                            risk {fmt.pct(risk)}
                          </span>
                          <span className={`rounded-md px-1.5 py-0.5 font-semibold ${rt.text}`}>
                            ready {fmt.pct(r)}
                          </span>
                        </div>
                      </div>
                      <div className="mt-2"><Meter value={r} tone={rt.bar} /></div>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>
      </div>

      {/* Fleet extremes */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Peak salinity" value={maxSal ? `${fmt.kg(Math.round(maxSal))} g/L` : "—"} tone="text-brine-300" sub="across the fleet" />
        <Stat label="Peak depth" value={maxDepth ? fmt.cm(maxDepth) : "—"} tone={maxDepth >= 15 ? "text-red-400" : "text-sky-300"} sub="deepest brine column" />
        <Stat label="Recommendations" value={String(status.data?.recommendations ?? 0)} tone="text-slate-100" sub="generated to date" />
        <Stat label="Outcomes logged" value={String(status.data?.outcomes ?? 0)} tone="text-slate-100" sub="ground truth collected" />
      </div>
    </div>
  );
}