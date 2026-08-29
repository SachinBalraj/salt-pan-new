"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, severityColor } from "@/lib/api";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  inputCls,
  Spinner,
} from "@/components/ui";
import { PanSelect } from "./common";

export default function RecommendationsPanel() {
  const qc = useQueryClient();
  const { data: pans } = useQuery({ queryKey: ["pans"], queryFn: api.pans });
  const [panId, setPanId] = useState<number>(0);
  const [statusFilter, setStatusFilter] = useState("");
  const [notes, setNotes] = useState<Record<number, string>>({});
  const selected = pans?.find((p) => p.id === panId) ?? pans?.[0];

  const recs = useQuery({
    queryKey: ["recs", selected?.id, statusFilter],
    queryFn: () => api.recommendations(selected?.id ?? undefined, statusFilter || undefined),
    enabled: !pans || pans.length > 0,
  });

  const generate = useMutation({
    mutationFn: () => api.generateRecommendations(selected!.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["recs"] });
      qc.invalidateQueries({ queryKey: ["status"] });
    },
  });

  const respond = useMutation({
    mutationFn: ({ id, status, farmer_notes }: { id: number; status: "accepted" | "declined"; farmer_notes: string }) =>
      api.respondRecommendation(id, { status, farmer_notes }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["recs"] });
      qc.invalidateQueries({ queryKey: ["status"] });
      qc.invalidateQueries({ queryKey: ["eval-summary"] });
    },
  });

  if (!pans || pans.length === 0) {
    return <Card title="Recommendations"><p className="text-sm text-slate-500">No pans available.</p></Card>;
  }

  return (
    <div className="space-y-5">
      <Card
        title="Farmer recommendations"
        subtitle="Rule-based guidance built on ML scores + SHAP rationale + digital-twin state"
        right={
          <div className="flex items-center gap-2">
            <div className="w-52">
              <PanSelect value={selected?.id ?? 0} onChange={setPanId} />
            </div>
            <select className="rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm text-slate-100"
              value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
              <option value="">All statuses</option>
              <option value="pending">Pending</option>
              <option value="accepted">Accepted</option>
              <option value="declined">Declined</option>
            </select>
            <Button onClick={() => generate.mutate()} disabled={generate.isPending}>
              {generate.isPending ? "Generating…" : "Generate for pan"}
            </Button>
          </div>
        }
      >
        {recs.isLoading ? (
          <Spinner label="Loading recommendations…" />
        ) : (recs.data ?? []).length === 0 ? (
          <EmptyState>
            No recommendations yet. Press <b>Generate for pan</b> to produce guidance for{" "}
            {selected?.pan_id}.
          </EmptyState>
        ) : (
          <ul className="space-y-3">
            {(recs.data ?? []).map((r) => (
              <li key={r.id} className="rounded-xl border border-white/5 bg-black/20 p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <Badge className={severityColor(r.risk_level)}>{r.risk_level}</Badge>
                    <span className="text-sm font-bold text-slate-100">{r.title}</span>
                  </div>
                  <Badge className={
                    r.status === "accepted"
                      ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-300"
                      : r.status === "declined"
                        ? "border-slate-400/40 bg-slate-500/15 text-slate-300"
                        : "border-amber-500/40 bg-amber-500/15 text-amber-300"
                  }>
                    {r.status}
                  </Badge>
                </div>
                <p className="mt-2 text-sm text-slate-300">{r.message}</p>
                <div className="mt-1.5 text-xs text-emerald-400/90">↳ {r.expected_benefit}</div>
                <div className="mt-2 rounded-lg bg-black/30 px-3 py-2 text-xs text-slate-500">
                  <b className="text-slate-400">Why:</b> {r.rationale}
                </div>

                {r.status === "pending" && (
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <input
                      className={`${inputCls} max-w-xs`}
                      placeholder="Farmer notes (optional)"
                      value={notes[r.id] ?? ""}
                      onChange={(e) => setNotes((n) => ({ ...n, [r.id]: e.target.value }))}
                    />
                    <Button variant="success" disabled={respond.isPending}
                      onClick={() => respond.mutate({ id: r.id, status: "accepted", farmer_notes: notes[r.id] ?? "" })}>
                      Accept
                    </Button>
                    <Button variant="danger" disabled={respond.isPending}
                      onClick={() => respond.mutate({ id: r.id, status: "declined", farmer_notes: notes[r.id] ?? "" })}>
                      Decline
                    </Button>
                  </div>
                )}
                {r.farmer_notes && r.status !== "pending" && (
                  <div className="mt-2 text-xs text-slate-400">Farmer note: “{r.farmer_notes}”</div>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}