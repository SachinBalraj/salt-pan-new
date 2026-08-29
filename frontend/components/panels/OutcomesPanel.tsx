"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, fmt } from "@/lib/api";
import { Badge, Button, Card, inputCls, Spinner, Stat } from "@/components/ui";
import { PanSelect } from "./common";

export default function OutcomesPanel() {
  const qc = useQueryClient();
  const { data: pans } = useQuery({ queryKey: ["pans"], queryFn: api.pans });
  const predictions = useQuery({ queryKey: ["predictions"], queryFn: () => api.predictions() });
  const recsQ = useQuery({ queryKey: ["recs", undefined, "pending"], queryFn: () => api.recommendations(undefined, "pending") });

  const [panId, setPanId] = useState<number>(0);
  const selected = pans?.find((p) => p.id === panId) ?? pans?.[0];

  const [form, setForm] = useState<Record<string, string>>({
    outcome_date: new Date().toISOString().slice(0, 10),
    actual_rainfall_mm: "",
    action_taken: "no_action",
    harvest_date: "",
    actual_yield_kg: "",
    brine_density_be: "",
    salt_thickness_mm: "",
    prediction_id: "",
    recommendation_id: "",
    notes: "",
  });
  const set = (k: string, v: string) => setForm((f) => ({ ...f, [k]: v }));

  const outcomes = useQuery({
    queryKey: ["outcomes", selected?.id],
    queryFn: () => api.outcomes(selected?.id ?? undefined),
    enabled: !pans || pans.length > 0,
  });

  const submit = useMutation({
    mutationFn: () =>
      api.createOutcome({
        pan_id: selected!.id,
        ...(form.prediction_id ? { prediction_id: Number(form.prediction_id) } : {}),
        ...(form.recommendation_id ? { recommendation_id: Number(form.recommendation_id) } : {}),
        outcome_date: form.outcome_date,
        actual_rainfall_mm: Number(form.actual_rainfall_mm || 0),
        action_taken: form.action_taken,
        harvest_date: form.harvest_date || null,
        actual_yield_kg: form.actual_yield_kg ? Number(form.actual_yield_kg) : null,
        brine_density_be: form.brine_density_be ? Number(form.brine_density_be) : null,
        salt_thickness_mm: form.salt_thickness_mm ? Number(form.salt_thickness_mm) : null,
        notes: form.notes,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["outcomes"] });
      qc.invalidateQueries({ queryKey: ["status"] });
      setForm((f) => ({ ...f, actual_rainfall_mm: "", actual_yield_kg: "", notes: "" }));
    },
  });

  const verify = useMutation({
    mutationFn: api.verifyOutcome,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["outcomes"] });
      qc.invalidateQueries({ queryKey: ["eval-summary"] });
    },
  });

  return (
    <div className="space-y-5">
      <Card
        title="Record actual outcome"
        subtitle="Ground truth from the field: rainfall, action taken, harvest date and yield"
        right={<div className="w-56"><PanSelect value={selected?.id ?? 0} onChange={setPanId} /></div>}
      >
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-400">Date</span>
            <input className={inputCls} type="date" value={form.outcome_date} onChange={(e) => set("outcome_date", e.target.value)} />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-400">Actual rainfall (mm)</span>
            <input className={inputCls} type="number" step="any" min={0} value={form.actual_rainfall_mm} onChange={(e) => set("actual_rainfall_mm", e.target.value)} placeholder="0" />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-400">Action taken</span>
            <select className={inputCls} value={form.action_taken} onChange={(e) => set("action_taken", e.target.value)}>
              <option value="no_action">No action</option>
              <option value="harvest">Harvested</option>
              <option value="covered_pans">Covered pans / stockpile</option>
              <option value="pumped_water">Pumped water</option>
              <option value="stored_brine">Stored brine</option>
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-400">Harvest date</span>
            <input className={inputCls} type="date" value={form.harvest_date} onChange={(e) => set("harvest_date", e.target.value)} />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-400">Actual yield (kg)</span>
            <input className={inputCls} type="number" step="any" min={0} value={form.actual_yield_kg} onChange={(e) => set("actual_yield_kg", e.target.value)} placeholder="e.g. 90000" />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-400">Brine density (°Bé)</span>
            <input className={inputCls} type="number" step="any" value={form.brine_density_be} onChange={(e) => set("brine_density_be", e.target.value)} placeholder="26.0" />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-400">Salt thickness (mm)</span>
            <input className={inputCls} type="number" step="any" value={form.salt_thickness_mm} onChange={(e) => set("salt_thickness_mm", e.target.value)} placeholder="14.0" />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-400">Linked prediction</span>
            <select className={inputCls} value={form.prediction_id} onChange={(e) => set("prediction_id", e.target.value)}>
              <option value="">None</option>
              {(predictions.data ?? []).slice(0, 12).map((p) => (
                <option key={p.id} value={p.id}>Prediction #{p.id} ({p.prediction_date})</option>
              ))}
            </select>
          </label>
          <label className="block md:col-span-2">
            <span className="mb-1 block text-xs font-medium text-slate-400">Linked recommendation</span>
            <select className={inputCls} value={form.recommendation_id} onChange={(e) => set("recommendation_id", e.target.value)}>
              <option value="">None</option>
              {(recsQ.data ?? []).slice(0, 12).map((r) => (
                <option key={r.id} value={r.id}>Rec #{r.id} — {r.title}</option>
              ))}
            </select>
          </label>
          <label className="block md:col-span-2">
            <span className="mb-1 block text-xs font-medium text-slate-400">Notes</span>
            <input className={inputCls} value={form.notes} onChange={(e) => set("notes", e.target.value)} placeholder="Weather observations, losses, quality…" />
          </label>
        </div>
        <div className="mt-4">
          <Button onClick={() => submit.mutate()} disabled={submit.isPending || !selected}>
            {submit.isPending ? "Saving…" : "Record outcome"}
          </Button>
          <span className="ml-3 text-xs text-slate-500">
            Outcomes ≥ 15 mm rain are auto-flagged as a risk occurrence.
          </span>
        </div>
      </Card>

      <Card title="Recorded outcomes" subtitle="Verify field data to feed the evaluation & feedback loop">
        {outcomes.isLoading ? (
          <Spinner label="Loading outcomes…" />
        ) : (outcomes.data ?? []).length === 0 ? (
          <p className="text-sm text-slate-500">No outcomes recorded yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-white/10 text-[11px] uppercase tracking-wider text-slate-500">
                  <th className="py-2 pr-3">ID</th>
                  <th className="py-2 pr-3">Date</th>
                  <th className="py-2 pr-3">Rain</th>
                  <th className="py-2 pr-3">Risk</th>
                  <th className="py-2 pr-3">Action</th>
                  <th className="py-2 pr-3">Yield</th>
                  <th className="py-2 pr-3">Verified</th>
                  <th className="py-2 text-right">Verify</th>
                </tr>
              </thead>
              <tbody>
                {(outcomes.data ?? []).map((o) => (
                  <tr key={o.id} className="border-b border-white/5">
                    <td className="py-2 pr-3 text-slate-500">#{o.id}</td>
                    <td className="py-2 pr-3 text-slate-300">{fmt.date(o.outcome_date)}</td>
                    <td className="py-2 pr-3 tabular-nums text-slate-300">{fmt.mm(o.actual_rainfall_mm)}</td>
                    <td className="py-2 pr-3">
                      <Badge className={o.risk_occurred ? "border-red-500/40 bg-red-500/15 text-red-300" : "border-emerald-500/40 bg-emerald-500/15 text-emerald-300"}>
                        {o.risk_occurred ? "occurred" : "no"}
                      </Badge>
                    </td>
                    <td className="py-2 pr-3 text-slate-300">{o.action_taken || "—"}</td>
                    <td className="py-2 pr-3 tabular-nums text-slate-300">{fmt.kg(o.actual_yield_kg)} kg</td>
                    <td className="py-2 pr-3">
                      <Badge className={o.verified ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-300" : "border-amber-500/40 bg-amber-500/15 text-amber-300"}>
                        {o.verified ? "verified" : "pending"}
                      </Badge>
                    </td>
                    <td className="py-2 text-right">
                      {!o.verified && (
                        <Button variant="ghost" disabled={verify.isPending} onClick={() => verify.mutate(o.id)}>
                          Verify
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}