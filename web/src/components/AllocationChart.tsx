import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Metric } from "../lib/types";

const CLASSES = ["CASH", "CA_BONDS", "CA_EQUITY", "US_EQUITY", "INTL_EQUITY", "REAL_ASSETS"];

export function AllocationChart({ metrics }: { metrics: Record<string, Metric> }) {
  const data = CLASSES.filter((c) => metrics[`alloc.${c}.pct`]).map((c) => ({
    asset_class: c.replace("_", " "), current: metrics[`alloc.${c}.pct`].value, target: metrics[`target.${c}.pct`]?.value ?? null,
  }));
  if (!data.length) return null;
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3">
      <div className="mb-1 text-sm font-medium">Allocation vs target (%)</div>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data} barGap={2} barCategoryGap="25%" margin={{ top: 4, right: 4, left: -16, bottom: 0 }}>
          <CartesianGrid vertical={false} stroke="#eceeef" />
          <XAxis dataKey="asset_class" tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "#64748b" }} />
          <YAxis tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "#64748b" }} />
          <Tooltip cursor={{ fill: "#f1f5f9" }} formatter={(v) => `${Number(v).toFixed(1)}%`} />
          <Legend iconSize={10} wrapperStyle={{ fontSize: 12 }} />
          <Bar dataKey="current" name="Current" fill="#2a78d6" radius={[4, 4, 0, 0]} maxBarSize={28} />
          <Bar dataKey="target" name="Target" fill="#eb6834" radius={[4, 4, 0, 0]} maxBarSize={28} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
