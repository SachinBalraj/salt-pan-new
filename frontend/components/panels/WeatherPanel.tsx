"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, fmt } from "@/lib/api";
import { Badge, Button, Card, Spinner, Stat } from "@/components/ui";
import { PanSelect } from "./common";

export default function WeatherPanel() {
  const { data: pans } = useQuery({ queryKey: ["pans"], queryFn: api.pans });
  const [panId, setPanId] = useState<number>(0);
  const [scenario, setScenario] = useState("mock");
  const [days, setDays] = useState(7);
  const [force, setForce] = useState(0);
  const selected = pans?.find((p) => p.id === panId) ?? pans?.[0];

  const forecast = useQuery({
    queryKey: ["forecast", selected?.id, scenario, days, force],
    queryFn: () => api.forecast(selected?.id ?? null, days, scenario, true),
    enabled: !!selected?.id,
  });

  const data = forecast.isLoading ? undefined : forecast.data?.days;

  return (
    <div className="space-y-5">
      <Card
        title="Weather forecast"
        subtitle="Open-Meteo live feed with a deterministic seasonal mock provider for offline/demo use"
        right={
          <div className="flex items-center gap-2">
            <div className="w-52">
              <PanSelect value={selected?.id ?? 0} onChange={setPanId} />
            </div>
            <select
              className="rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm text-slate-100"
              value={scenario}
              onChange={(e) => setScenario(e.target.value)}
            >
              <option value="mock">Mock (offline)</option>
              <option value="auto">Live (auto-fallback)</option>
              <option value="live">Live only</option>
            </select>
            <select
              className="rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm text-slate-100"
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
            >
              {[7, 14, 21].map((d) => (
                <option key={d} value={d}>{d} days</option>
              ))}
            </select>
            <Button variant="ghost" onClick={() => setForce((f) => f + 1)}>
              Refresh
            </Button>
          </div>
        }
      >
        {forecast.isLoading || !data ? (
          <Spinner label="Fetching forecast…" />
        ) : (
          <>
            <div className="mb-3 flex items-center gap-2 text-xs text-slate-400">
              <Badge className={forecast.data?.source === "open_meteo"
                ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-300"
                : "border-amber-500/40 bg-amber-500/15 text-amber-300"}>
                {forecast.data?.source}
              </Badge>
              Last fetched {fmt.date(forecast.data?.generated_at)}
            </div>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Stat label="Max temp" value={fmt.temp(Math.max(...data.map((d) => d.temperature_c)))} tone="text-amber-300" />
              <Stat label="Total rain" value={`${data.reduce((a, d) => a + d.rainfall_mm, 0).toFixed(1)} mm`} tone="text-sky-300" />
              <Stat label="Peak rain day" value={data.reduce((a, d) => (d.rainfall_mm > a.rainfall_mm ? d : a), data[0]).rainfall_mm > 0 ? data.reduce((a, d) => (d.rainfall_mm > a.rainfall_mm ? d : a), data[0]).date.split("-").slice(1).reverse().join(" ") : "dry"} tone="text-slate-200" />
              <Stat label="Avg wind" value={`${(data.reduce((a, d) => a + d.wind_speed_kmh, 0) / data.length).toFixed(0)} km/h`} tone="text-slate-200" />
            </div>
            <ResponsiveContainer width="100%" height={300}>
              <ComposedChart data={data}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e3a52" />
                <XAxis dataKey="date" stroke="#64748b" tick={{ fontSize: 11 }} tickFormatter={(v: string) => v.slice(5)} />
                <YAxis yAxisId="rain" stroke="#38bdf8" tick={{ fontSize: 11 }} tickFormatter={(v) => `${v}mm`} />
                <YAxis yAxisId="temp" orientation="right" stroke="#fbbf24" tick={{ fontSize: 11 }} tickFormatter={(v) => `${v}°`} />
                <Tooltip
                  contentStyle={{ background: "#0b1521", border: "1px solid #1f3a4d", borderRadius: 8 }}
                />
                <Legend />
                <Bar yAxisId="rain" dataKey="rainfall_mm" name="Rain (mm)" fill="#38bdf8" radius={[4, 4, 0, 0]} />
                <Line yAxisId="temp" type="monotone" dataKey="temperature_c" name="Temp (°C)" stroke="#fbbf24" strokeWidth={2} dot={false} />
                <Line yAxisId="temp" type="monotone" dataKey="humidity_pct" name="Humidity (%)" stroke="#a78bfa" strokeWidth={1.5} dot={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </>
        )}
      </Card>
    </div>
  );
}