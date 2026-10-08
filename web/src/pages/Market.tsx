import { useEffect, useState } from "react";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card } from "../components/Status";
import { formatValue } from "../lib/format";
import { source } from "../lib/source";
import type { Market as M } from "../lib/types";

/** Market context for client conversations: index trends and which households are most exposed. */
export function Market() {
  const [m, setM] = useState<M>();
  useEffect(() => { source.market().then(setM); }, []);
  if (!m) return <p className="text-slate-500">Loading…</p>;
  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2">
      {m.real.map((r) => (
        <Card key={r.key} title={`${r.label} · real data`} right={<span className="text-lg font-semibold text-slate-900">{formatValue(r.history.at(-1)?.value ?? 0, r.unit)}</span>}>
          <ResponsiveContainer width="100%" height={110}>
            <LineChart data={r.history} margin={{ top: 4, right: 8, left: -12, bottom: 0 }}>
              <XAxis dataKey="date" tick={{ fontSize: 10, fill: "#94a3b8" }} tickLine={false} axisLine={false} minTickGap={40} />
              <YAxis domain={["auto", "auto"]} tick={{ fontSize: 10, fill: "#94a3b8" }} tickLine={false} axisLine={false} width={52} />
              <Tooltip />
              <Line dataKey="value" stroke="#008300" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
          {r.note && <p className="mt-1 text-xs text-slate-600">{r.note}</p>}
          <p className="mt-1 text-xs text-slate-500">Source: <a className="text-sky-700 hover:underline" href={r.url} target="_blank" rel="noreferrer">{r.source}</a> · as of {r.as_of} · <a className="text-sky-700 hover:underline" href={r.terms} target="_blank" rel="noreferrer">terms</a></p>
        </Card>
      ))}
      </div>
      {m.sectors.length > 0 && (
        <Card title="Index and US sector ETFs · laptop only" right={<span className="text-xs text-slate-500">change {m.sectors[0].from} → {m.sectors[0].to} · Tiingo, personal use, never published</span>}>
          <div className="grid gap-x-6 gap-y-1 text-sm md:grid-cols-3">{m.sectors.map((x) => (
            <div key={x.ticker} className="flex justify-between"><span>{x.sector} <span className="text-xs text-slate-400">{x.ticker}</span></span>
              <span className={x.change_pct < 0 ? "text-red-700" : "text-emerald-700"}>{x.change_pct > 0 ? "+" : ""}{x.change_pct}%</span></div>))}</div>
        </Card>
      )}
      <p className="rounded-lg bg-slate-100 px-3 py-2 text-sm text-slate-700">{m.label} Month-end values; these are what the copilot's market analyst reads.</p>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {m.indicators.map((i) => (
          <Card key={i.key} title={i.label} right={<span className={`text-lg font-semibold ${i.value < 0 ? "text-red-700" : "text-slate-900"}`}>{formatValue(i.value, i.unit)}</span>}>
            <ResponsiveContainer width="100%" height={110}>
              <LineChart data={i.history.map((v, k) => ({ month: m.months[k], v }))} margin={{ top: 4, right: 8, left: -24, bottom: 0 }}>
                <XAxis dataKey="month" tick={{ fontSize: 10, fill: "#94a3b8" }} tickLine={false} axisLine={false} interval={2} />
                <YAxis domain={["auto", "auto"]} tick={{ fontSize: 10, fill: "#94a3b8" }} tickLine={false} axisLine={false} width={40} />
                <Tooltip formatter={(v: any) => [formatValue(Number(v), i.unit), "Month end"]} />
                <Line dataKey="v" stroke="#2a78d6" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
            <div className="mt-2 text-xs text-slate-500">Most exposed households</div>
            <ul className="text-sm">{i.most_exposed.slice(0, 3).map((e) => (
              <li key={e.client_id} className="flex justify-between"><a className="text-sky-700" href={`#/client/${e.client_id}`}>{e.name}</a><span>{e.weight_pct}%</span></li>))}</ul>
          </Card>
        ))}
      </div>
      <Card title="Instruments in client portfolios">
        <ul className="grid gap-1 text-sm md:grid-cols-2">{m.instruments.map((i) => (
          <li key={i.ticker}><a className="text-sky-700 hover:underline" href={`#/ticker/${i.ticker}`}>{i.ticker} · {i.name}</a></li>))}</ul>
      </Card>
      <Card title="Bank of Canada releases"><ul className="list-disc pl-5 text-sm text-slate-700">{m.headlines.map((h) => <li key={h.id}>{h.text}</li>)}</ul></Card>
    </div>
  );
}
