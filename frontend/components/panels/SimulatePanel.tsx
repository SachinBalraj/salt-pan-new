"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, fmt, riskTone } from "@/lib/api";
import { Badge, Button, Card, inputCls, Spinner, Stat } from "@/components/ui";
import { PanSelect } from "./common";
import type { RainRiskLevel, SimulateRainOut } from "@/lib/types";

const RISK_TONE: Record<RainRiskLevel, string> = {
  LOW: "bg-emerald-500/15 text-emerald-300 border-emerald-500/40",
  MEDIUM: "bg-amber-500/15 text-amber-300 border-amber-500/40",
  HIGH: "bg-red-500/15 text-red-300 border-red-500/40",
};

const RISK_SCORE: Record<RainRiskLevel, number> = {
  LOW: 0.15,
  MEDIUM: 0.5,
  HIGH: 0.9,
};

const ACTION_LABEL: Record<string, string> = {
  harvest_now: "Harvest now",
  store_brine: "Store the concentrated brine",
  protect_pan: "Protect the pans",
  monitor: "Keep monitoring",
};

function RiskBadge({ level }: { level: RainRiskLevel }) {
  return (
    <Badge className={`border ${RISK_TONE[level]}`} title={`risk: ${level.toLowerCase()}`}>
      {level}
    </Badge>
  );
}

export default function SimulatePanel() {
  const { data: pans } = useQuery({ queryKey: ["pans"], queryFn: api.pans });
  const [panId, setPanId] = useState<number>(0);
  const [rain, setRain] = useState(20);
  const selected = pans?.find((p) => p.id === panId) ?? pans?.[0];

  // ---- Phase-9 quick rain simulator ----------------------------------
  const sim = useMutation({
    mutationFn: (mm: number) => api.simulatePanRain(selected!.id, mm),
  });
  useEffect(() => {
    sim.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [panId]);

  const twin = useQuery({
    queryKey: ["digital-twin", selected?.id],
    queryFn: () => api.digitalTwin(selected!.id),
    enabled: !!selected,
    refetchInterval: 30_000,
  });

  const s: SimulateRainOut | undefined = sim.data;

  // ---- existing ML scenario what-if ----------------------------------
  const [dayOffset, setDayOffset] = useState(1);
  const [dryAfter, setDryAfter] = useState(3);
  const ml = useMutation({
    mutationFn: () =>
      api.simulateRain({
        pan_id: selected!.id,
        horizon_days: 7,
        scenario: { rainfall_mm: rain, day_offset: dayOffset, dry_days_after: dryAfter },
      }),
  });
  useEffect(() => {
    ml.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [panId]);

  const m = ml.data;
  const chartData = m
    ? m.baseline.map((b, i) => ({
        label: b.label,
        "baseline readiness": +b.readiness.toFixed(3),
        "after rain readiness": +m.rain_scenario[i].readiness.toFixed(3),
        "baseline risk": +b.risk.toFixed(3),
        "after rain risk": +m.rain_scenario[i].risk.toFixed(3),
      }))
    : [];

  const salinityCompare = s
    ? [
        {
          label: "Salinity (g/L)",
          before: s.current_salinity_g_l,
          after: s.predicted_salinity_after_rain_g_l,
        },
      ]
    : [];
  const depthCompare = s
    ? [
        {
          label: "Water depth (cm)",
          before: s.current_depth_cm,
          after: s.predicted_depth_after_rain_cm,
        },
      ]
    : [];

  return (
    <div className="space-y-5">
      <Card
        title="Rain impact simulator"
        subtitle="Pick a pan, slide the rainfall to 0–100 mm, hit Simulate — see the pan before and after the event"
        right={
          <div className="w-56">
            <PanSelect value={selected?.id ?? 0} onChange={setPanId} />
          </div>
        }
      >
        <div className="grid max-w-3xl items-end gap-4 sm:grid-cols-[1fr_auto]">
          <label className="block">
            <span className="mb-1 flex items-center justify-between text-xs font-medium text-slate-400">
              <span>Rainfall event</span>
              <span className="rounded-md bg-brine-500/20 px-2 py-0.5 font-bold tabular-nums text-brine-300">
                {rain} mm
              </span>
            </span>
            <input
              type="range"
              min={0}
              max={100}
              step={1}
              value={rain}
              onChange={(e) => setRain(Number(e.target.value))}
              className="w-full accent-brine-400"
            />
            <span className="mt-1 flex justify-between text-[11px] text-slate-500">
              <span>0 mm · drizzle</span>
              <span>100 mm · storm</span>
            </span>
          </label>
          <div className="flex items-end gap-2">
            <Button onClick={() => sim.mutate(rain)} disabled={sim.isPending || !selected || rain <= 0} variant="primary">
              {sim.isPending ? "Simulating…" : "Simulate"}
            </Button>
          </div>
        </div>
        {rain <= 0 && (
          <p className="mt-2 text-xs text-slate-500">Move the slider above 0 mm to run a scenario.</p>
        )}

        {!s && !twin.data ? (
          <Spinner label="Loading the selected pan's twin state…" />
        ) : (
          <>
            {twin.data && (
<div className="mt-5 grid grid-cols-2 gap-3 md:grid-cols-4">
                  <Stat label="Current salinity" value={`${(s?.current_salinity_g_l ?? twin.data.salinity_g_l).toFixed(0)} g/L`} tone="text-brine-300" sub="brine concentration" />
                  <Stat label="Current depth" value={fmt.cm(s?.current_depth_cm ?? twin.data.water_depth_cm)} tone="text-sky-300" sub="water column in the bed" />
                  <Stat label="Current volume" value={`${(s?.current_volume_m3 ?? twin.data.brine_volume_m3).toFixed(0)} m³`} tone="text-slate-200" sub="brine in the pan" />
                  <Stat label="Forecast (24 h)" value={fmt.mm(twin.data.forecast_rainfall_mm)} tone="text-amber-300" sub={`7-day: ${fmt.mm(twin.data.forecast_rainfall_7d_mm)}`} />
                </div>
            )}

            {s && (
              <>
                <div className="mt-5 grid grid-cols-2 gap-3 md:grid-cols-4">
                  <Stat label="Rain volume" value={`${s.rain_volume_m3.toFixed(0)} m³`} tone="text-sky-300" sub="water added by the event" />
                  <Stat label="Depth after rain" value={fmt.cm(s.predicted_depth_after_rain_cm)} tone={s.predicted_depth_after_rain_cm > s.current_depth_cm ? "text-amber-300" : "text-slate-200"} sub={`+${s.predicted_depth_after_rain_cm - s.current_depth_cm} cm`} />
                  <Stat label="Salinity after rain" value={`${s.predicted_salinity_after_rain_g_l.toFixed(0)} g/L`} tone="text-brine-300" sub={`from ${s.current_salinity_g_l.toFixed(0)} g/L`} />
                  <Stat label="Harvest delay" value={`${(s.predicted_harvest_delay_hours / 24).toFixed(0)} days`} tone="text-red-400" sub={`≈ ${s.predicted_harvest_delay_hours.toFixed(0)} h to recover`} />
                </div>

                <div className="mt-5 grid gap-5 lg:grid-cols-3">
                  <div>
                    <div className="mb-2 text-sm font-semibold text-slate-300">Salinity before vs after</div>
                    <ResponsiveContainer width="100%" height={240}>
                      <BarChart data={salinityCompare}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#1e3a52" />
                        <XAxis dataKey="label" stroke="#64748b" tick={{ fontSize: 11 }} />
                        <YAxis stroke="#64748b" tick={{ fontSize: 11 }} />
                        <Tooltip contentStyle={{ background: "#0b1521", border: "1px solid #1f3a4d", borderRadius: 8 }} />
                        <Legend />
                        <Bar dataKey="before" name="before" fill="#4cc4dc" radius={[6, 6, 0, 0]} />
                        <Bar dataKey="after" name="after (rain)" fill="#f87171" radius={[6, 6, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                  <div>
                    <div className="mb-2 text-sm font-semibold text-slate-300">Water depth before vs after</div>
                    <ResponsiveContainer width="100%" height={240}>
                      <BarChart data={depthCompare}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#1e3a52" />
                        <XAxis dataKey="label" stroke="#64748b" tick={{ fontSize: 11 }} />
                        <YAxis stroke="#64748b" tick={{ fontSize: 11 }} />
                        <Tooltip contentStyle={{ background: "#0b1521", border: "1px solid #1f3a4d", borderRadius: 8 }} />
                        <Legend />
                        <Bar dataKey="before" name="before" fill="#4cc4dc" radius={[6, 6, 0, 0]} />
                        <Bar dataKey="after" name="after (rain)" fill="#60a5fa" radius={[6, 6, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                  <div>
                    <div className="mb-2 flex items-center justify-between text-sm font-semibold text-slate-300">
                      <span>Risk comparison</span>
                      <span className="flex items-center gap-1.5 text-xs font-normal">
                        <RiskBadge level={s.risk_before} />
                        <span className="text-slate-500">→</span>
                        <RiskBadge level={s.risk_after} />
                      </span>
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <div className="rounded-lg border border-white/5 bg-black/20 p-3">
                        <div className="text-[11px] font-medium uppercase tracking-wider text-slate-500">Before</div>
                        <div className="mt-2 flex items-center gap-2">
                          <span className="h-2.5 w-2.5 rounded-full bg-emerald-400" />
                          <RiskBadge level={s.risk_before} />
                        </div>
                        <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-white/10">
                          <div className="h-full rounded-full bg-emerald-500" style={{ width: `${RISK_SCORE[s.risk_before] * 100}%` }} />
                        </div>
                      </div>
                      <div className="rounded-lg border border-white/5 bg-black/20 p-3">
                        <div className="text-[11px] font-medium uppercase tracking-wider text-slate-500">After</div>
                        <div className="mt-2 flex items-center gap-2">
                          <span className="h-2.5 w-2.5 rounded-full bg-red-400" />
                          <RiskBadge level={s.risk_after} />
                        </div>
                        <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-white/10">
                          <div className="h-full rounded-full bg-red-500" style={{ width: `${RISK_SCORE[s.risk_after] * 100}%` }} />
                        </div>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="mt-5 flex items-start gap-3 rounded-xl border border-brine-500/30 bg-brine-500/10 p-4">
                  <div>
                    <Badge className="border-brine-500/40 bg-brine-500/20 text-brine-300">
                      RECOMMENDED
                    </Badge>
                  </div>
                  <div>
                    <div className="text-sm font-bold text-brine-300">
                      {ACTION_LABEL[s.recommended_action] ?? s.recommended_action}
                    </div>
                    <p className="mt-1 text-sm leading-relaxed text-slate-300">{s.recommendation}</p>
                  </div>
                </div>
              </>
            )}
          </>
        )}
      </Card>

      <Card
        title="“What happens if it rains tomorrow?”"
        subtitle="Simulate a rain event inside the digital twin, project both timelines with the ML models, and quantify the impact"
        right={
          <div className="w-56">
            <PanSelect value={selected?.id ?? 0} onChange={setPanId} />
          </div>
        }
      >
        <div className="grid max-w-3xl grid-cols-2 gap-3 sm:grid-cols-4">
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-400">Rain event (mm)</span>
            <input className={inputCls} type="number" min={1} max={200} value={rain}
              onChange={(e) => setRain(Number(e.target.value))} />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-400">Day of event (0…6)</span>
            <input className={inputCls} type="number" min={0} max={6} value={dayOffset}
              onChange={(e) => setDayOffset(Number(e.target.value))} />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-400">Dry days after</span>
            <input className={inputCls} type="number" min={0} max={7} value={dryAfter}
              onChange={(e) => setDryAfter(Number(e.target.value))} />
          </label>
          <div className="flex items-end">
            <Button onClick={() => ml.mutate()} disabled={ml.isPending || !selected}>
              {ml.isPending ? "Simulating…" : "Run simulation"}
            </Button>
          </div>
        </div>

        {!m ? (
          <Spinner label="Run a scenario to see projected impacts." />
        ) : (
          <>
            <div className="mt-5 flex flex-wrap items-center gap-2 text-xs text-slate-400">
              <Badge className="border-brine-500/40 bg-brine-500/15 text-brine-300">{m.scenario_name}</Badge>
              <Badge className="border-white/10 bg-white/5 text-slate-300">forecast source: {m.forecast_source}</Badge>
              {m.impact.risk_critical && (
                <Badge className="border-red-500/40 bg-red-500/15 text-red-300">critically risky outcome</Badge>
              )}
            </div>

            <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
              <Stat label="Projected yield loss" value={`${fmt.kg(m.impact.projected_yield_loss_kg)} kg`} tone="text-red-400" sub={`${m.impact.salt_thickness_loss_mm} mm of salt layer dissolved`} />
              <Stat label="Risk increase" value={`+${fmt.pct(m.impact.risk_increase)}`} tone={riskTone(m.impact.max_risk_after_rain).text} sub={`peak ${fmt.pct(m.impact.max_risk_after_rain)} today → ${fmt.pct(m.impact.max_risk_baseline)}`} />
              <Stat label="Readiness drop" value={`-${fmt.pct(m.impact.readiness_drop_on_day)}`} tone="text-amber-300" sub={`${fmt.pct(m.impact.readiness_before)} → ${fmt.pct(m.impact.readiness_after)} on ${fmt.date(m.impact.event_date)}`} />
              <Stat label="Days setback" value={`~${m.impact.days_setback_estimate} days`} tone="text-sky-300" sub="to rebuild dissolved salt layer" />
            </div>

            <div className="mt-5 grid gap-5 lg:grid-cols-2">
              <div>
                <div className="mb-2 text-sm font-semibold text-slate-300">Harvest readiness — baseline vs rain</div>
                <ResponsiveContainer width="100%" height={240}>
                  <LineChart data={chartData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e3a52" />
                    <XAxis dataKey="label" stroke="#64748b" tick={{ fontSize: 11 }} />
                    <YAxis domain={[0, 1]} stroke="#64748b" tick={{ fontSize: 11 }} />
                    <Tooltip contentStyle={{ background: "#0b1521", border: "1px solid #1f3a4d", borderRadius: 8 }} />
                    <Legend />
                    <Line type="monotone" dataKey="baseline readiness" stroke="#10b981" strokeWidth={2.5} dot={false} />
                    <Line type="monotone" dataKey="after rain readiness" stroke="#f59e0b" strokeWidth={2.5} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <div>
                <div className="mb-2 text-sm font-semibold text-slate-300">Climate risk — baseline vs rain</div>
                <ResponsiveContainer width="100%" height={240}>
                  <LineChart data={chartData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e3a52" />
                    <XAxis dataKey="label" stroke="#64748b" tick={{ fontSize: 11 }} />
                    <YAxis domain={[0, 1]} stroke="#64748b" tick={{ fontSize: 11 }} />
                    <Tooltip contentStyle={{ background: "#0b1521", border: "1px solid #1f3a4d", borderRadius: 8 }} />
                    <Legend />
                    <Line type="monotone" dataKey="baseline risk" stroke="#f87171" strokeWidth={1.5} dot={false} />
                    <Line type="monotone" dataKey="after rain risk" stroke="#ff2040" strokeWidth={2.5} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          </>
        )}
      </Card>
    </div>
  );
}