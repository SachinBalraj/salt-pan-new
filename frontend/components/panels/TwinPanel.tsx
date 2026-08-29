"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, fmt } from "@/lib/api";
import {
  Badge,
  Button,
  Card,
  inputCls,
  Meter,
  Spinner,
  Stat,
} from "@/components/ui";
import { PanSelect } from "./common";

export default function TwinPanel() {
  const qc = useQueryClient();
  const [panId, setPanId] = useState<number>(0);

  const { data: pans } = useQuery({ queryKey: ["pans"], queryFn: api.pans });
  const selected = pans?.find((p) => p.id === panId) ?? pans?.[0];

  const twin = useQuery({
    queryKey: ["twin", selected?.id],
    queryFn: () => api.panTwin(selected!.id),
    enabled: !!selected?.id,
  });

  const [form, setForm] = useState<Record<string, string>>({});
  useEffect(() => {
    if (twin.data) {
      setForm({
        water_depth_cm: String(twin.data.state.water_depth_cm ?? ""),
        brine_density_be: String(twin.data.state.brine_density_be ?? ""),
        salt_thickness_mm: String(twin.data.state.salt_thickness_mm ?? ""),
        days_since_last_rain: String(twin.data.state.days_since_last_rain ?? ""),
      });
    }
  }, [twin.data]);

  const update = useMutation({
    mutationFn: () =>
      api.updateTwin(selected!.id, {
        water_depth_cm: Number(form.water_depth_cm),
        brine_density_be: Number(form.brine_density_be),
        salt_thickness_mm: Number(form.salt_thickness_mm),
        days_since_last_rain: Number(form.days_since_last_rain),
        last_update: new Date().toISOString().slice(0, 10),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["twin"] });
      qc.invalidateQueries({ queryKey: ["pans"] });
    },
  });

  if (!pans || pans.length === 0) {
    return <Card title="Digital twin"><p className="text-sm text-slate-500">No pans registered yet.</p></Card>;
  }
  if (twin.isLoading || !twin.data) return <Spinner label="Loading twin…" />;

  const st = twin.data.state;
  return (
    <div className="space-y-5">
      <Card
        title="Digital twin editor"
        subtitle="Live physics state of each salt pan — updated by forecasts, simulations and verified outcomes"
        right={
          <div className="w-56">
            <PanSelect value={selected?.id ?? 0} onChange={setPanId} />
          </div>
        }
      >
        <div className="flex flex-wrap items-center gap-4">
          <div>
            <div className="text-lg font-bold text-slate-100">{selected!.pan_id}</div>
            <div className="text-xs text-slate-500">{selected!.name} · {selected!.location}</div>
          </div>
          <Badge className="border-white/10 bg-white/5 text-slate-300">Area {fmt.kg(selected!.area_m2)} m²</Badge>
          <Badge className="border-emerald-500/40 bg-emerald-500/15 text-emerald-300">
            {Math.round(twin.data.progress_to_harvest * 100)}% to harvest
          </Badge>
        </div>

        <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Stat label="Brine density" value={fmt.be(st.brine_density_be ?? 0)} tone="text-sky-300" />
          <Stat label="Salt layer" value={fmt.mm(st.salt_thickness_mm ?? 0)} tone="text-slate-100" />
          <Stat label="Water depth" value={fmt.cm(st.water_depth_cm ?? 0)} tone="text-slate-100" />
          <Stat label="Est. mass" value={`${fmt.kg(st.estimated_salt_mass_kg)} kg`} tone="text-brine-300" />
        </div>

        <div className="mt-4">
          <Meter value={twin.data.progress_to_harvest} label="Progress to harvest" tone="bg-brine-400" />
        </div>

        <div className="mt-4 grid max-w-xl grid-cols-2 gap-3">
          {(["water_depth_cm", "brine_density_be", "salt_thickness_mm", "days_since_last_rain"] as const).map((k) => (
            <label key={k} className="block">
              <span className="mb-1 block text-xs font-medium text-slate-400">{k}</span>
              <input
                className={inputCls}
                type="number"
                step="any"
                value={form[k] ?? ""}
                onChange={(e) => setForm((f) => ({ ...f, [k]: e.target.value }))}
              />
            </label>
          ))}
        </div>
        <div className="mt-3 flex items-center gap-3">
          <Button onClick={() => update.mutate()} disabled={update.isPending}>
            {update.isPending ? "Updating…" : "Update twin state"}
          </Button>
          <span className="text-xs text-slate-500">
            Last updated {fmt.date(st.last_update)}
          </span>
        </div>
      </Card>

      <Card
        title="Twin state history"
        subtitle="Snapshots recorded from seeding, forecasts, simulations and outcome feedback"
      >
        <div className="text-xs text-slate-500">
          Snapshots for pan {selected!.pan_id} are stored in <code className="text-brine-300">twin_snapshots</code>
          {" "}and exposed via <code className="text-brine-300">GET /api/pans/{selected!.id}/snapshots</code>.
        </div>
      </Card>
    </div>
  );
}