"use client";

import { useQuery } from "@tanstack/react-query";
import { Component, ReactNode, useState } from "react";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui";
import { useLang, LANG_LABEL } from "@/lib/i18n";
import Dashboard from "@/components/panels/Dashboard";
import PanDetails from "@/components/panels/PanDetails";
import DataPanel from "@/components/panels/DataPanel";
import ModelsPanel from "@/components/panels/ModelsPanel";
import SimulatePanel from "@/components/panels/SimulatePanel";
import RecommendationsPanel from "@/components/panels/RecommendationsPanel";
import OutcomesPanel from "@/components/panels/OutcomesPanel";
import FeedbackPanel from "@/components/panels/FeedbackPanel";
import SetupPanel from "@/components/panels/SetupPanel";

const tabs = [
  { key: "dashboard", label: "Dashboard" },
  { key: "pans", label: "Pans" },
  { key: "simulate", label: "Simulator" },
  { key: "data", label: "Dataset" },
  { key: "models", label: "Models" },
  { key: "recommend", label: "Recommendations" },
  { key: "outcomes", label: "Outcomes" },
  { key: "feedback", label: "Feedback" },
  { key: "setup", label: "Setup" },
] as const;

type TabKey = (typeof tabs)[number]["key"];

// ---------------------------------------------------------------------------
// React Error Boundary — catches rendering crashes and shows a friendly page
// ---------------------------------------------------------------------------
class ErrorBoundary extends Component<
  { children: ReactNode; fallback?: ReactNode },
  { error: Error | null }
> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  render() {
    if (this.state.error) {
      return (
        this.props.fallback ?? (
          <div className="flex min-h-[50vh] flex-col items-center justify-center gap-4 px-4 text-center">
            <div className="rounded-xl border border-red-500/40 bg-red-500/10 px-6 py-5">
              <h2 className="text-lg font-bold text-red-300">
                Something went wrong
              </h2>
              <p className="mt-2 max-w-md text-sm text-slate-400">
                {this.state.error.message || "An unexpected error occurred while rendering this page."}
              </p>
              <p className="mt-2 text-xs text-slate-600">
                Try refreshing the page, or navigate to a different tab.
              </p>
            </div>
          </div>
        )
      );
    }
    return this.props.children;
  }
}

function ProxyWarningBanner() {
  const { data: status } = useQuery({
    queryKey: ["label-status"],
    queryFn: api.modelLabelStatus,
    refetchInterval: 30_000,
  });
  if (!status || !status.any_active_proxy) return null;
  return (
    <div className="sticky top-[52px] z-10 border-b border-amber-500/40 bg-amber-500/15 px-4 py-2 backdrop-blur">
      <p className="mx-auto max-w-7xl text-center text-xs font-bold tracking-wide text-amber-200">
        PROXY/SIMULATED MODEL — NOT YET FIELD VALIDATED
      </p>
      <p className="mx-auto max-w-7xl text-center text-[11px] text-amber-200/70">
        {status.subtext}
      </p>
    </div>
  );
}

function SafetyBanner() {
  const { data: safety } = useQuery({
    queryKey: ["safety"],
    queryFn: () => api.get<{ physical_equipment_control_enabled: boolean; warning: string }>("/api/system/safety"),
    refetchInterval: 60_000,
  });
  if (!safety || !safety.physical_equipment_control_enabled) return null;
  return (
    <div className="sticky top-[84px] z-10 border-b border-red-500/60 bg-red-500/20 px-4 py-2 backdrop-blur">
      <p className="mx-auto max-w-7xl text-center text-xs font-bold tracking-wide text-red-200">
        ⚠ PHYSICAL EQUIPMENT CONTROL IS ENABLED — THE SYSTEM CAN ACTIVATE PUMPS/GATES
      </p>
      <p className="mx-auto max-w-7xl text-center text-[11px] text-red-200/70">
        {safety.warning}
      </p>
    </div>
  );
}

function TopBar() {
  const { data: status, isLoading } = useQuery({
    queryKey: ["status"],
    queryFn: api.status,
    refetchInterval: 30_000,
  });
  const { lang, setLang } = useLang();
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
          <div className="flex items-center rounded-full border border-white/10 bg-white/5 p-0.5">
            {(["en", "ta"] as const).map((l) => (
              <button
                key={l}
                onClick={() => setLang(l)}
                className={`rounded-full px-2.5 py-0.5 font-medium transition ${
                  lang === l
                    ? "bg-brine-500/20 text-brine-300"
                    : "text-slate-500 hover:text-slate-300"
                }`}
                title={l === "ta" ? "Translate farmer instructions to Tamil (தமிழ்)" : "English"}
              >
                {LANG_LABEL[l]}
              </button>
            ))}
          </div>
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

export default function Home() {
  const [tab, setTab] = useState<TabKey>("dashboard");
  const [panFocus, setPanFocus] = useState<number>(0);

  const openPan = (id: number) => {
    setPanFocus(id);
    setTab("pans");
  };

  return (
    <div className="min-h-screen">
      <TopBar />
      <ProxyWarningBanner />
      <SafetyBanner />
      <main className="mx-auto max-w-7xl px-4 pb-24 pt-4">
        <nav className="mt-2 flex flex-wrap gap-1.5 border-b border-white/10 pb-3">
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
          <ErrorBoundary key={tab}>
            {tab === "dashboard" && <Dashboard onOpenPan={openPan} />}
            {tab === "pans" && <PanDetails key={panFocus} focusId={panFocus} />}
            {tab === "simulate" && <SimulatePanel />}
            {tab === "data" && <DataPanel />}
            {tab === "models" && <ModelsPanel />}
            {tab === "recommend" && <RecommendationsPanel />}
            {tab === "outcomes" && <OutcomesPanel />}
            {tab === "feedback" && <FeedbackPanel />}
            {tab === "setup" && <SetupPanel onFinish={() => setTab("dashboard")} />}
          </ErrorBoundary>
        </section>
      </main>
    </div>
  );
}