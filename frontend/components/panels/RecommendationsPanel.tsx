"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, fmt, severityColor, recStatusTone } from "@/lib/api";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  inputCls,
  Spinner,
} from "@/components/ui";
import { PanSelect } from "./common";
import { useLang, t } from "@/lib/i18n";
import type { Recommendation } from "@/lib/types";

const TABS = [
  { key: "active", label: "Active", match: (s: string) => s === "pending" },
  { key: "accepted", label: "Accepted", match: (s: string) => s === "accepted" },
  { key: "rejected", label: "Rejected", match: (s: string) => s === "declined" || s === "rejected" },
  { key: "completed", label: "Completed", match: (s: string) => s === "completed" || s === "expired" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

function bucket(list: Recommendation[], tab: TabKey) {
  const tabDef = TABS.find((x) => x.key === tab)!;
  return list.filter((r) => tabDef.match(r.status));
}

export default function RecommendationsPanel() {
  const qc = useQueryClient();
  const { lang } = useLang();
  const { data: pans } = useQuery({ queryKey: ["pans"], queryFn: api.pans });
  const [panId, setPanId] = useState<number>(0);
  const [tab, setTab] = useState<TabKey>("active");
  const [notes, setNotes] = useState<Record<number, string>>({});
  const selected = pans?.find((p) => p.id === panId) ?? pans?.[0];

  const recs = useQuery({
    queryKey: ["recs", selected?.id],
    queryFn: () => api.recommendations(selected?.id ?? undefined),
    enabled: !pans || pans.length > 0,
  });
  const list = recs.data ?? [];

  const generate = useMutation({
    mutationFn: () => api.generateRecommendations(selected!.id),
    onSuccess: (created) => {
      const first = created[0]?.status;
      if (first && first !== "pending") setTab("accepted");
      qc.invalidateQueries({ queryKey: ["recs"] });
      qc.invalidateQueries({ queryKey: ["status"] });
    },
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["recs"] });
    qc.invalidateQueries({ queryKey: ["status"] });
    qc.invalidateQueries({ queryKey: ["eval-summary"] });
  };

  const respond = useMutation({
    mutationFn: ({ id, status }: { id: number; status: "accepted" | "declined" }) =>
      api.respondRecommendation(id, { status, farmer_notes: notes[id] ?? "" }),
    onSuccess: invalidate,
  });
  const complete = useMutation({
    mutationFn: (id: number) => api.completeRecommendation(id),
    onSuccess: invalidate,
  });

  if (!pans || pans.length === 0) {
    return <Card title="Recommendations"><p className="text-sm text-slate-500">No pans available.</p></Card>;
  }

  const shown = bucket(list, tab);
  const counts = TABS.reduce<Record<string, number>>((acc, x) => {
    acc[x.key] = bucket(list, x.key).length;
    return acc;
  }, {});

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
            <Button onClick={() => generate.mutate()} disabled={generate.isPending}>
              {generate.isPending ? "Generating…" : "Generate for pan"}
            </Button>
          </div>
        }
      >
        {/* status tabs */}
        <div className="mb-4 flex flex-wrap gap-1.5 border-b border-white/10 pb-3">
          {TABS.map((x) => (
            <button
              key={x.key}
              onClick={() => setTab(x.key)}
              className={
                tab === x.key
                  ? "rounded-lg bg-brine-500/20 px-3 py-1.5 text-sm font-semibold text-brine-300"
                  : "rounded-lg px-3 py-1.5 text-sm text-slate-400 transition hover:bg-white/5 hover:text-slate-200"
              }
            >
              {x.label} <span className="ml-1 text-xs opacity-60">{counts[x.key]}</span>
            </button>
          ))}
        </div>

        {recs.isLoading ? (
          <Spinner label="Loading recommendations…" />
        ) : shown.length === 0 ? (
          <EmptyState>
            No {TABS.find((x) => x.key === tab)?.label.toLowerCase()} recommendations for{" "}
            {selected?.pan_id}. Generate advice or switch tabs.
          </EmptyState>
        ) : (
          <ul className="space-y-3">
            {shown.map((r) => (
              <li key={r.id} className="rounded-xl border border-white/5 bg-black/20 p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge className={severityColor(r.risk_level)}>{r.risk_level}</Badge>
                    <span className="text-sm font-bold text-slate-100">{t(r.title, lang)}</span>
                    <Badge className="border-white/10 bg-white/5 text-slate-300">
                      {t(r.recommendation_type, lang).replace(/_/g, " ")}
                    </Badge>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    {r.confidence_pct > 0 && (
                      <Badge className="border-sky-500/40 bg-sky-500/15 text-sky-300">
                        {r.confidence_pct}% confidence
                      </Badge>
                    )}
                    {r.action_deadline && r.status === "pending" && (
                      <Badge className="border-amber-500/40 bg-amber-500/15 text-amber-300">
                        act by {fmt.date(r.action_deadline)}
                      </Badge>
                    )}
                    <Badge className={recStatusTone(r.status)}>{t(r.status, lang)}</Badge>
                  </div>
                </div>
                <p className="mt-2 text-sm text-slate-300">{t(r.message, lang)}</p>
                <div className="mt-1.5 text-xs text-emerald-400/90">
                  ↳ {t(r.expected_benefit, lang)}
                </div>

                {r.consequence_if_waited && r.status === "pending" && (
                  <div className="mt-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
                    <b>If the farmer waits:</b> {t(r.consequence_if_waited, lang)}
                  </div>
                )}

                <div className="mt-3 grid gap-3 lg:grid-cols-2">
                  <div className="rounded-lg bg-black/30 px-3 py-2 text-xs text-slate-500">
                    <b className="text-slate-400">Three reasons</b>
                    <ol className="mt-1 list-decimal space-y-1 pl-4">
                      {(r.reasons ?? []).map((reason, i) =>
                        reason ? <li key={i} className="text-slate-300">{t(reason, lang)}</li> : null,
                      )}
                    </ol>
                  </div>
                  <div className="rounded-lg bg-black/30 px-3 py-2 text-xs text-slate-500">
                    <b className="text-slate-400">Step by step</b>
                    <ol className="mt-1 list-decimal space-y-1 pl-4">
                      {(r.instructions ?? []).map((step, i) =>
                        step ? <li key={i} className="text-slate-300">{t(step, lang)}</li> : null,
                      )}
                    </ol>
                  </div>
                </div>

                {r.status === "pending" && (
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <input
                      className={`${inputCls} max-w-xs`}
                      placeholder={lang === "ta" ? "விவசாயி குறிப்புகள் (விருப்பம்)" : "Farmer notes (optional)"}
                      value={notes[r.id] ?? ""}
                      onChange={(e) => setNotes((n) => ({ ...n, [r.id]: e.target.value }))}
                    />
                    <Button variant="success" disabled={respond.isPending}
                      onClick={() => respond.mutate({ id: r.id, status: "accepted" })}>
                      Accept
                    </Button>
                    <Button variant="danger" disabled={respond.isPending}
                      onClick={() => respond.mutate({ id: r.id, status: "declined" })}>
                      Decline
                    </Button>
                  </div>
                )}
                {r.status === "accepted" && (
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <Button disabled={complete.isPending} onClick={() => complete.mutate(r.id)}>
                      {complete.isPending ? "Marking…" : "Mark as completed in the field"}
                    </Button>
                    <span className="text-xs text-slate-500">Accepted ✓ — log the outcome to close it automatically.</span>
                  </div>
                )}
                {r.farmer_notes && r.status !== "pending" && (
                  <div className="mt-2 text-xs text-slate-400">
                    {lang === "ta" ? "விவசாயி குறிப்பு" : "Farmer note"}: “{r.farmer_notes}”
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}