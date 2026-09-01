"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, fmt } from "@/lib/api";
import { Badge, Button, Card, ConfirmDialog, inputCls, Spinner, Stat } from "@/components/ui";
import { PanSelect } from "./common";
import { useLang } from "@/lib/i18n";

const ACTIONS = [
  { key: "no_action", label: "No action taken" },
  { key: "harvest", label: "Harvested" },
  { key: "covered_pans", label: "Covered pans / stockpile" },
  { key: "protected_pan", label: "Protected the pan (tarpaulin / bunds)" },
  { key: "pumped_water", label: "Pumped water" },
  { key: "stored_brine", label: "Stored brine" },
  { key: "transferred_brine", label: "Transferred brine to reserve" },
  { key: "drained_pan", label: "Drained the pan" },
];

export default function OutcomesPanel() {
  const qc = useQueryClient();
  const { lang } = useLang();
  const { data: pans } = useQuery({ queryKey: ["pans"], queryFn: api.pans });
  const predictions = useQuery({ queryKey: ["predictions"], queryFn: () => api.predictions() });
  const recsQ = useQuery({ queryKey: ["recs", undefined, "pending"], queryFn: () => api.recommendations(undefined, "pending") });

  const [panId, setPanId] = useState<number>(0);
  const selected = pans?.find((p) => p.id === panId) ?? pans?.[0];

  const [form, setForm] = useState<Record<string, string>>({
    outcome_date: new Date().toISOString().slice(0, 10),
    actual_rainfall_mm: "",
    action_taken: "no_action",
    pump_duration_min: "",
    transferred_volume_l: "",
    protection_applied: "false",
    harvest_date: "",
    actual_yield_kg: "",
    salt_purity_pct: "",
    rain_damage: "",
    yield_loss_pct: "",
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
        pump_duration_min: form.pump_duration_min ? Number(form.pump_duration_min) : null,
        transferred_volume_l: form.transferred_volume_l ? Number(form.transferred_volume_l) : null,
        protection_applied: form.protection_applied === "true",
        harvest_date: form.harvest_date || null,
        actual_yield_kg: form.actual_yield_kg ? Number(form.actual_yield_kg) : null,
        salt_purity_pct: form.salt_purity_pct ? Number(form.salt_purity_pct) : null,
        rain_damage: form.rain_damage ? form.rain_damage === "true" : null,
        yield_loss_pct: form.yield_loss_pct ? Number(form.yield_loss_pct) : null,
        brine_density_be: form.brine_density_be ? Number(form.brine_density_be) : null,
        salt_thickness_mm: form.salt_thickness_mm ? Number(form.salt_thickness_mm) : null,
        notes: form.notes,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["outcomes"] });
      qc.invalidateQueries({ queryKey: ["status"] });
      qc.invalidateQueries({ queryKey: ["recs"] });
      setForm((f) => ({
        ...f,
        actual_rainfall_mm: "",
        actual_yield_kg: "",
        salt_purity_pct: "",
        yield_loss_pct: "",
        pump_duration_min: "",
        transferred_volume_l: "",
        protection_applied: "false",
        rain_damage: "",
        notes: "",
      }));
    },
  });

  const verify = useMutation({
    mutationFn: api.verifyOutcome,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["outcomes"] });
      qc.invalidateQueries({ queryKey: ["eval-summary"] });
    },
  });
  const [verifyTarget, setVerifyTarget] = useState<number | null>(null);

  const toggle = (k: string, value?: string) =>
    set(k, value ?? "false" ? (form[k] === "true" ? "false" : "true") : "");

  return (
    <div className="space-y-5">
      <Card
        title="Record actual outcome"
        subtitle="Field ground truth: action, pump/transfer/protection, rainfall, harvest and yield quality"
        right={<div className="w-56"><PanSelect value={selected?.id ?? 0} onChange={setPanId} /></div>}
      >
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-400">Date</span>
            <input className={inputCls} type="date" value={form.outcome_date} onChange={(e) => set("outcome_date", e.target.value)} />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-400">Actual action</span>
            <select className={inputCls} value={form.action_taken} onChange={(e) => set("action_taken", e.target.value)}>
              {ACTIONS.map((a) => <option key={a.key} value={a.key}>{a.label}</option>)}
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-400">Pump duration (min)</span>
            <input className={inputCls} type="number" step="any" min={0} value={form.pump_duration_min}
              onChange={(e) => set("pump_duration_min", e.target.value)} placeholder="e.g. 120" />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-400">Transferred volume (L)</span>
            <input className={inputCls} type="number" step="any" min={0} value={form.transferred_volume_l}
              onChange={(e) => set("transferred_volume_l", e.target.value)} placeholder="e.g. 45000" />
          </label>
          <label className="block md:col-span-2">
            <span className="mb-1 block text-xs font-medium text-slate-400">Protection event</span>
            <button
              type="button"
              onClick={() => set("protection_applied", form.protection_applied === "true" ? "false" : "true")}
              className={`${inputCls} flex items-center gap-2 text-left`}
            >
              <span className={`inline-block h-3 w-6 rounded-full ${form.protection_applied === "true" ? "bg-emerald-400" : "bg-white/15"}`}>
                <span className={`block h-3 w-3 rounded-full bg-white transition-transform ${form.protection_applied === "true" ? "translate-x-3" : ""}`} />
              </span>
              <span className={form.protection_applied === "true" ? "text-emerald-300" : "text-slate-400"}>
                {form.protection_applied === "true" ? "Protection applied" : "No protection"}
              </span>
            </button>
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-400">Actual rainfall (mm)</span>
            <input className={inputCls} type="number" step="any" min={0} value={form.actual_rainfall_mm}
              onChange={(e) => set("actual_rainfall_mm", e.target.value)} placeholder="0" />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-400">Harvest date</span>
            <input className={inputCls} type="date" value={form.harvest_date} onChange={(e) => set("harvest_date", e.target.value)} />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-400">Actual yield (kg)</span>
            <input className={inputCls} type="number" step="any" min={0} value={form.actual_yield_kg}
              onChange={(e) => set("actual_yield_kg", e.target.value)} placeholder="e.g. 90000" />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-400">Salt purity (%)</span>
            <input className={inputCls} type="number" step="any" min={0} max={100} value={form.salt_purity_pct}
              onChange={(e) => set("salt_purity_pct", e.target.value)} placeholder="e.g. 97" />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-400">Rain damage</span>
            <button
              type="button"
              onClick={() => set("rain_damage", form.rain_damage === "true" ? "false" : "true")}
              className={`${inputCls} flex items-center gap-2 text-left`}
            >
              <span className={`inline-block h-3 w-6 rounded-full ${form.rain_damage === "true" ? "bg-red-400" : "bg-white/15"}`}>
                <span className={`block h-3 w-3 rounded-full bg-white transition-transform ${form.rain_damage === "true" ? "translate-x-3" : ""}`} />
              </span>
              <span className={form.rain_damage === "true" ? "text-red-300" : "text-slate-400"}>
                {form.rain_damage === "true" ? "Damaged by rain" : "No rain damage"}
              </span>
            </button>
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-400">Yield loss (%)</span>
            <input className={inputCls} type="number" step="any" min={0} max={100} value={form.yield_loss_pct}
              onChange={(e) => set("yield_loss_pct", e.target.value)} placeholder="e.g. 12" />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-400">Brine density (°Bé)</span>
            <input className={inputCls} type="number" step="any" value={form.brine_density_be}
              onChange={(e) => set("brine_density_be", e.target.value)} placeholder="26.0" />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-400">Salt thickness (mm)</span>
            <input className={inputCls} type="number" step="any" value={form.salt_thickness_mm}
              onChange={(e) => set("salt_thickness_mm", e.target.value)} placeholder="14.0" />
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
          <label className="block">
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
            <input className={inputCls} value={form.notes} onChange={(e) => set("notes", e.target.value)}
              placeholder="Weather observations, losses, quality…" />
          </label>
        </div>

        <div className="mt-4">
          <Button onClick={() => submit.mutate()} disabled={submit.isPending || !selected}>
            {submit.isPending ? "Saving…" : "Record outcome"}
          </Button>
          <span className="ml-3 text-xs text-slate-500">
            Outcomes ≥ 15 mm rain auto-flag as a rain-damage event; completing one closes any linked
            recommendation.
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
                  <th className="py-2 pr-3">Date</th>
                  <th className="py-2 pr-3">Action</th>
                  <th className="py-2 pr-3">Pump</th>
                  <th className="py-2 pr-3">Transfer</th>
                  <th className="py-2 pr-3">Protect</th>
                  <th className="py-2 pr-3">Rain</th>
                  <th className="py-2 pr-3">Damage</th>
                  <th className="py-2 pr-3">Yield</th>
                  <th className="py-2 pr-3">Purity</th>
                  <th className="py-2 pr-3">Loss</th>
                  <th className="py-2 pr-3">Verified</th>
                  <th className="py-2 text-right">Verify</th>
                </tr>
              </thead>
              <tbody>
                {(outcomes.data ?? []).map((o) => (
                  <tr key={o.id} className="border-b border-white/5">
                    <td className="py-2 pr-3 text-slate-300">{fmt.date(o.outcome_date)}</td>
                    <td className="py-2 pr-3 text-slate-300">{o.action_taken.replaceAll("_", " ") || "—"}</td>
                    <td className="py-2 pr-3 tabular-nums text-slate-300">{fmt.hours(o.pump_duration_min)}</td>
                    <td className="py-2 pr-3 tabular-nums text-slate-300">{fmt.lit(o.transferred_volume_l)}</td>
                    <td className="py-2 pr-3 text-slate-300">
                      {o.protection_applied ? <span className="text-emerald-400">yes</span> : "—"}
                    </td>
                    <td className="py-2 pr-3 tabular-nums text-slate-300">{fmt.mm(o.actual_rainfall_mm)}</td>
                    <td className="py-2 pr-3">
                      <Badge className={o.rain_damage ? "border-red-500/40 bg-red-500/15 text-red-300" : "border-emerald-500/40 bg-emerald-500/15 text-emerald-300"}>
                        {o.rain_damage ? "yes" : "no"}
                      </Badge>
                    </td>
                    <td className="py-2 pr-3 tabular-nums text-slate-300">{fmt.kg(o.actual_yield_kg)} kg</td>
                    <td className="py-2 pr-3 tabular-nums text-slate-300">
                      {o.salt_purity_pct != null ? `${o.salt_purity_pct.toFixed(0)}%` : "—"}
                    </td>
                    <td className="py-2 pr-3 tabular-nums text-slate-300">
                      {o.yield_loss_pct != null ? `${o.yield_loss_pct.toFixed(0)}%` : "—"}
                    </td>
                    <td className="py-2 pr-3">
                      <Badge className={o.verified ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-300" : "border-amber-500/40 bg-amber-500/15 text-amber-300"}>
                        {o.verified ? "verified" : "pending"}
                      </Badge>
                    </td>
                    <td className="py-2 text-right">
                      {!o.verified && (
                        <Button variant="ghost" disabled={verify.isPending} onClick={() => setVerifyTarget(o.id)}>
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

      <ConfirmDialog
        open={verifyTarget !== null}
        title="Verify this outcome?"
        message="Verified outcomes are treated as field ground truth and — once digested — populate the training pool that future retraining runs on. This cannot be undone."
        confirmLabel="Verify"
        variant="warning"
        onConfirm={() => verifyTarget !== null && verify.mutate(verifyTarget)}
        onCancel={() => setVerifyTarget(null)}
      />
    </div>
  );
}