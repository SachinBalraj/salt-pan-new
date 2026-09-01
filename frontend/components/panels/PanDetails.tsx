"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, fmt, readinessTone, riskTone, recStatusTone } from "@/lib/api";
import { Badge, Button, Card, ConfirmDialog, EmptyState, inputCls, Meter, Spinner, Stat } from "@/components/ui";
import { PanSelect } from "./common";
import { useLang, t } from "@/lib/i18n";

const CHART_TOOLTIP = {
  background: "#0b1521",
  border: "1px solid #1f3a4d",
  borderRadius: 8,
};

function seriesAsc<T extends { timestamp: string }>(list: T[]) {
  return [...(list ?? [])].sort(
    (a, b) => +new Date(a.timestamp) - +new Date(b.timestamp),
  );
}

function FactorList({
  title,
  color,
  factors,
}: {
  title: string;
  color: string;
  factors: { feature: string; contribution: number; explanation: string }[];
}) {
  if (!factors?.length) return null;
  return (
    <div>
      <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">{title}</div>
      <div className="space-y-1.5">
        {factors.slice(0, 4).map((f) => (
          <div key={f.feature} className="rounded-lg border border-white/5 bg-black/20 px-3 py-2 text-xs">
            <div className="flex items-center justify-between gap-2">
              <span className="text-slate-200">{f.explanation}</span>
              <span className="shrink-0 font-mono tabular-nums" style={{ color }}>
                {f.contribution >= 0 ? "+" : ""}
                {f.contribution.toFixed(2)}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function PanDetails({ focusId }: { focusId?: number }) {
  const qc = useQueryClient();
  const { lang } = useLang();
  const [confirmOverride, setConfirmOverride] = useState(false);
  const { data: pans } = useQuery({ queryKey: ["pans"], queryFn: api.pans });
  const [panId, setPanId] = useState<number>(focusId ?? 0);
  const selected = pans?.find((p) => p.id === (panId || focusId)) ?? pans?.[0];

  const twin = useQuery({
    queryKey: ["twin", selected?.id],
    queryFn: () => api.panTwin(selected!.id),
    enabled: !!selected?.id,
  });
  const dt = useQuery({
    queryKey: ["dts", selected?.id],
    queryFn: () => api.digitalTwin(selected!.id),
    enabled: !!selected?.id,
  });
  const sensors = useQuery({
    queryKey: ["sensors", selected?.id],
    queryFn: () => api.panSensors(selected!.id),
    enabled: !!selected?.id,
    refetchInterval: 60_000,
  });
  const ops = useQuery({
    queryKey: ["ops", selected?.id],
    queryFn: () => api.panOperations(selected!.id),
    enabled: !!selected?.id,
  });
  const recs = useQuery({
    queryKey: ["recs", selected?.id],
    queryFn: () => api.recommendations(selected?.id),
    enabled: !!selected?.id,
  });
  const forecast = useQuery({
    queryKey: ["forecast", selected?.id],
    queryFn: () => api.forecast(selected?.id ?? null, 7, "auto", false),
    enabled: !!selected?.id,
  });
  const predictions = useQuery({
    queryKey: ["predictions", selected?.id],
    queryFn: () => api.predictions(selected?.id),
    enabled: !!selected?.id,
  });

  // twin state editor
  const [form, setForm] = useState<Record<string, string>>({});
  useEffect(() => {
    if (twin.data && !twin.isFetching) {
      setForm({
        water_depth_cm: String(twin.data.state.water_depth_cm ?? ""),
        brine_density_be: String(twin.data.state.brine_density_be ?? ""),
        salt_thickness_mm: String(twin.data.state.salt_thickness_mm ?? ""),
        days_since_last_rain: String(twin.data.state.days_since_last_rain ?? ""),
      });
    }
  }, [twin.data, twin.isFetching]);
  const updateTwin = useMutation({
    mutationFn: () =>
      api.updateTwin(selected!.id, {
        water_depth_cm: Number(form.water_depth_cm),
        brine_density_be: Number(form.brine_density_be),
        salt_thickness_mm: Number(form.salt_thickness_mm),
        days_since_last_rain: Number(form.days_since_last_rain),
        last_update: new Date().toISOString().slice(0, 10),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["twin"] });
      qc.invalidateQueries({ queryKey: ["dts"] });
      qc.invalidateQueries({ queryKey: ["pans"] });
    },
  });

  const sensorSeries = useMemo(
    () =>
      seriesAsc(sensors.data ?? []).map((s) => ({
        label: new Date(s.timestamp).toLocaleDateString("en-IN", { day: "2-digit", month: "short" }),
        salinity_g_l: s.salinity_g_l,
        water_depth_cm: s.water_depth_cm,
        brine_temperature_c: s.brine_temperature_c,
        air_temperature_c: s.air_temperature_c,
        humidity_pct: s.humidity_pct,
      })),
    [sensors.data],
  );
  const forecastSeries = useMemo(
    () =>
      (forecast.data?.days ?? []).map((d) => ({
        label: d.date.slice(5),
        rainfall_mm: d.rainfall_mm,
        precipitation_probability_pct: d.precipitation_probability_pct,
      })),
    [forecast.data],
  );

  if (!pans || pans.length === 0) {
    return (
      <Card title="Pan details">
        <EmptyState>No pans registered yet — use the Setup wizard to create one.</EmptyState>
      </Card>
    );
  }
  if (twin.isLoading || !twin.data) return <Spinner label="Loading pan details…" />;

  const st = twin.data.state;
  const rt = readinessTone(twin.data.progress_to_harvest);
  const risk = dt.data?.climate_risk ?? (Number(st.risk) || 0);
  const rk = riskTone(risk);
  const latestRec = (recs.data ?? []).find((r) => r.status === "pending")
    ?? (recs.data ?? [])[0];
  const latestPred = (predictions.data ?? [])[0];
  const explain = latestPred?.explain;
  const deep = st.water_depth_cm ?? 0;
  const safeDepth = (dt.data as any)?.state?.safe_depth_cm ?? 12;

  return (
    <div className="space-y-5">
      <Card
        title="Pan details"
        subtitle="Digital-twin state, in-situ sensor history and the current recommendation"
        right={
          <div className="w-56">
            <PanSelect value={selected?.id ?? 0} onChange={setPanId} />
          </div>
        }
      >
        <div className="flex flex-wrap items-center gap-3">
          <div>
            <div className="text-lg font-bold text-slate-100">{selected!.pan_id}</div>
            <div className="text-xs text-slate-500">{selected!.name} · {selected!.location}</div>
          </div>
          <Badge className="border-white/10 bg-white/5 text-slate-300">Area {selected!.area_m2.toLocaleString()} m²</Badge>
          <Badge className={`border ${recStatusTone(latestRec?.status ?? "pending")}`}>
            {latestRec ? t(latestRec.title, lang) : "no advice yet"}
          </Badge>
        </div>

        <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Stat label="Progress to harvest" value={fmt.pct(twin.data.progress_to_harvest)} tone={rt.text} />
          <Stat label="Climate risk" value={fmt.pct(risk)} tone={rk.text} />
          <Stat label="Brine density" value={fmt.be((dt.data?.state?.brine_density_be as number | undefined) ?? st.brine_density_be ?? 0)} tone="text-sky-300" />
          <Stat label="Est. salt mass" value={`${fmt.kg(st.estimated_salt_mass_kg)} kg`} tone="text-brine-300" />
        </div>
        <div className="mt-3 grid grid-cols-2 gap-3">
          <Meter value={twin.data.progress_to_harvest} label="Harvest readiness" tone={rt.bar} />
          <Meter value={risk} label="Climate risk" tone={rk.bar} />
        </div>
      </Card>

      {/* Digital-twin state */}
      <Card
        title="Digital-twin state"
        subtitle="Latest synchronous snapshot (physics, forecast edge and projections)"
      >
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
          <Stat label="Salinity" value={dt.data ? `${fmt.kg(Math.round(dt.data.salinity_g_l))} g/L` : "—"} tone="text-brine-300" />
          <Stat label="Water depth" value={dt.data ? fmt.cm(dt.data.water_depth_cm) : "—"} tone={dt.data && dt.data.water_depth_cm > 15 ? "text-red-400" : "text-sky-300"} />
          <Stat label="Brine temp" value={dt.data ? fmt.temp(dt.data.brine_temperature_c) : "—"} tone="text-amber-300" />
          <Stat label="Evaporation" value={dt.data ? `${dt.data.evaporation_mm_day.toFixed(1)} mm/d` : "—"} tone="text-slate-200" />
          <Stat label="Rain probability" value={dt.data ? fmt.pct((dt.data.rain_probability_pct ?? 0) / 100) : "—"} tone={dt.data && (dt.data.rain_probability_pct ?? 0) >= 60 ? "text-red-400" : "text-slate-200"} />
          <Stat label="Rain (7d)" value={dt.data ? fmt.mm(dt.data.forecast_rainfall_7d_mm) : "—"} tone={dt.data && dt.data.forecast_rainfall_7d_mm >= 10 ? "text-red-400" : "text-sky-300"} />
          <Stat label="Depth after rain" value={dt.data ? fmt.cm(dt.data.predicted_depth_after_rain_cm) : "—"} tone={dt.data && dt.data.predicted_depth_after_rain_cm > safeDepth ? "text-red-400" : "text-slate-200"} sub={`safe ≈ ${fmt.cm(safeDepth)}`} />
          <Stat label="Salinity after rain" value={dt.data ? `${fmt.kg(Math.round(dt.data.predicted_salinity_after_rain_g_l))} g/L` : "—"} tone={dt.data && dt.data.predicted_salinity_after_rain_g_l < 200 ? "text-amber-300" : "text-slate-200"} />
        </div>

        {twin.data.state && (
          <details className="mt-4">
            <summary className="cursor-pointer text-xs font-medium text-slate-400 hover:text-brine-300">
              Edit twin state (manual override)
            </summary>
            <div className="mt-3 grid max-w-xl grid-cols-2 gap-3">
              {(["water_depth_cm", "brine_density_be", "salt_thickness_mm", "days_since_last_rain"] as const).map((k) => (
                <label key={k} className="block">
                  <span className="mb-1 block text-xs font-medium text-slate-400">{k}</span>
                  <input className={inputCls} type="number" step="any" value={form[k] ?? ""}
                    onChange={(e) => setForm((f) => ({ ...f, [k]: e.target.value }))} />
                </label>
              ))}
            </div>
            <Button className="mt-3" onClick={() => setConfirmOverride(true)} disabled={updateTwin.isPending}>
              {updateTwin.isPending ? "Updating…" : "Update twin state"}
            </Button>
          </details>
        )}
      </Card>

      {/* Sensor charts */}
      <Card title="Sensor history & charts" subtitle={`In-situ readings for ${selected!.pan_id} · ${sensorSeries.length} samples plus 7-day forecast rain`}>
        {sensorSeries.length < 2 && forecastSeries.length === 0 ? (
          <EmptyState>No sensor history or forecast available yet.</EmptyState>
        ) : (
          <div className="grid gap-4 lg:grid-cols-2">
            {sensorSeries.length >= 2 && (
              <div>
                <div className="mb-1.5 text-xs font-semibold text-slate-300">Salinity (g/L)</div>
                <ResponsiveContainer width="100%" height={180}>
                  <LineChart data={sensorSeries}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e3a52" />
                    <XAxis dataKey="label" stroke="#64748b" tick={{ fontSize: 10 }} />
                    <YAxis stroke="#64748b" tick={{ fontSize: 10 }} />
                    <Tooltip contentStyle={CHART_TOOLTIP} />
                    <Line type="monotone" dataKey="salinity_g_l" stroke="#4cc4dc" strokeWidth={2.5} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
            {sensorSeries.length >= 2 && (
              <div>
                <div className="mb-1.5 text-xs font-semibold text-slate-300">Water depth (cm)</div>
                <ResponsiveContainer width="100%" height={180}>
                  <LineChart data={sensorSeries}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e3a52" />
                    <XAxis dataKey="label" stroke="#64748b" tick={{ fontSize: 10 }} />
                    <YAxis stroke="#64748b" tick={{ fontSize: 10 }} />
                    <Tooltip contentStyle={CHART_TOOLTIP} />
                    <Line type="monotone" dataKey="water_depth_cm" stroke="#38bdf8" strokeWidth={2.5} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
            {sensorSeries.length >= 2 && (
              <div>
                <div className="mb-1.5 text-xs font-semibold text-slate-300">Temperature (°C)</div>
                <ResponsiveContainer width="100%" height={180}>
                  <LineChart data={sensorSeries}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e3a52" />
                    <XAxis dataKey="label" stroke="#64748b" tick={{ fontSize: 10 }} />
                    <YAxis stroke="#64748b" tick={{ fontSize: 10 }} />
                    <Tooltip contentStyle={CHART_TOOLTIP} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Line type="monotone" dataKey="brine_temperature_c" name="Brine" stroke="#fbbf24" strokeWidth={2.5} dot={false} />
                    <Line type="monotone" dataKey="air_temperature_c" name="Air" stroke="#fb7185" strokeWidth={1.5} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
            {forecastSeries.length > 0 && (
              <div>
                <div className="mb-1.5 text-xs font-semibold text-slate-300">Rainfall forecast (mm) & probability (%)</div>
                <ResponsiveContainer width="100%" height={180}>
                  <ComposedChart data={forecastSeries}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e3a52" />
                    <XAxis dataKey="label" stroke="#64748b" tick={{ fontSize: 10 }} />
                    <YAxis yAxisId="l" stroke="#38bdf8" tick={{ fontSize: 10 }} />
                    <YAxis yAxisId="r" orientation="right" stroke="#a78bfa" tick={{ fontSize: 10 }} />
                    <Tooltip contentStyle={CHART_TOOLTIP} />
                    <Bar yAxisId="l" dataKey="rainfall_mm" name="Rain (mm)" fill="#38bdf8" radius={[3, 3, 0, 0]} />
                    <Line yAxisId="r" type="monotone" dataKey="precipitation_probability_pct" name="Prob (%)" stroke="#a78bfa" strokeWidth={2} dot={false} />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
        )}
        {sensorSeries.length > 0 && (
          <div className="mt-3 text-xs text-slate-500">
            Last reading {fmt.date(sensors.data?.[0]?.timestamp)} · quality{" "}
            {sensors.data?.[0]?.sensor_quality?.toFixed(0)}%
          </div>
        )}
      </Card>

      {/* Recommendation + explanation */}
      <div className="grid gap-5 lg:grid-cols-2">
        <Card
          title="Current recommendation"
          subtitle={latestRec ? `#${latestRec.id} · ${t(latestRec.recommendation_type, lang)}` : "Generate advice from the Recommendations page"}
          right={latestRec && <Badge className={recStatusTone(latestRec.status)}>{t(latestRec.status, lang)}</Badge>}
        >
          {!latestRec ? (
            <p className="text-sm text-slate-500">
              No recommendation yet. Open the Recommendations page and press <b>Generate</b>.
            </p>
          ) : (
            <div className="space-y-3">
              <div className="text-base font-bold text-slate-100">{t(latestRec.title, lang)}</div>
              <p className="text-sm text-slate-300">{t(latestRec.message, lang)}</p>
              <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
                <b>If the farmer waits:</b> {t(latestRec.consequence_if_waited, lang)}
              </div>
              {latestRec.action_deadline && (
                <p className="text-xs text-slate-500">Act by {fmt.date(latestRec.action_deadline)}</p>
              )}
            </div>
          )}
        </Card>

        <Card title="Recommendation explanation" subtitle="Why the model gave this advice (SHAP factors)">
          {!explain ? (
            <p className="text-sm text-slate-500">
              No stored explanation yet — run a prediction or generate recommendations to populate it.
            </p>
          ) : (
            <div className="space-y-3">
              <FactorList title="What drives harvest readiness?" color="#10b981" factors={explain.harvest_readiness?.factors ?? []} />
              <FactorList title="What drives climate risk?" color="#ef4444" factors={explain.climate_risk?.factors ?? []} />
              {(explain.context ?? []).length > 0 && (
                <div className="rounded-lg border border-brine-500/20 bg-brine-500/5 px-3 py-2 text-xs text-slate-200">
                  {(explain.context ?? []).map((c) => (
                    <div key={c.feature}>• {c.explanation}</div>
                  ))}
                </div>
              )}
            </div>
          )}
        </Card>
      </div>

      {/* Previous actions */}
      <Card title="Previous actions" subtitle="Logged field operations: pump, transfer, protection, harvest responses">
        {(ops.data ?? []).length === 0 ? (
          <EmptyState>No field operations logged for this pan yet — they appear here when outcomes are recorded.</EmptyState>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-white/10 text-[11px] uppercase tracking-wider text-slate-500">
                  <th className="py-2 pr-4">When</th>
                  <th className="py-2 pr-4">Action</th>
                  <th className="py-2 pr-4">Pump time</th>
                  <th className="py-2 pr-4">Transferred</th>
                  <th className="py-2 pr-4">Protection</th>
                  <th className="py-2 pr-4">Linked to</th>
                  <th className="py-2">Notes</th>
                </tr>
              </thead>
              <tbody>
                {(ops.data ?? []).map((o) => (
                  <tr key={o.id} className="border-b border-white/5">
                    <td className="py-2 pr-4 text-xs text-slate-400">{fmt.date(o.event_timestamp)}</td>
                    <td className="py-2 pr-4">
                      <Badge className={
                        o.event_type === "protection"
                          ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-300"
                          : o.event_type === "operator_response"
                            ? "border-slate-400/40 bg-slate-500/15 text-slate-300"
                            : "border-brine-500/40 bg-brine-500/15 text-brine-300"
                      }>
                        {o.event_type.replaceAll("_", " ")}
                      </Badge>
                    </td>
                    <td className="py-2 pr-4 tabular-nums text-slate-300">{fmt.hours(o.pump_duration_min)}</td>
                    <td className="py-2 pr-4 tabular-nums text-slate-300">{fmt.lit(o.transferred_volume_l)}</td>
                    <td className="py-2 pr-4 text-slate-300">{o.protection_applied ? "Yes" : "—"}</td>
                    <td className="py-2 pr-4 text-xs text-slate-500">
                      {o.recommendation_title?.replaceAll("_", " ") ?? ""}
                      {o.destination_pan_ref ? ` → ${o.destination_pan_ref}` : ""}
                    </td>
                    <td className="py-2 text-xs text-slate-400">{o.operator_notes || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <ConfirmDialog
        open={confirmOverride}
        title="Override digital-twin state?"
        message="This overwrites the twin's depth, brine density, salt thickness and last-rain fields. It drives every downstream prediction for this pan and cannot be undone. Reading from sensors may re-overwrite it on the next ingest."
        confirmLabel="Apply override"
        variant="warning"
        onConfirm={() => updateTwin.mutate()}
        onCancel={() => setConfirmOverride(false)}
      />
    </div>
  );
}