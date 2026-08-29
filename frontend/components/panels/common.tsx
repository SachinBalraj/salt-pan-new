"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Select } from "@/components/ui";
import type { DataSet, MlModel, SaltPan } from "@/lib/types";

export function usePans() {
  return useQuery<SaltPan[]>({ queryKey: ["pans"], queryFn: api.pans });
}

export function useDatasets() {
  return useQuery<DataSet[]>({ queryKey: ["datasets"], queryFn: api.datasets });
}

export function useModels() {
  return useQuery<MlModel[]>({ queryKey: ["models"], queryFn: api.models });
}

export function PanSelect({
  value,
  onChange,
  allowAll = false,
  allValue = 0,
}: {
  value: number;
  onChange: (id: number) => void;
  allowAll?: boolean;
  allValue?: number;
}) {
  const { data: pans, isLoading } = usePans();
  if (isLoading) {
    return <div className="text-sm text-slate-500">Loading pans…</div>;
  }
  return (
    <Select
      value={value}
      onChange={(v) => onChange(Number(v))}
      className="max-w-xs"
    >
      {allowAll && <option value={allValue}>All pans</option>}
      {(pans ?? []).map((p) => (
        <option key={p.id} value={p.id}>
          {p.pan_id} — {p.name}
        </option>
      ))}
    </Select>
  );
}