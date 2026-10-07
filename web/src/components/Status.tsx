import type { Level } from "../lib/types";

const STYLE: Record<Level, [string, string, string]> = {
  critical: ["●", "Critical", "bg-red-50 text-red-800 ring-red-200"],
  warning: ["▲", "Warning", "bg-amber-50 text-amber-900 ring-amber-200"],
  kyc: ["◆", "KYC due", "bg-orange-50 text-orange-900 ring-orange-200"],
  review: ["○", "Review due", "bg-sky-50 text-sky-900 ring-sky-200"],
};

/** Status always as icon + word + colour, never colour alone. */
export function Status({ level }: { level: Level | null }) {
  if (!level) return <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs text-emerald-800 ring-1 ring-emerald-200">✓ On track</span>;
  const [icon, label, cls] = STYLE[level];
  return <span className={`whitespace-nowrap rounded-full px-2 py-0.5 text-xs ring-1 ${cls}`}>{icon} {label}</span>;
}

export function Tile({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4" title={hint}>
      <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-slate-900">{value}</div>
    </div>
  );
}

export function Card({ title, children, right }: { title: string; children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-700">{title}</h2>
        {right}
      </div>
      {children}
    </section>
  );
}
