import { Bar, BarChart, Cell, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { money, word } from "../lib/format";
import type { ClientDetail } from "../lib/types";
import { Card, Status } from "./Status";

const OVER = "#2a78d6";
const UNDER = "#eb6834";

/** Out of balance: each asset class's distance from target, with the ±tolerance band shaded. */
export function DriftBars({ c }: { c: ClientDetail }) {
  const tol = c.metrics["cfg.drift_tolerance.pp"] ?? 5;
  const data = c.allocation.filter((a) => a.target_pct !== null).map((a) => ({
    drift: +(a.current_pct - (a.target_pct ?? 0)).toFixed(1), current: a.current_pct, target: a.target_pct, asset: word(a.asset_class),
  })).map((d) => ({ ...d, name: `${d.asset}  ${d.drift > 0 ? "+" : ""}${d.drift}` }));
  if (!data.length) return <p className="text-sm text-slate-500">No target mix until the KYC risk profile is on file.</p>;
  return (
    <div>
      <ResponsiveContainer width="100%" height={230}>
        <BarChart data={data} layout="vertical" margin={{ left: 20, right: 16 }}>
          <XAxis type="number" domain={[(min: number) => Math.min(min, -tol * 2), (max: number) => Math.max(max, tol * 2)]} hide />
          <YAxis type="category" dataKey="name" width={170} tickLine={false} axisLine={false} tick={{ fontSize: 12, fill: "#475569" }} />
          <ReferenceArea x1={-tol} x2={tol} fill="#f1f5f9" />
          <ReferenceLine x={0} stroke="#94a3b8" />
          <Tooltip cursor={{ fill: "#f8fafc" }} formatter={(_v, _n, p: any) => [`${p.payload.current.toFixed(1)}% now · ${p.payload.target}% target`, "Allocation"]} />
          <Bar dataKey="drift" radius={4} barSize={14}>
            {data.map((d) => <Cell key={d.name} fill={d.drift >= 0 ? OVER : UNDER} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <p className="text-xs text-slate-500">Percentage points above (blue) or below (orange) target. Shaded band = within tolerance (±{tol} pts).</p>
    </div>
  );
}

/** Risk at a glance: volatility against the profile's limit, stress loss, single-stock exposure. */
export function RiskPanel({ c }: { c: ClientDetail }) {
  const m = c.metrics;
  const vol = m["risk.vol.pct"], band = m["risk.vol_band_max.pct"];
  const scale = Math.max((band ?? vol) * 1.5, vol * 1.15);
  const over = band !== undefined && vol > band;
  const stocks = Object.entries(m).filter(([k]) => k.startsWith("conc.") && k !== "conc.limit.pct");
  return (
    <div className="space-y-4 text-sm">
      <div>
        <div className="flex justify-between"><span>Volatility (how much the value swings)</span>
          <span className="font-medium">{vol.toFixed(1)}%{band !== undefined && ` · limit ${band.toFixed(1)}%`}</span></div>
        <div className="relative mt-1 h-3 rounded-full bg-slate-100">
          <div className="h-3 rounded-full" style={{ width: `${(vol / scale) * 100}%`, background: over ? "#d03b3b" : "#0ca30c" }} />
          {band !== undefined && <div className="absolute -top-1 h-5 w-0.5 bg-slate-700" style={{ left: `${(band / scale) * 100}%` }} title="Limit for the risk profile" />}
        </div>
        <div className="mt-1">{over ? <Status level="critical" /> : <Status level={null} />}</div>
      </div>
      <div className="flex justify-between border-t border-slate-100 pt-3"><span>In a severe market drop (stress test)</span>
        <span className="font-medium text-red-800">{money(Math.abs(m["stress.equity_bear.cad"] ?? 0)).replace("$", "−$")} ({(m["stress.equity_bear.pct"] ?? 0).toFixed(1)}%)</span></div>
      {stocks.map(([k, v]) => (
        <div key={k} className="flex justify-between border-t border-slate-100 pt-3"><span>Single stock {k.split(".")[1]}</span>
          <span className="font-medium">{v.toFixed(1)}% of portfolio · limit {m["conc.limit.pct"]}%</span></div>
      ))}
    </div>
  );
}

export function Goals({ c }: { c: ClientDetail }) {
  if (!c.goals.length) return <p className="text-sm text-slate-500">No goals on file from the client survey.</p>;
  return (
    <div className="space-y-2">
      {c.goals.map((g) => {
        const atRisk = g.required_pct !== null && g.model_pct !== null && g.required_pct > g.model_pct;
        return (
          <div key={g.goal_id} className="flex items-center justify-between rounded-lg border border-slate-100 p-3 text-sm">
            <div><div className="font-medium">{g.name}</div>
              <div className="text-xs text-slate-500">{money(g.target_cad)} by {g.target_year}
                {g.required_pct !== null && ` · needs ${g.required_pct.toFixed(1)}%/yr, plan expects ${g.model_pct?.toFixed(1)}%/yr`}</div></div>
            {atRisk ? <Status level="warning" /> : <Status level={null} />}
          </div>
        );
      })}
    </div>
  );
}

export function Accounts({ c }: { c: ClientDetail }) {
  return (
    <div className="space-y-3 text-sm">
      {c.accounts.map((a) => (
        <div key={a.type}>
          <div className="flex justify-between font-medium"><span>{word(a.type)}</span><span>{money(a.value_cad)}</span></div>
          <ul className="mt-1 space-y-0.5 text-slate-600">
            {a.holdings.map((h) => <li key={h.ticker} className="flex justify-between"><a href={`#/ticker/${h.ticker}`} className="text-sky-700 hover:underline">{h.ticker} · {h.name}</a><span>{money(h.value_cad)}</span></li>)}
          </ul>
        </div>
      ))}
    </div>
  );
}

export function Notes({ c }: { c: ClientDetail }) {
  if (!c.notes.length) return <p className="text-sm text-slate-500">No notes yet.</p>;
  return (
    <ol className="space-y-3 border-l border-slate-200 pl-4 text-sm">
      {c.notes.map((n) => (
        <li key={n.note_id}><div className="text-xs text-slate-500">{n.date} · {n.author}</div><div className="text-slate-700">{n.text}</div></li>
      ))}
    </ol>
  );
}

export function Overview({ c }: { c: ClientDetail }) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title="Out of balance vs target mix"><DriftBars c={c} /></Card>
      <Card title="Risk"><RiskPanel c={c} /></Card>
      <Card title="Goals from the client survey"><Goals c={c} /></Card>
      <Card title="Accounts"><Accounts c={c} /></Card>
      <div className="lg:col-span-2"><Card title="Notes"><Notes c={c} /></Card></div>
    </div>
  );
}
