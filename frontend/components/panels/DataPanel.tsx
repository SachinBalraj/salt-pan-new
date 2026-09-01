"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { api } from "@/lib/api";
import type { UploadPreview } from "@/lib/types";
import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
  EmptyState,
  ErrorBanner,
  inputCls,
  Spinner,
} from "@/components/ui";

type Message = { kind: "ok" | "err"; text: string } | null;

const DATASET_TYPES = [
  { key: "", label: "Auto-detect" },
  { key: "sensor", label: "Pan sensor readings" },
  { key: "weather", label: "Weather / forecast" },
  { key: "operations", label: "Operations + harvest" },
  { key: "combined", label: "Combined master" },
];

function statusTone(status: string) {
  if (status === "valid" || status === "promoted" || status === "imported")
    return "border-emerald-500/40 bg-emerald-500/15 text-emerald-300";
  if (status === "invalid")
    return "border-red-500/40 bg-red-500/15 text-red-300";
  if (status === "needs_review")
    return "border-amber-500/40 bg-amber-500/15 text-amber-300";
  return "border-white/10 bg-white/5 text-slate-300";
}

function SampleTable({ rows }: { rows: Record<string, unknown>[] }) {
  if (!rows?.length) return <EmptyState>No sample rows.</EmptyState>;
  const cols = Object.keys(rows[0]);
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-xs">
        <thead>
          <tr className="border-b border-white/10 text-slate-500">
            {cols.slice(0, 14).map((c) => (
              <th key={c} className="px-2 py-1.5 whitespace-nowrap">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-white/5">
              {cols.slice(0, 14).map((c) => (
                <td key={c} className="px-2 py-1.5 tabular-nums text-slate-300">
                  {String(r[c] ?? "")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function DataPanel() {
  const qc = useQueryClient();
  const { data: datasets, isLoading } = useQuery({
    queryKey: ["datasets"],
    queryFn: api.datasets,
  });
  const fileRef = useRef<HTMLInputElement>(null);
  const [previewFor, setPreviewFor] = useState<number | null>(null);
  const [uploadedId, setUploadedId] = useState<number | null>(null);
  const [message, setMessage] = useState<Message>(null);
  const [file, setFile] = useState<File | null>(null);
  const [datasetType, setDatasetType] = useState("");
  const [confirmImport, setConfirmImport] = useState<number | null>(null);
  const [confirmPromote, setConfirmPromote] = useState<number | null>(null);

  const preview = useQuery({
    queryKey: ["preview", previewFor],
    queryFn: () => api.datasetPreview(previewFor!),
    enabled: !!previewFor,
  });

  const analyze = useMutation({
    mutationFn: (f: File) =>
      api.previewUpload(f, { dataset_type: datasetType || undefined }),
    onError: (e: Error) => setMessage({ kind: "err", text: e.message }),
  });
  const uploadDs = useMutation({
    mutationFn: (f: File) =>
      api.uploadDataset(f, { dataset_type: datasetType || undefined }),
    onSuccess: (ds) => {
      setUploadedId(ds.id);
      setFile(null);
      setMessage({
        kind: "ok",
        text: `Uploaded ${ds.filename} (${ds.rows_count} rows, status: ${ds.status}). Review below, then import.`,
      });
      qc.invalidateQueries({ queryKey: ["datasets"] });
    },
    onError: (e: Error) => setMessage({ kind: "err", text: e.message }),
  });

  const analysis = useQuery({
    queryKey: ["datasetAnalysis", uploadedId],
    queryFn: () => api.datasetAnalysis(uploadedId!),
    enabled: !!uploadedId,
  });

  const validate = useMutation({
    mutationFn: api.validateDataset,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["datasets"] }),
  });
  const promote = useMutation({
    mutationFn: api.promoteDataset,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["datasets"] }),
  });
  const importer = useMutation({
    mutationFn: (id: number) => api.importDataset(id),
    onSuccess: (res) => {
      setUploadedId(res.dataset.id);
      setMessage({
        kind: "ok",
        text: `Imported ${res.summary.imported_rows} rows into ${res.summary.tables.join(", ")}.`,
      });
      qc.invalidateQueries({ queryKey: ["datasets"] });
    },
    onError: (e: Error) => setMessage({ kind: "err", text: e.message }),
  });

  const onFile = (f: File | null) => {
    setFile(f);
    setMessage(null);
    if (f) analyze.mutate(f);
  };

  if (isLoading) return <Spinner label="Loading datasets…" />;

  const pv: UploadPreview | undefined = analyze.data;

  return (
    <div className="space-y-5">
      {/* Confirmation dialogs */}
      <ConfirmDialog
        open={confirmImport !== null}
        title="Import dataset?"
        message="This will import all valid rows into the operational tables (sensor readings, weather, operations). This action cannot be undone."
        confirmLabel="Import"
        variant="warning"
        onConfirm={() => {
          if (confirmImport !== null) importer.mutate(confirmImport);
          setConfirmImport(null);
        }}
        onCancel={() => setConfirmImport(null)}
      />
      <ConfirmDialog
        open={confirmPromote !== null}
        title="Promote to training source?"
        message="This will overwrite the current training dataset with this file's contents. Models trained later will use this data."
        confirmLabel="Promote"
        variant="warning"
        onConfirm={() => {
          if (confirmPromote !== null) promote.mutate(confirmPromote);
          setConfirmPromote(null);
        }}
        onCancel={() => setConfirmPromote(null)}
      />
      <Card
        title="Upload a salt-pan dataset"
        subtitle="CSV/TSV of sensor, weather, operations or combined daily rows. Analysed before anything is imported."
      >
        <div className="flex flex-wrap items-center gap-3">
          <select
            className={`${inputCls} w-auto`}
            value={datasetType}
            onChange={(e) => setDatasetType(e.target.value)}
          >
            {DATASET_TYPES.map((t) => (
              <option key={t.key} value={t.key} className="bg-slate-900">
                {t.label}
              </option>
            ))}
          </select>
          <input
            ref={fileRef}
            type="file"
            accept=".csv,.tsv"
            className="text-sm text-slate-400 file:mr-3 file:rounded-lg file:border-0 file:bg-brine-500/20 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-brine-300"
            onChange={(e) => onFile(e.target.files?.[0] ?? null)}
          />
          {(analyze.isPending || uploadDs.isPending) && <Spinner label="Analysing…" />}
          {message && (
            <span
              className={`text-sm ${
                message.kind === "ok" ? "text-emerald-400" : "text-red-400"
              }`}
            >
              {message.text}
            </span>
          )}
        </div>

        {pv && (
          <div className="mt-4 space-y-3">
            <div className="flex flex-wrap items-center gap-3">
              <Badge className="bg-sky-500/15 text-sky-300 border-sky-500/40">
                {pv.dataset_type} · {Math.round(pv.detection_confidence * 100)}% confidence
              </Badge>
              <Badge
                className={
                  pv.errors.length
                    ? "border-red-500/40 bg-red-500/15 text-red-300"
                    : pv.missing.length
                      ? "border-amber-500/40 bg-amber-500/15 text-amber-300"
                      : "border-emerald-500/40 bg-emerald-500/15 text-emerald-300"
                }
              >
                {pv.errors.length
                  ? "missing required columns"
                  : pv.missing.length
                    ? `${pv.missing.length} optional gap(s)`
                    : "ready"}
              </Badge>
              <Button
                variant="primary"
                disabled={uploadDs.isPending || !!pv.errors.length}
                onClick={() => file && uploadDs.mutate(file)}
              >
                {uploadDs.isPending ? "Uploading…" : "Upload for review"}
              </Button>
            </div>

            <div className="grid gap-3 md:grid-cols-2">
              <div className="rounded-lg border border-white/5 bg-black/20 p-3 text-xs">
                <div className="mb-1 font-semibold text-slate-200">
                  Column mapping ({pv.mappings.length} mapped · {pv.extra.length} extra)
                </div>
                <div className="max-h-40 space-y-0.5 overflow-y-auto font-mono">
                  {pv.mappings.map((m) => (
                    <div key={m.original} className="flex justify-between gap-2">
                      <span className="truncate text-slate-400">{m.original}</span>
                      <span className="text-slate-200">
                        → {m.canonical}
                        {m.converted && (
                          <span className="ml-1 text-amber-300">(unit)</span>
                        )}
                      </span>
                    </div>
                  ))}
                  {pv.extra.map((c) => (
                    <div key={c} className="flex justify-between gap-2">
                      <span className="truncate text-slate-400">{c}</span>
                      <span className="text-slate-600">ignored</span>
                    </div>
                  ))}
                </div>
                {!!pv.conversions.length && (
                  <div className="mt-1 text-amber-300">
                    {pv.conversions.map((c) => (
                      <div key={c.column}>• {c.note}</div>
                    ))}
                  </div>
                )}
              </div>

              <div className="rounded-lg border border-white/5 bg-black/20 p-3 text-xs">
                <div className="mb-1 font-semibold text-slate-200">
                  Required columns ({pv.required.length})
                </div>
                <div className="flex flex-wrap gap-1">
                  {pv.required.map((c) => {
                    const missing = pv.missing.includes(c);
                    return (
                      <span
                        key={c}
                        className={`rounded px-1.5 py-0.5 font-mono ${
                          missing
                            ? "bg-red-500/15 text-red-300"
                            : "bg-emerald-500/15 text-emerald-300"
                        }`}
                      >
                        {c}
                        {missing && " ✗"}
                      </span>
                    );
                  })}
                </div>
                {!!pv.duplicates && (
                  <div className="mt-2 text-red-400">
                    {pv.duplicates} duplicate (pan + timestamp) row(s) flagged.
                  </div>
                )}
                {!!pv.errors.length && (
                  <div className="mt-2 space-y-0.5 text-red-400">
                    {pv.errors.map((e) => (
                      <div key={e}>• {e}</div>
                    ))}
                  </div>
                )}
                {!!pv.warnings.length && (
                  <div className="mt-2 space-y-0.5 text-amber-400">
                    {pv.warnings.map((w) => (
                      <div key={w}>• {w}</div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            <div>
              <div className="mb-1 text-xs font-semibold text-slate-200">
                Preview (first rows)
              </div>
              <SampleTable rows={pv.sample_rows} />
            </div>
          </div>
        )}
      </Card>

      {(analysis.data || uploadedId) && (
        <Card
          title={`Analysis of dataset #${uploadedId ?? ""}`}
          subtitle={
            analysis.data
              ? `${analysis.data.valid_rows} valid · ${analysis.data.rejected_rows} rejected · ${analysis.data.duplicates} duplicates`
              : undefined
          }
        >
          {analysis.isLoading ? (
            <Spinner />
          ) : analysis.data ? (
            <div className="space-y-4">
              <div className="flex flex-wrap gap-3 text-xs">
                <Badge className={statusTone(analysis.data.status)}>
                  {analysis.data.status}
                </Badge>
                <Badge className="bg-sky-500/15 text-sky-300 border-sky-500/40">
                  {analysis.data.dataset_type}
                </Badge>
                <span className="text-slate-400">
                  Confidence {Math.round(analysis.data.detection_confidence * 100)}%
                </span>
              </div>

              <div className="grid gap-3 md:grid-cols-3">
                <div className="rounded-lg border border-white/5 bg-black/20 p-3 text-xs">
                  <div className="mb-1 font-semibold text-slate-200">Missing values</div>
                  {Object.keys(analysis.data.quality.missing ?? {}).length ? (
                    Object.entries(analysis.data.quality.missing ?? {}).map(([c, n]) => (
                      <div key={c} className="flex justify-between text-slate-400">
                        <span>{c}</span>
                        <span className="tabular-nums">{String(n)}</span>
                      </div>
                    ))
                  ) : (
                    <EmptyState>None</EmptyState>
                  )}
                </div>
                <div className="rounded-lg border border-white/5 bg-black/20 p-3 text-xs">
                  <div className="mb-1 font-semibold text-slate-200">
                    Outliers (report only)
                  </div>
                  {Object.keys(analysis.data.quality.outliers ?? {}).length ? (
                    Object.entries(analysis.data.quality.outliers ?? {}).map(([c, o]) => (
                      <div key={c} className="flex justify-between text-amber-300">
                        <span>{c}</span>
                        <span className="tabular-nums">{String(o.count)}</span>
                      </div>
                    ))
                  ) : (
                    <EmptyState>None</EmptyState>
                  )}
                </div>
                <div className="rounded-lg border border-white/5 bg-black/20 p-3 text-xs">
                  <div className="mb-1 font-semibold text-slate-200">Conversions</div>
                  {analysis.data.conversions.length ? (
                    analysis.data.conversions.map((c) => (
                      <div key={c.column} className="text-amber-300">
                        • {c.note}
                      </div>
                    ))
                  ) : (
                    <EmptyState>None</EmptyState>
                  )}
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <a
                  href={api.invalidRowsUrl(uploadedId!)}
                  className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-slate-200 hover:bg-white/10"
                  download
                >
                  Download invalid rows (CSV)
                </a>
                <Button
                  variant="primary"
                  disabled={
                    importer.isPending ||
                    analysis.data.status === "invalid" ||
                    analysis.data.valid_rows === 0
                  }
                  onClick={() => importer.mutate(uploadedId!)}
                >
                  {importer.isPending
                    ? "Importing…"
                    : analysis.data.valid_rows === 0
                      ? "Nothing to import"
                      : "Confirm import"}
                </Button>
                {importer.data && (
                  <span className="text-xs text-emerald-400">
                    Imported {importer.data.summary.imported_rows} rows into{" "}
                    {importer.data.summary.tables.join(", ")}
                    {importer.data.summary.created_pans.length
                      ? ` · created pans: ${importer.data.summary.created_pans.join(", ")}`
                      : ""}
                  </span>
                )}
              </div>
            </div>
          ) : (
            <EmptyState>Analysis failed.</EmptyState>
          )}
        </Card>
      )}

      <Card title="Registered datasets" subtitle="Uploads, generated samples and feedback pools">
        {(datasets ?? []).length === 0 ? (
          <EmptyState>No datasets yet — upload one above or restart with AUTO_SEED=true.</EmptyState>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-white/10 text-[11px] uppercase tracking-wider text-slate-500">
                  <th className="py-2 pr-4">ID</th>
                  <th className="py-2 pr-4">Name</th>
                  <th className="py-2 pr-4">Type</th>
                  <th className="py-2 pr-4">Source</th>
                  <th className="py-2 pr-4">Rows</th>
                  <th className="py-2 pr-4">Status</th>
                  <th className="py-2 pr-4">Uploaded</th>
                  <th className="py-2 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {datasets?.map((d) => (
                  <tr key={d.id} className="border-b border-white/5">
                    <td className="py-2 pr-4 text-slate-500">#{d.id}</td>
                    <td className="py-2 pr-4 font-medium text-slate-200">{d.name}</td>
                    <td className="py-2 pr-4 text-xs text-slate-400">
                      {d.dataset_type ?? "—"}
                    </td>
                    <td className="py-2 pr-4 text-slate-400">{d.source}</td>
                    <td className="py-2 pr-4 tabular-nums text-slate-300">
                      {d.rows_count.toLocaleString()}
                    </td>
                    <td className="py-2 pr-4">
                      <Badge className={statusTone(d.status)}>{d.status}</Badge>
                    </td>
                    <td className="py-2 pr-4 text-xs text-slate-500">
                      {new Date(d.created_at).toLocaleDateString()}
                    </td>
                    <td className="py-2 text-right">
                      <div className="flex justify-end gap-1.5">
                        <Button variant="ghost" onClick={() => setPreviewFor(d.id)}>
                          Preview
                        </Button>
                        <Button
                          variant="ghost"
                          disabled={validate.isPending}
                          onClick={() =>
                            validate.mutate(d.id, {
                              onSuccess: () =>
                                setMessage({ kind: "ok", text: `Re-validated dataset #${d.id}` }),
                            })
                          }
                        >
                          Validate
                        </Button>
                        <Button
                          variant="ghost"
                          disabled={importer.isPending || d.status === "imported"}
                          onClick={() =>
                            importer.mutate(d.id, {
                              onSuccess: () =>
                                setMessage({ kind: "ok", text: `Imported dataset #${d.id}` }),
                            })
                          }
                        >
                          {d.status === "imported" ? "Imported" : "Import"}
                        </Button>
                        <Button
                          variant="ghost"
                          disabled={promote.isPending || d.status === "promoted"}
                          onClick={() =>
                            promote.mutate(d.id, {
                              onSuccess: () =>
                                setMessage({
                                  kind: "ok",
                                  text: `Dataset #${d.id} promoted to training source.`,
                                }),
                            })
                          }
                        >
                          {d.status === "promoted" ? "Promoted" : "Promote"}
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {previewFor && (
        <Card
          title={`Dataset #${previewFor} preview`}
          subtitle={
            preview.data
              ? `${preview.data.columns.length} columns · showing ${preview.data.rows.length} rows`
              : undefined
          }
          right={
            <Button variant="ghost" onClick={() => setPreviewFor(null)}>
              Close
            </Button>
          }
        >
          {preview.isLoading ? (
            <Spinner />
          ) : preview.data ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-white/10 text-slate-500">
                    {preview.data.columns.slice(0, 18).map((c) => (
                      <th key={c} className="px-2 py-1.5 whitespace-nowrap">
                        {c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {preview.data.rows.map((r, i) => (
                    <tr key={i} className="border-b border-white/5">
                      {preview.data!.columns.slice(0, 18).map((c) => (
                        <td key={c} className="px-2 py-1.5 tabular-nums text-slate-300">
                          {String(r[c] ?? "")}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState>Preview failed.</EmptyState>
          )}
        </Card>
      )}

      <Card title="Validation reports" subtitle="Errors & warnings captured when datasets were validated">
        <div className="space-y-3">
          {(datasets ?? [])
            .filter((d) => d.validation_report?.errors?.length || d.validation_report?.warnings?.length)
            .map((d) => (
              <div key={d.id} className="rounded-lg border border-white/5 bg-black/20 p-3 text-xs">
                <div className="mb-1 font-semibold text-slate-200">
                  #{d.id} · {d.name}
                </div>
                {(d.validation_report?.errors ?? []).map((e, i) => (
                  <div key={i} className="text-red-400">• {e}</div>
                ))}
                {(d.validation_report?.warnings ?? []).map((w, i) => (
                  <div key={i} className="text-amber-400">• {w}</div>
                ))}
                {d.validation_report?.note && (
                  <div className="text-slate-400">• {d.validation_report.note}</div>
                )}
              </div>
            ))}
        </div>
      </Card>
    </div>
  );
}