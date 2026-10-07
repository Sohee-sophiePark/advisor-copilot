import { useEffect, useState } from "react";
import { Card } from "../components/Status";
import { money, word } from "../lib/format";
import { source } from "../lib/source";
import type { InstrumentView } from "../lib/types";

/** One ticker: public facts with their source and date, the price source, and the households that hold it. */
export function Ticker({ ticker }: { ticker: string }) {
  const [v, setV] = useState<InstrumentView>();
  useEffect(() => { source.instrument(ticker).then(setV); }, [ticker]);
  if (!v) return <p className="text-slate-500">Loading…</p>;
  const f = v.facts;
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">{v.ticker} · {v.name}</h1>
        <p className="text-sm text-slate-500">{word(v.asset_class)} · {v.listing === "US" ? "US-listed" : "Canadian-listed"} · ${v.price_cad.toFixed(2)} ({v.price_note})</p>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Public facts" right={f && <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs text-emerald-800">{f.facts_source} · as of {f.facts_as_of}</span>}>
          {!f ? <p className="text-sm text-slate-500">No public facts yet: this fund is not an SEC filer. Canadian fund documents come later.</p> : (
            <div className="space-y-3 text-sm">
              <p className="text-slate-700">{f.entity}{f.description && ` · ${f.description}`}
                {!f.figures.length && " (the trust that issues this fund; its filings cover several funds)"}</p>
              {f.figures.length > 0 && <table className="w-full"><tbody>{f.figures.map((g) => (
                <tr key={g.key} className="border-t border-slate-100"><td className="py-1">{g.label}</td><td className="py-1 text-right">{g.unit === "cad" ? money(g.value) : `${(g.value / 1e9).toFixed(2)}B`}</td><td className="py-1 pl-3 text-right text-slate-500">{g.period}</td></tr>))}</tbody></table>}
              {f.figures.some((g) => g.unit === "cad") && <p className="text-xs text-slate-500">Reported figures in CAD from the issuer's annual filing.</p>}
              <div><div className="text-xs text-slate-500">Recent filings</div>
                <ul>{f.filings.map((x) => <li key={x.url}><a className="text-sky-700 hover:underline" href={x.url} target="_blank" rel="noreferrer">{x.form} · {x.date}</a></li>)}</ul></div>
              <a className="text-xs text-sky-700 hover:underline" href={f.facts_url} target="_blank" rel="noreferrer">Source: SEC EDGAR</a>
            </div>
          )}
        </Card>
        <Card title="Households holding it" right={<span className="text-sm text-slate-600">{v.holders.length} · {money(v.total_cad)}</span>}>
          <table className="w-full text-sm"><tbody>{v.holders.map((h) => (
            <tr key={h.client_id} className="border-t border-slate-100">
              <td className="py-1"><a className="text-sky-700 hover:underline" href={`#/client/${h.client_id}`}>{h.name}</a></td>
              <td className="py-1 text-right">{money(h.value_cad)}</td><td className="py-1 pl-3 text-right text-slate-500">{h.weight_pct}%</td></tr>))}</tbody></table>
        </Card>
      </div>
    </div>
  );
}
