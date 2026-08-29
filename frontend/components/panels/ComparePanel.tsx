"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, fmt, readinessTone } from "@/lib/api";
import { Card, Spinner } from "@/components/ui";
import { PanSelect } from "./common";

export default function ComparePanel() {
  const { data: pans } = useQuery({ queryKey: ["pans"], queryFn: api.pans });
  const [panA, setPanA] = useState<number>(0);
  const [panB, setPanB] = useState<number>(0);
  const a = pans?.find((p) => p.id === panA) ?? pans?.[0];
  const b = pans?.find((p) => p.id === panB) ?? pans?.[1];

  const pa = useQuery({ queryKey: ["twin", a?.id], queryFn: () => api.panTwin(a!.id), enabled: !!a });
  const pb = useQuery({ queryKey: ["twin", b?.id], queryFn: () => api.panTwin(b!.id), enabled: !!b });

  if (!pans || pans.length < 2) {
    return <Card title="Compare pans"><p className="text-sm text-slate-500">Need at least two pans to compare.</p></Card>;
  }
  if (pa.isLoading || pb.isLoading || !pa.data || !pb.data) return <Spinner label="Loading twins…" />;

  const rows: Array<{ label: string; left: React.ReactNode; right: React.ReactNode; best?: "a" | "b" }> = [
    {
      label: "Brine density",
      left: <span className={readinessTone((pa.data.state.brine_density_be ?? 0) / 30).text}>{fmt.be(pa.data.state.brine_density_be)}</span>,
      right: <span className={readinessTone((pb.data.state.brine_density_be ?? 0) / 30).text}>{fmt.be(pb.data.state.brine_density_be)}</span>,
      best: (pa.data.state.brine_density_be ?? 0) >= (pb.data.state.brine_density_be ?? 0) ? "a" : "b",
    },
    {
      label: "Salt thickness",
      left: <span>{fmt.mm(pa.data.state.salt_thickness_mm)}</span>,
      right: <span>{fmt.mm(pb.data.state.salt_thickness_mm)}</span>,
      best: (pa.data.state.salt_thickness_mm ?? 0) >= (pb.data.state.salt_thickness_mm ?? 0) ? "a" : "b",
    },
    {
      label: "Days since last rain",
      left: <span>{pa.data.state.days_since_last_rain ?? 0} d</span>,
      right: <span>{pb.data.state.days_since_last_rain ?? 0} d</span>,
      best: (pa.data.state.days_since_last_rain ?? 0) >= (pb.data.state.days_since_last_rain ?? 0) ? "a" : "b",
    },
    {
      label: "Progress to harvest",
      left: <span className={readinessTone(pa.data.progress_to_harvest).text}>{fmt.pct(pa.data.progress_to_harvest)}</span>,
      right: <span className={readinessTone(pb.data.progress_to_harvest).text}>{fmt.pct(pb.data.progress_to_harvest)}</span>,
      best: pa.data.progress_to_harvest >= pb.data.progress_to_harvest ? "a" : "b",
    },
  ];

  return (
    <div className="space-y-5">
      <Card title="Pan readiness tour" subtitle="Readiness per pan (demo seed) with harvest window">
        <div className="space-y-2">
          {pans.map((pan) => {
            const t = pa.data && pa.data.pan.id === pan.id
              ? pa.data
              : pb.data && pb.data.pan.id === pan.id
                ? pb.data
                : undefined;
            const r = (t?.progress_to_harvest ?? 0) * 100;
            return (
              <div key={pan.id} className="flex items-center gap-3 text-sm">
                <span className="w-24 shrink-0 text-slate-400">{pan.pan_id}</span>
                <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-black/30">
                  <div
                    className="h-full rounded-full bg-brine-400 transition-all"
                    style={{ width: `${r}%` }}
                  />
                </div>
                <span className="w-20 text-right tabular-nums text-slate-200">{fmt.pct(r / 100)}</span>
              </div>
            );
          })}
        </div>
      </Card>

      <Card title="Side-by-side comparison" subtitle="Select two pans to benchmark against each other">
        <div className="mb-4 grid max-w-xl grid-cols-2 gap-3">
          <PanSelect value={a!.id} onChange={setPanA} />
          <PanSelect value={b!.id} onChange={setPanB} />
        </div>

        <div className="overflow-hidden rounded-xl border border-white/5">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/10 bg-black/30 text-[11px] uppercase tracking-wider text-slate-500">
                <th className="px-4 py-2 text-center">{a!.pan_id}</th>
                <th className="px-4 py-2 text-left">Metric</th>
                <th className="px-4 py-2 text-center">{b!.pan_id}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.label} className="border-b border-white/5 last:border-0">
                  <td className={`px-4 py-2.5 text-center ${row.best === "a" ? "font-semibold text-brine-300" : "text-slate-400"}`}>
                    {row.left}
                  </td>
                  <td className="px-4 py-2.5 text-center text-xs text-slate-500">{row.label}</td>
                  <td className={`px-4 py-2.5 text-center ${row.best === "b" ? "font-semibold text-brine-300" : "text-slate-400"}`}>
                    {row.right}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}