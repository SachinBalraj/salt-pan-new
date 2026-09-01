"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, fmt } from "@/lib/api";
import { Badge, Button, Card, ConfirmDialog, EmptyState, Spinner, Stat } from "@/components/ui";

type PendingConfirm = "digest" | "retrain" | null;

function pct(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `${Math.round(v * 100)}%`;
}

function MatchBadge({ ok }: { ok: boolean | null }) {
  if (ok === null) return <Badge className="border-white/10 bg-white/5 text-slate-400">—</Badge>;
  return ok ? (
    <Badge className="border-emerald-500/40 bg-emerald-500/15 text-emerald-300">matched</Badge>
  ) : (
    <Badge className="border-red-500/40 bg-red-500/15 text-red-300">not followed</Badge>
  );
}

export default function FeedbackPanel() {
  const [confirm, setConfirm] = useState<PendingConfirm>(null);
  const qc = useQueryClient();
  const summary = useQuery({ queryKey: ["eval-summary"], queryFn: api.evaluationSummary });
  const rows = useQuery({ queryKey: ["comparison"], queryFn: api.comparison });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["eval-summary"] });
    qc.invalidateQueries({ queryKey: ["comparison"] });
    qc.invalidateQueries({ queryKey: ["status"] });
  };

  const ingest = useMutation({
    mutationFn: api.ingestFeedback,
    onSuccess: invalidate,
  });
  const retrain = useMutation({
    mutationFn: api.retrainWithFeedback,
    onSuccess: invalidate,
  });

  if (summary.isLoading) return <Spinner label="Loading feedback analytics…" />;
  const s = summary.data!;

  const kpis: { label: string; value: string; tone?: string; hint: string }[] = [
    { label: "Recommendation acceptance rate", value: pct(s.recommendation_acceptance_rate), tone: "text-brine-300", hint: "Accepted of all responded recommendations" },
    { label: "Recommendation completion rate", value: pct(s.recommendation_completion_rate), tone: "text-brine-300", hint: "Completed of all accepted" },
    { label: "Farmer response time", value: s.response_time_mean_hours != null ? `${fmt.kg(Math.round(s.response_time_mean_hours))} h` : "—", hint: `median ${s.response_time_median_hours != null ? `${fmt.kg(Math.round(s.response_time_median_hours))} h` : "—"} from issue to response` },
    { label: "Risk-classification accuracy", value: pct(s.risk_accuracy), hint: `TP ${s.risk_tp} · TN ${s.risk_tn} · FP ${s.risk_fp} · FN ${s.risk_fn}` },
    { label: "Harvest-date MAE", value: s.harvest_date_mae_days != null ? `${s.harvest_date_mae_days.toFixed(1)} d` : "—", hint: "predicted vs actual harvest date" },
    { label: "Yield MAE", value: s.yield_mae_kg != null ? `${fmt.kg(s.yield_mae_kg)} kg` : "—", hint: "projected vs recorded yield" },
    { label: "Forecast rainfall error", value: s.forecast_rainfall_mae_mm != null ? `${s.forecast_rainfall_mae_mm.toFixed(1)} mm` : "—", hint: "7-day forecast vs recorded rain (MAE)" },
    { label: "Recommendations with successful outcomes", value: pct(s.recommendation_success_rate), tone: "text-emerald-400", hint: `${s.linked_outcomes} linked outcome${s.linked_outcomes === 1 ? "" : "s"}` },
  ];

  return (
    <div className="space-y-5">
      <Card
        title="Feedback loop"
        subtitle="Verified field outcomes closed back into the digital twins, the training pool and model quality"
      >
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {kpis.map((k) => (
            <Stat key={k.label} label={k.label} value={k.value} tone={k.tone ?? "text-slate-100"} />
          ))}
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2 text-xs text-slate-400">
          <Badge className="border-white/10 bg-white/5 text-slate-300">
            {s.total_outcomes} outcomes · {s.verified_outcomes} verified
          </Badge>
          <Badge className="border-white/10 bg-white/5 text-slate-300">
            {s.feedback_rows_collected} feedback rows in training pool
          </Badge>
          <Badge className="border-white/10 bg-white/5 text-slate-300">
            {s.ingested_outcomes} ingested
          </Badge>
          <Badge
            className={
              s.models_pending_retrain
                ? "border-amber-500/40 bg-amber-500/15 text-amber-300"
                : "border-emerald-500/40 bg-emerald-500/15 text-emerald-300"
            }
          >
            {s.models_pending_retrain ? "retrain pending" : "models up to date"}
          </Badge>
        </div>
      </Card>

      <Card
        title="Learn from verified outcomes"
        subtitle="Retraining is always manual — nothing is retrained automatically after a single record"
        right={
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="ghost" disabled={ingest.isPending} onClick={() => setConfirm("digest")}>
              {ingest.isPending ? "Digesting…" : "Digest verified outcomes"}
            </Button>
            <Button
              disabled={retrain.isPending || s.feedback_rows_collected === 0}
              onClick={() => setConfirm("retrain")}
            >
              {retrain.isPending
                ? "Training…"
                : "Retrain using verified outcomes"}
            </Button>
          </div>
        }
      >
        {retrain.data ? (
          <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200">
            <b>Trained {retrain.data.models_trained} models</b> on{" "}
            {retrain.data.base_rows} base + {retrain.data.feedback_rows_used} verified field rows
            (combined {retrain.data.combined_rows}, dataset #{retrain.data.base_dataset_id}).
            <span className="ml-2 text-xs text-emerald-300/80">
              {retrain.data.proxy_labels_in_use
                ? "Still uses proxy labels for unprovenanced rows."
                : "No proxy labels in use — field validated."}
            </span>
            {retrain.data.errors.length > 0 && (
              <ul className="mt-2 list-disc pl-4 text-xs">
                {retrain.data.errors.map((e, i) => (
                  <li key={i} className="text-red-300">{e}</li>
                ))}
              </ul>
            )}
          </div>
        ) : s.models_pending_retrain ? (
          <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
            Verified outcomes have been collected since the last training run. Click
            “Retrain using verified outcomes” to fold the field labels into new models.
          </div>
        ) : (
          <p className="text-sm text-slate-500">
            No new verified outcomes since the last retrain. Record and verify outcomes, then
            digest them here to keep the loop healthy.
          </p>
        )}
      </Card>

      <Card title="Per-outcome comparison" subtitle="Recommended vs actual action, forecast vs observed rain, predicted vs actual harvest and yield">
        {rows.isLoading ? (
          <Spinner label="Loading comparisons…" />
        ) : (rows.data ?? []).length === 0 ? (
          <EmptyState>No outcomes recorded yet — comparisons appear once farmers log field results.</EmptyState>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-white/10 text-[11px] uppercase tracking-wider text-slate-500">
                  <th className="py-2 pr-3">Date · Pan</th>
                  <th className="py-2 pr-3">Action (advised → actual)</th>
                  <th className="py-2 pr-3">Rain (forecast → actual)</th>
                  <th className="py-2 pr-3">Harvest (predicted → actual)</th>
                  <th className="py-2 pr-3">Yield (projected → actual)</th>
                  <th className="py-2 text-right">Success</th>
                </tr>
              </thead>
              <tbody>
                {(rows.data ?? []).map((r) => (
                  <tr key={r.outcome_id} className="border-b border-white/5">
                    <td className="py-2 pr-3 text-slate-300">
                      {fmt.date(r.outcome_date)}
                      <div className="text-[11px] text-slate-500">{r.pan_ref}</div>
                    </td>
                    <td className="py-2 pr-3">
                      <div className="text-slate-300">
                        {r.recommended_action.replaceAll("_", " ") || "—"}
                        <span className="mx-1 text-slate-600">→</span>
                        {r.action_taken.replaceAll("_", " ") || "—"}
                      </div>
                      <MatchBadge ok={r.action_matched} />
                    </td>
                    <td className="py-2 pr-3 text-slate-300">
                      {r.forecast_rainfall_mm != null
                        ? `${r.forecast_rainfall_mm.toFixed(1)} → ${r.actual_rainfall_mm.toFixed(1)} mm`
                        : `${r.actual_rainfall_mm.toFixed(1)} mm`}
                      {r.rain_error_mm != null && (
                        <div className={`text-[11px] ${Math.abs(r.rain_error_mm) > 10 ? "text-red-400" : "text-emerald-400"}`}>
                          err {r.rain_error_mm >= 0 ? "+" : ""}{r.rain_error_mm.toFixed(1)} mm
                        </div>
                      )}
                    </td>
                    <td className="py-2 pr-3 text-slate-300">
                      {r.predicted_harvest_date
                        ? `${fmt.date(r.predicted_harvest_date)} → ${r.outcome_date}`
                        : "—"}
                      {r.harvest_date_error_days != null && (
                        <div className={`text-[11px] ${Math.abs(r.harvest_date_error_days) > 2 ? "text-red-400" : "text-emerald-400"}`}>
                          {r.harvest_date_error_days > 0 ? "+" : ""}{r.harvest_date_error_days} d
                        </div>
                      )}
                    </td>
                    <td className="py-2 pr-3 text-slate-300">
                      {r.projected_yield_kg != null || r.actual_yield_kg != null ? (
                        <>
                          {r.projected_yield_kg != null ? `${fmt.kg(r.projected_yield_kg)}` : "—"}
                          <span className="mx-1 text-slate-600">→</span>
                          {r.actual_yield_kg != null ? `${fmt.kg(r.actual_yield_kg)} kg` : "—"}
                        </>
                      ) : "—"}
                      {r.yield_error_kg != null && (
                        <div className="text-[11px] text-slate-500">err {fmt.kg(r.yield_error_kg)} kg</div>
                      )}
                    </td>
                    <td className="py-2 text-right">
                      <Badge
                        className={
                          r.recommendation_success === true
                            ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-300"
                            : r.recommendation_success === false
                              ? "border-red-500/40 bg-red-500/15 text-red-300"
                              : "border-white/10 bg-white/5 text-slate-400"
                        }
                      >
                        {r.recommendation_success === true ? "success" : r.recommendation_success === false ? "failed" : "unlinked"}
                      </Badge>
                      {r.feedback_ingested && (
                        <span className="ml-1 text-[10px] uppercase text-brine-300">ingested</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <ConfirmDialog
        open={confirm === "digest"}
        title="Digest verified outcomes?"
        message="This closes verified field results back into the digital twins and appends them to the training pool for future retraining. It cannot be undone."
        confirmLabel="Digest"
        variant="warning"
        onConfirm={() => ingest.mutate()}
        onCancel={() => setConfirm(null)}
      />
      <ConfirmDialog
        open={confirm === "retrain"}
        title="Retrain all models?"
        message="This trains brand-new models on the base dataset plus all verified feedback rows, replacing the currently active models. Retraining is resource-intensive and cannot be undone."
        confirmLabel="Retrain"
        variant="warning"
        onConfirm={() => retrain.mutate()}
        onCancel={() => setConfirm(null)}
      />
    </div>
  );
}