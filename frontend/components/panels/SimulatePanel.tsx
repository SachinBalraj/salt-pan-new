"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
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
import { api, fmt, riskTone } from "@/lib/api";
import { Badge, Button, Card, inputCls, Spinner, Stat } from "@/components/ui";
import { PanSelect } from "./common";

export default function SimulatePanel() {
  const { data: pans } = useQuery({ queryKey: ["pans"], queryFn: api.pans });
  const [panId, setPanId] = useState<number>(0);
  const [rain, setRain] = useState(35);
  const [dayOffset, setDayOffset] = useState(1);
  const [dryAfter, setDryAfter] = useState(3);
  const selected = pans?.find((p) => p.id === panId) ?? pans?.[0];

  const sim = useMutation({
    mutationFn: () =>
      api.simulateRain({
        pan_id: selected!.id,
        horizon_days: 7,
        scenario: { rainfall_mm: rain, day_offset: dayOffset, dry_days_after: dryAfter },
      }),
  });

  const s = sim.data;
  const chartData = s
    ? s.baseline.map((b, i) => ({
        label: b.label,
        "baseline readiness": +b.readiness.toFixed(3),
        "after rain readiness": +s.rain_scenario[i].readiness.toFixed(3),
        "baseline risk": +b.risk.toFixed(3),
        "after rain risk": +s.rain_scenario[i].risk.toFixed(3),
      }))
    : [];

  const critical = s?.impact.risk_critical;
  const rt = riskTone(s?.impact.max_risk_after_rain ?? 0);

  return (
    <div className="space-y-5">
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
            <Button onClick={() => sim.mutate()} disabled={sim.isPending || !selected}>
              {sim.isPending ? "Simulating…" : "Run simulation"}
            </Button>
          </div>
        </div>

        {!s ? (
          <Spinner label="Run a scenario to see projected impacts." />
        ) : (
          <>
            <div className="mt-5 flex flex-wrap items-center gap-2 text-xs text-slate-400">
              <Badge className="border-brine-500/40 bg-brine-500/15 text-brine-300">{s.scenario_name}</Badge>
              <Badge className="border-white/10 bg-white/5 text-slate-300">forecast source: {s.forecast_source}</Badge>
              {critical && (
                <Badge className="border-red-500/40 bg-red-500/15 text-red-300">critically risky outcome</Badge>
              )}
            </div>

            <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
              <Stat label="Projected yield loss" value={`${fmt.kg(s.impact.projected_yield_loss_kg)} kg`} tone="text-red-400" sub={`${s.impact.salt_thickness_loss_mm} mm of salt layer dissolved`} />
              <Stat label="Risk increase" value={`+${fmt.pct(s.impact.risk_increase)}`} tone={rt.text} sub={`peak ${fmt.pct(s.impact.max_risk_after_rain)} today → ${fmt.pct(s.impact.max_risk_baseline)}`} />
              <Stat label="Readiness drop" value={`-${fmt.pct(s.impact.readiness_drop_on_day)}`} tone="text-amber-300" sub={`${fmt.pct(s.impact.readiness_before)} → ${fmt.pct(s.impact.readiness_after)} on ${fmt.date(s.impact.event_date)}`} />
              <Stat label="Days setback" value={`~${s.impact.days_setback_estimate} days`} tone="text-sky-300" sub="to rebuild dissolved salt layer" />
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