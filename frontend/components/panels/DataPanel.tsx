"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { api } from "@/lib/api";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  inputCls,
  Spinner,
} from "@/components/ui";

export default function DataPanel() {
  const qc = useQueryClient();
  const { data: datasets, isLoading } = useQuery({
    queryKey: ["datasets"],
    queryFn: api.datasets,
  });
  const fileRef = useRef<HTMLInputElement>(null);
  const [previewFor, setPreviewFor] = useState<number | null>(null);
  const [message, setMessage] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const preview = useQuery({
    queryKey: ["preview", previewFor],
    queryFn: () => api.datasetPreview(previewFor!),
    enabled: !!previewFor,
  });

  const upload = useMutation({
    mutationFn: (f: File) => api.uploadDataset(f),
    onSuccess: (ds) => {
      setMessage({ kind: "ok", text: `Uploaded ${ds.filename} (${ds.rows_count} rows, status: ${ds.status}).` });
      qc.invalidateQueries({ queryKey: ["datasets"] });
    },
    onError: (e: Error) => setMessage({ kind: "err", text: e.message }),
  });

  const validate = useMutation({
    mutationFn: api.validateDataset,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["datasets"] });
    },
  });
  const promote = useMutation({
    mutationFn: api.promoteDataset,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["datasets"] });
    },
  });

  if (isLoading) return <Spinner label="Loading datasets…" />;

  return (
    <div className="space-y-5">
      <Card
        title="Upload a salt-pan dataset"
        subtitle="CSV/TSV with daily observations per pan. Validated for required columns and physical ranges."
      >
        <div className="flex flex-wrap items-center gap-3">
          <input
            ref={fileRef}
            type="file"
            accept=".csv,.tsv"
            className="text-sm text-slate-400 file:mr-3 file:rounded-lg file:border-0 file:bg-brine-500/20 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-brine-300"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) {
                upload.mutate(f);
              }
            }}
          />
          {upload.isPending && <Spinner label="Validating…" />}
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
        <div className="mt-3 text-xs text-slate-500">
          Required columns: pan_id · date · temperature_c · humidity_pct ·
          wind_speed_kmh · rainfall_mm · sunshine_hours · water_depth_cm ·
          brine_density_be · salt_thickness_mm · days_since_last_rain. Optional
          ML targets: harvest_readiness · climate_risk.
        </div>
      </Card>

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
                    <td className="py-2 pr-4 font-medium text-slate-200">
                      {d.name}
                    </td>
                    <td className="py-2 pr-4 text-slate-400">{d.source}</td>
                    <td className="py-2 pr-4 tabular-nums text-slate-300">
                      {d.rows_count.toLocaleString()}
                    </td>
                    <td className="py-2 pr-4">
                      <Badge
                        className={
                          d.status === "valid" || d.status === "promoted"
                            ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-300"
                            : d.status === "invalid"
                              ? "border-red-500/40 bg-red-500/15 text-red-300"
                              : "border-white/10 bg-white/5 text-slate-300"
                        }
                      >
                        {d.status}
                      </Badge>
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
                                setMessage({
                                  kind: "ok",
                                  text: `Re-validated dataset #${d.id}`,
                                }),
                            })
                          }
                        >
                          Validate
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