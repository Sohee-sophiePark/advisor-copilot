import { useEffect, useState } from "react";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card } from "../components/Status";
import { source } from "../lib/source";
import type { Market as M } from "../lib/types";

/** Market context for client conversations: index trends and which households are most exposed. */
export function Market() {
  const [m, setM] = useState<M>();
  useEffect(() => { source.market().then(setM); }, []);
  if (!m) return <p className="text-slate-500">Loading…</p>;
  return (
    <div className="space-y-4">
      <p className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900">{m.label} As of {m.as_of}.</p>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {m.indicators.map((i) => (
          <Card key={i.key} title={i.label.replace(" (fictional)", "")} right={<span className={`text-lg font-semibold ${i.value < 0 ? "text-red-700" : "text-slate-900"}`}>{i.value > 0 && !i.key.endsWith("yield") ? "+" : ""}{i.value}%</span>}>
            <ResponsiveContainer width="100%" height={110}>
              <LineChart data={i.history.map((v, k) => ({ month: m.months[k], v }))} margin={{ top: 4, right: 8, left: -24, bottom: 0 }}>
                <XAxis dataKey="month" tick={{ fontSize: 10, fill: "#94a3b8" }} tickLine={false} axisLine={false} interval={2} />
                <YAxis tick={{ fontSize: 10, fill: "#94a3b8" }} tickLine={false} axisLine={false} width={40} />
                <Tooltip formatter={(v: any) => [`${v}%`, i.key.endsWith("yield") ? "Yield" : "Year to date"]} />
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
      <Card title="Headlines (fictional)"><ul className="list-disc pl-5 text-sm text-slate-700">{m.headlines.map((h) => <li key={h.id}>{h.text.replace("Fictional: ", "")}</li>)}</ul></Card>
    </div>
  );
}
