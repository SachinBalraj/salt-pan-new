"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, fmt, readinessTone, riskTone } from "@/lib/api";
import { Badge, Card, Spinner, Stat } from "@/components/ui";
import Dashboard from "@/components/panels/Dashboard";
import DataPanel from "@/components/panels/DataPanel";
import ModelsPanel from "@/components/panels/ModelsPanel";
import TwinPanel from "@/components/panels/TwinPanel";
import WeatherPanel from "@/components/panels/WeatherPanel";
import PredictPanel from "@/components/panels/PredictPanel";
import SimulatePanel from "@/components/panels/SimulatePanel";
import RecommendationsPanel from "@/components/panels/RecommendationsPanel";
import OutcomesPanel from "@/components/panels/OutcomesPanel";
import ComparePanel from "@/components/panels/ComparePanel";

const tabs = [
  { key: "dashboard", label: "Dashboard" },
  { key: "data", label: "Data" },
  { key: "models", label: "Models" },
  { key: "twin", label: "Digital twin" },
  { key: "weather", label: "Weather" },
  { key: "predict", label: "Predict" },
  { key: "simulate", label: "What-if" },
  { key: "recommend", label: "Advise" },
  { key: "outcomes", label: "Outcomes" },
  { key: "compare", label: "Compare" },
] as const;

type TabKey = (typeof tabs)[number]["key"];

function TopBar() {
  const { data: status, isLoading } = useQuery({
    queryKey: ["status"],
    queryFn: api.status,
    refetchInterval: 30_000,
  });
  return (
    <header className="sticky top-0 z-20 border-b border-white/10 bg-[#0b1521]/85 backdrop-blur">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-2 px-4 py-3">
        <div>
          <h1 className="text-lg font-black tracking-tight text-slate-100 text-glow">
            SALT<span className="text-brine-400">LENS</span>
            <span className="ml-2 text-sm font-medium text-slate-500">· DSS</span>
          </h1>
          <p className="text-[11px] text-slate-500">
            AI-driven digital twin decision support for salt pans
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          {isLoading ? (
            <Badge className="border-white/10 bg-white/5 text-slate-400">checking…</Badge>
          ) : (
            <>
              <Badge className="border-emerald-500/40 bg-emerald-500/15 text-emerald-300">
                API connected
              </Badge>
              <Badge className="border-white/10 bg-white/5 text-slate-300">
                {status?.pans ?? 0} pans · {status?.models ?? 0} models
              </Badge>
              <Badge className="border-white/10 bg-white/5 text-slate-300">
                DB · {status?.seeded ? "seeded" : "empty"}
              </Badge>
            </>
          )}
        </div>
      </div>
    </header>
  );
}

function KpiStrip() {
  const { data: pans, isLoading } = useQuery({ queryKey: ["pans"], queryFn: api.pans });
  const twins = useQuery({
    queryKey: ["twins-all"],
    queryFn: async () => {
      const list = pans ?? [];
      return Promise.all(list.map((p) => api.panTwin(p.id)));
    },
    enabled: !isLoading && !!pans && pans.length > 0,
  });
  if (isLoading) {
    return <div className="grid grid-cols-2 gap-3 md:grid-cols-4"><Spinner label="Loading…" /></div>;
  }
  const list = pans ?? [];
  const progress = (twins.data ?? [])
    .map((t) => t.progress_to_harvest)
    .concat(Array(Math.max(0, list.length - (twins.data?.length ?? 0))).fill(0));
  const avgReadiness = progress.length
    ? progress.reduce((a, v) => a + v, 0) / progress.length
    : 0;
  const harvestReady = progress.filter((v) => v >= 0.55).length;
  const atRisk = (twins.data ?? []).filter((t) => (t.state.risk as number) >= 0.65).length;
  return (
    <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
      <Stat label="Pans tracked" value={String(list.length)} tone="text-slate-100" sub="digital twin instances" />
      <Stat label="Avg readiness" value={fmt.pct(avgReadiness)} tone={readinessTone(avgReadiness).text} sub="harvest progress" />
      <Stat label="Harvest-ready" value={String(harvestReady)} tone="text-emerald-400" sub="readiness ≥ 55%" />
      <Stat label="Risk-prone" value={String(atRisk)} tone={riskTone(0.65).text} sub="climate risk ≥ 65%" />
    </div>
  );
}

export default function Home() {
  const [tab, setTab] = useState<TabKey>("dashboard");

  return (
    <div className="min-h-screen">
      <TopBar />
      <main className="mx-auto max-w-7xl px-4 pb-24 pt-4">
        <KpiStrip />
        <nav className="mt-6 flex flex-wrap gap-1.5 border-b border-white/10 pb-3">
          {tabs.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={
                tab === t.key
                  ? "rounded-lg bg-brine-500/20 px-3 py-1.5 text-sm font-semibold text-brine-300"
                  : "rounded-lg px-3 py-1.5 text-sm text-slate-400 transition hover:bg-white/5 hover:text-slate-200"
              }
            >
              {t.label}
            </button>
          ))}
        </nav>
        <section className="mt-5">
          {tab === "dashboard" && <Dashboard />}
          {tab === "data" && <DataPanel />}
          {tab === "models" && <ModelsPanel />}
          {tab === "twin" && <TwinPanel />}
          {tab === "weather" && <WeatherPanel />}
          {tab === "predict" && <PredictPanel />}
          {tab === "simulate" && <SimulatePanel />}
          {tab === "recommend" && <RecommendationsPanel />}
          {tab === "outcomes" && <OutcomesPanel />}
          {tab === "compare" && <ComparePanel />}
        </section>
      </main>
    </div>
  );
}