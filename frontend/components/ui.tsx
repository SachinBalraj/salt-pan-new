import { ReactNode } from "react";

export function Card({
  title,
  subtitle,
  right,
  children,
  className = "",
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  right?: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-xl border border-white/10 bg-white/[0.03] shadow-lg shadow-black/20 ${className}`}
    >
      {(title || right) && (
        <div className="flex items-start justify-between gap-3 px-5 pt-4">
          <div>
            {title && (
              <h3 className="text-sm font-semibold tracking-wide text-slate-200">
                {title}
              </h3>
            )}
            {subtitle && (
              <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>
            )}
          </div>
          {right}
        </div>
      )}
      <div className="p-5">{children}</div>
    </div>
  );
}

export function Stat({
  label,
  value,
  sub,
  tone = "text-slate-100",
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: string;
}) {
  return (
    <div className="rounded-lg border border-white/5 bg-black/20 p-3">
      <div className="text-[11px] font-medium uppercase tracking-wider text-slate-500">
        {label}
      </div>
      <div className={`mt-1 text-xl font-bold tabular-nums ${tone}`}>{value}</div>
      {sub && <div className="mt-0.5 text-[11px] text-slate-500">{sub}</div>}
    </div>
  );
}

export function Badge({
  children,
  className = "",
  title,
}: {
  children: ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${className}`}
    >
      {children}
    </span>
  );
}

export function Button({
  children,
  onClick,
  disabled,
  variant = "primary",
  className = "",
  type = "button",
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  variant?: "primary" | "ghost" | "danger" | "success";
  className?: string;
  type?: "button" | "submit";
}) {
  const styles =
    variant === "primary"
      ? "bg-brine-500 text-brine-950 hover:bg-brine-400"
      : variant === "success"
        ? "bg-emerald-500 text-emerald-950 hover:bg-emerald-400"
        : variant === "danger"
          ? "bg-red-500/80 text-white hover:bg-red-500"
          : "border border-white/10 text-slate-300 hover:bg-white/5";
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-40 ${styles} ${className}`}
    >
      {children}
    </button>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-8 text-sm text-slate-400">
      <div className="h-4 w-4 animate-spin rounded-full border-2 border-brine-500 border-t-transparent" />
      {label ?? "Loading…"}
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-white/10 py-10 text-center text-sm text-slate-500">
      {children}
    </div>
  );
}

export function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-slate-400">
        {label}
      </span>
      {children}
    </label>
  );
}

export const inputCls =
  "w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm text-slate-100 outline-none focus:border-brine-400 focus:ring-1 focus:ring-brine-400/40";

export function Select({
  value,
  onChange,
  children,
  className = "",
}: {
  value: string | number;
  onChange: (v: string) => void;
  children: ReactNode;
  className?: string;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={`${inputCls} ${className}`}
    >
      {children}
    </select>
  );
}

export function Meter({
  value,
  tone,
  label,
}: {
  value: number;
  tone?: string;
  label?: string;
}) {
  const pct = Math.max(0, Math.min(100, value * 100));
  return (
    <div>
      {label && (
        <div className="flex justify-between text-[11px] text-slate-400">
          <span>{label}</span>
          <span className="tabular-nums">{Math.round(pct)}%</span>
        </div>
      )}
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/10">
        <div
          className={`h-full rounded-full transition-all ${tone ?? "bg-sky-500"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}