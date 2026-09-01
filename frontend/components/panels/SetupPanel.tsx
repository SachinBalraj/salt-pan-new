"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { api, fmt } from "@/lib/api";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  inputCls,
  Spinner,
} from "@/components/ui";
import type { DataSet, MlModel, SaltPan } from "@/lib/types";

const STEPS = [
  { key: "pan", label: "Create a salt pan" },
  { key: "upload", label: "Upload datasets" },
  { key: "validate", label: "Validate data" },
  { key: "train", label: "Train model" },
  { key: "activate", label: "Activate model" },
  { key: "done", label: "View dashboard" },
] as const;

type StepKey = (typeof STEPS)[number]["key"];

const STATUS_OK = new Set(["valid", "promoted", "imported", "needs_review"]);

export default function SetupPanel({
  onFinish,
}: {
  onFinish?: () => void;
}) {
  const qc = useQueryClient();
  const { data: status } = useQuery({ queryKey: ["status"], queryFn: api.status });
  const { data: pans } = useQuery({ queryKey: ["pans"], queryFn: api.pans });
  const { data: datasets } = useQuery({ queryKey: ["datasets"], queryFn: api.datasets });
  const { data: models } = useQuery({ queryKey: ["models"], queryFn: api.models });

  const [step, setStep] = useState<StepKey>("pan");
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const havePans = (pans ?? []).length > 0;
  const uploaded = (datasets ?? []).filter((d) => d.source !== "generated" || d.status === "imported");
  const uploadReady = (datasets ?? []).some((d) => STATUS_OK.has(d.status));
  const trainedOk = (models ?? []).some((m) => m.status === "trained" || m.status === "active");
  const activeOk = !!status?.any_active_model;

  const isComplete = (k: StepKey): boolean =>
    k === "pan" ? havePans
      : k === "upload" ? (datasets ?? []).length > 0
        : k === "validate" ? uploadReady
          : k === "train" ? trainedOk
            : k === "activate" ? activeOk
              : true;

  const stepIndex = STEPS.findIndex((s) => s.key === step);
  const nextStep = (): StepKey => STEPS[Math.min(stepIndex + 1, STEPS.length - 1)].key;

  // ---- pan creation -------------------------------------------------------
  const [panForm, setPanForm] = useState({
    pan_id: "",
    name: "",
    location: "",
    area_m2: "1000",
  });
  const createPan = useMutation({
    mutationFn: () =>
      api.createPan({
        pan_id: panForm.pan_id.trim().toUpperCase().replace(/\s+/g, "-"),
        name: panForm.name.trim(),
        location: panForm.location.trim(),
        area_m2: Number(panForm.area_m2 || 1000),
      }),
    onSuccess: () => {
      setMsg({ kind: "ok", text: "Salt pan created. Moving to the upload step." });
      qc.invalidateQueries({ queryKey: ["pans"] });
      qc.invalidateQueries({ queryKey: ["status"] });
      setStep("upload");
    },
    onError: (e: Error) => setMsg({ kind: "err", text: e.message }),
  });

  // ---- upload + validate --------------------------------------------------
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [uploadedId, setUploadedId] = useState<number | null>(null);
  const preview = useMutation({
    mutationFn: (f: File) => api.previewUpload(f),
    onSuccess: () => setMsg({ kind: "ok", text: "File analysed. Review then upload." }),
    onError: (e: Error) => setMsg({ kind: "err", text: e.message }),
  });
  const uploadDs = useMutation({
    mutationFn: (f: File) => api.uploadDataset(f),
    onSuccess: (ds: DataSet) => {
      setUploadedId(ds.id);
      setMsg({ kind: "ok", text: `Uploaded ${ds.filename} (${ds.rows_count} rows, ${ds.status}).` });
      qc.invalidateQueries({ queryKey: ["datasets"] });
      setStep("validate");
    },
    onError: (e: Error) => setMsg({ kind: "err", text: e.message }),
  });
  const validate = useMutation({
    mutationFn: api.validateDataset,
    onSuccess: () => {
      setMsg({ kind: "ok", text: "Dataset validated. You can now train a model." });
      qc.invalidateQueries({ queryKey: ["datasets"] });
      setStep("train");
    },
    onError: (e: Error) => setMsg({ kind: "err", text: e.message }),
  });

  // ---- train + activate ---------------------------------------------------
  const train = useMutation({
    mutationFn: () => api.train({ kind: "all" }),
    onSuccess: (created: MlModel[]) => {
      const ok = created.filter((m) => m.status === "trained").length;
      const deferred = created.filter((m) => m.status === "deferred").length;
      setMsg({
        kind: "ok",
        text: `Training finished: ${ok} model(s) trained${deferred ? `, ${deferred} deferred (insufficient verified outcomes)` : ""}.`,
      });
      qc.invalidateQueries({ queryKey: ["models"] });
      qc.invalidateQueries({ queryKey: ["status"] });
      setStep("activate");
    },
    onError: (e: Error) => setMsg({ kind: "err", text: e.message }),
  });

  const activate = useMutation({
    mutationFn: async () => {
      const list = (await api.models()).filter((m) => m.status !== "deferred");
      const latest = list.sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
      if (!latest) throw new Error("No trained model to activate");
      return api.activateModel(latest.id);
    },
    onSuccess: () => {
      setMsg({ kind: "ok", text: "Model activated. You are ready to use the dashboard." });
      qc.invalidateQueries({ queryKey: ["models"] });
      qc.invalidateQueries({ queryKey: ["status"] });
      qc.invalidateQueries({ queryKey: ["label-status"] });
      setStep("done");
    },
    onError: (e: Error) => setMsg({ kind: "err", text: e.message }),
  });

  const onFile = (f: File | null) => {
    setFile(f);
    setMsg(null);
    setUploadedId(null);
    if (f) preview.mutate(f);
  };

  const msgEl = msg && (
    <p className={`mt-3 text-sm ${msg.kind === "ok" ? "text-emerald-400" : "text-red-400"}`}>
      {msg.text}
    </p>
  );

  return (
    <div className="space-y-5">
      <Card
        title="First-run setup"
        subtitle="Guided onboarding: pan → data → validate → train → activate → dashboard"
      >
        <div className="grid gap-6 lg:grid-cols-[240px_1fr]">
          {/* stepper */}
          <ol className="space-y-1.5">
            {STEPS.map((s, i) => {
              const done = isComplete(s.key);
              const current = s.key === step;
              return (
                <li key={s.key}>
                  <button
                    onClick={() => checkPoint(s.key)}
                    className={`w-full rounded-lg border px-3 py-2 text-left text-sm transition ${
                      current
                        ? "border-brine-500/40 bg-brine-500/10 text-brine-200"
                        : done
                          ? "border-emerald-500/30 bg-emerald-500/5 text-emerald-300"
                          : "border-white/10 text-slate-400 hover:bg-white/5"
                    }`}
                  >
                    <span className="mr-2 inline-flex h-5 w-5 items-center justify-center rounded-full border border-current text-[10px]">
                      {done ? "✓" : i + 1}
                    </span>
                    {s.label}
                  </button>
                </li>
              );
            })}
          </ol>

          {/* step body */}
          <div className="min-h-[280px]">
            {step === "pan" && (
              <div className="space-y-4">
                <p className="text-sm text-slate-400">
                  Register the physical salt pan. Pan code and name are required;
                  area drives volume and yield estimates.
                </p>
                <div className="grid max-w-xl grid-cols-1 gap-3 sm:grid-cols-2">
                  <label className="block">
                    <span className="mb-1 block text-xs font-medium text-slate-400">Pan code</span>
                    <input className={inputCls} placeholder="PAN-4" value={panForm.pan_id}
                      onChange={(e) => setPanForm((f) => ({ ...f, pan_id: e.target.value }))} />
                  </label>
                  <label className="block">
                    <span className="mb-1 block text-xs font-medium text-slate-400">Name</span>
                    <input className={inputCls} placeholder="Cuddalore crystalliser" value={panForm.name}
                      onChange={(e) => setPanForm((f) => ({ ...f, name: e.target.value }))} />
                  </label>
                  <label className="block">
                    <span className="mb-1 block text-xs font-medium text-slate-400">Location</span>
                    <input className={inputCls} placeholder="Cuddalore, Tamil Nadu" value={panForm.location}
                      onChange={(e) => setPanForm((f) => ({ ...f, location: e.target.value }))} />
                  </label>
                  <label className="block">
                    <span className="mb-1 block text-xs font-medium text-slate-400">Area (m²)</span>
                    <input className={inputCls} type="number" min={100} step="any" value={panForm.area_m2}
                      onChange={(e) => setPanForm((f) => ({ ...f, area_m2: e.target.value }))} />
                  </label>
                </div>
                <div className="flex items-center gap-3">
                  <Button onClick={() => createPan.mutate()} disabled={createPan.isPending || !panForm.pan_id || !panForm.name}>
                    {createPan.isPending ? "Creating…" : "Create salt pan"}
                  </Button>
                  {havePans && (
                    <Button variant="ghost" onClick={() => setStep("upload")}>
                      Pan already exists → skip
                    </Button>
                  )}
                </div>
              </div>
            )}

            {step === "upload" && (
              <div className="space-y-4">
                <p className="text-sm text-slate-400">
                  Upload a CSV/TSV dataset of sensor, weather, operations or combined rows. It is
                  analysed before being stored.
                </p>
                <div className="flex flex-wrap items-center gap-3">
                  <input ref={fileRef} type="file" accept=".csv,.tsv"
                    className="text-sm text-slate-400 file:mr-3 file:rounded-lg file:border-0 file:bg-brine-500/20 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-brine-300"
                    onChange={(e) => onFile(e.target.files?.[0] ?? null)} />
                  {(preview.isPending || uploadDs.isPending) && <Spinner label="Analysing…" />}
                </div>
                {preview.isError && <p className="text-xs text-red-400">{preview.error.message}</p>}
                {preview.data && (
                  <div className="rounded-lg border border-white/5 bg-black/20 p-3 text-xs">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge className="bg-sky-500/15 text-sky-300 border-sky-500/40">
                        {preview.data.dataset_type} · {Math.round(preview.data.detection_confidence * 100)}%
                      </Badge>
                      <Badge className={preview.data.errors.length
                        ? "border-red-500/40 bg-red-500/15 text-red-300"
                        : "border-emerald-500/40 bg-emerald-500/15 text-emerald-300"}>
                        {preview.data.errors.length
                          ? `${preview.data.errors.length} blocking issue(s)`
                          : `${preview.data.mappings.length} columns mapped`}
                      </Badge>
                      <span className="text-slate-400">
                        {preview.data.sample_rows.length} sample rows · {preview.data.duplicates} duplicates
                      </span>
                      <Button
                        disabled={uploadDs.isPending || !!preview.data.errors.length || !file}
                        onClick={() => file && uploadDs.mutate(file)}
                      >
                        {uploadDs.isPending ? "Uploading…" : "Upload dataset"}
                      </Button>
                    </div>
                    {preview.data.warnings.map((w) => (
                      <p key={w} className="mt-1 text-amber-400">• {w}</p>
                    ))}
                  </div>
                )}
                {(datasets ?? []).length > 0 && (
                  <p className="text-xs text-slate-500">
                    {(datasets ?? []).length} registered dataset(s). You can also skip ahead — an
                    AUTO_SEED demo dataset may already exist.
                  </p>
                )}
              </div>
            )}

            {step === "validate" && (
              <div className="space-y-4">
                <p className="text-sm text-slate-400">
                  Run the validator against the uploaded dataset so it can be promoted to a
                  training source. Invalid rows are quarantined, not deleted.
                </p>
                {(datasets ?? []).length === 0 ? (
                  <EmptyState>No dataset uploaded yet — return to Step 2.</EmptyState>
                ) : (
                  <ul className="space-y-2">
                    {(datasets ?? []).map((d) => (
                      <li key={d.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-white/5 bg-black/20 px-3 py-2 text-xs">
                        <span className="text-slate-300">
                          #{d.id} {d.name} · {d.rows_count.toLocaleString()} rows ·{" "}
                          <Badge className={
                            d.status === "invalid"
                              ? "border-red-500/40 bg-red-500/15 text-red-300"
                              : STATUS_OK.has(d.status)
                                ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-300"
                                : "border-amber-500/40 bg-amber-500/15 text-amber-300"
                          }>{d.status}</Badge>
                        </span>
                        {d.status !== "invalid" && (
                          <Button variant="ghost" disabled={validate.isPending} onClick={() => validate.mutate(d.id)}>
                            Validate
                          </Button>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
                {uploadReady && (
                  <Button variant="ghost" onClick={() => setStep("train")}>
                    Validation passed → continue
                  </Button>
                )}
              </div>
            )}

            {step === "train" && (
              <div className="space-y-4">
                <p className="text-sm text-slate-400">
                  Train the five model kinds (harvest readiness, climate risk, their classifiers and
                  the harvest-time regressor). Models needing more verified field outcomes are
                  deferred, not faked.
                </p>
                <div className="flex items-center gap-3">
                  <Button onClick={() => train.mutate()} disabled={train.isPending}>
                    {train.isPending ? "Training…" : "Train all models"}
                  </Button>
                  {trainedOk && (
                    <Button variant="ghost" onClick={() => setStep("activate")}>
                      Models exist → continue
                    </Button>
                  )}
                </div>
                {trainedOk && (
                  <p className="text-xs text-emerald-400">
                    {(models ?? []).filter((m) => m.status === "trained" || m.status === "active").length}
                    {" "}trained model(s) are available.
                  </p>
                )}
              </div>
            )}

            {step === "activate" && (
              <div className="space-y-4">
                <p className="text-sm text-slate-400">
                  Activate the latest trained model so predictions and recommendations become live.
                </p>
                {activeOk ? (
                  <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300">
                    An active model is already running.
                    <Button className="ml-3" variant="ghost" onClick={() => setStep("done")}>
                      Continue
                    </Button>
                  </div>
                ) : (
                  <div className="flex items-center gap-3">
                    <Button onClick={() => activate.mutate()} disabled={activate.isPending || !trainedOk}>
                      {activate.isPending ? "Activating…" : "Activate model"}
                    </Button>
                    {!trainedOk && <span className="text-xs text-slate-500">Train a model first.</span>}
                  </div>
                )}
              </div>
            )}

            {step === "done" && (
              <div className="space-y-4">
                <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 py-3">
                  <p className="text-sm font-bold text-emerald-300">Setup complete 🎉</p>
                  <p className="mt-1 text-sm text-slate-300">
                    Your salt pan is registered, data is validated, and an active model is issuing
                    recommendations. Open the dashboard, pan details or what-if simulator whenever
                    you are ready.
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <Button variant="success" onClick={() => onFinish?.()}>
                    View dashboard →
                  </Button>
                  <Button variant="ghost" onClick={() => setStep("pan")}>
                    Back to step 1
                  </Button>
                </div>
              </div>
            )}

            {msgEl}
          </div>
        </div>
      </Card>

      {/* live checklist */}
      <Card title="Setup status" subtitle="Live state of each onboarding step">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
          {STEPS.map((s) => (
            <div key={s.key} className="rounded-lg border border-white/5 bg-black/20 p-3">
              <div className="text-[11px] uppercase tracking-wider text-slate-500">{s.label}</div>
              <div className="mt-1 text-sm font-semibold text-slate-200">
                {isComplete(s.key) ? "Done" : "Pending"}
              </div>
            </div>
          ))}
        </div>
        <p className="mt-3 text-xs text-slate-500">
          Pans: {havePans ? `${pans?.length} registered` : "none"} · Datasets: {(datasets ?? []).length} · Models: {(models ?? []).length} · Active model: {activeOk ? "yes" : "no"}
        </p>
      </Card>
    </div>
  );

  function checkPoint(k: StepKey) {
    // allow jumping backward freely; forward only if the step is complete.
    const idx = STEPS.findIndex((s) => s.key === k);
    if (idx < stepIndex) {
      setStep(k);
      setMsg(null);
    } else if (isComplete(STEPS[idx - 1]?.key ?? "pan")) {
      setStep(k);
      setMsg(null);
    }
  }
}