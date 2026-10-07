import { useEffect, useState } from "react";
import { Chat } from "../components/Chat";
import { Overview } from "../components/Overview";
import { Status } from "../components/Status";
import { money, word } from "../lib/format";
import { source } from "../lib/source";
import type { ClientDetail } from "../lib/types";

/** One household: the full picture on the left, Review & Ask on the right. */
export function Client({ id }: { id: string }) {
  const [c, setC] = useState<ClientDetail>();
  const [tab, setTab] = useState<"overview" | "ask">("overview");
  useEffect(() => { setC(undefined); source.client(id).then(setC); }, [id]);
  if (!c) return <p className="text-slate-500">Loading…</p>;
  const p = c.profile;
  const facts = [
    ["Age", `${c.age} · ${word(c.life_stage)}`], ["Risk profile", word(c.risk_profile)],
    ["Horizon", p.time_horizon_years ? `${p.time_horizon_years} years` : "—"], ["Assets", `${money(c.total_cad)} · ${c.aum_tier}`],
    ["KYC reviewed", p.kyc_last_reviewed ?? "—"], ["Next review", c.review_due ?? "—"],
    ["Income need", p.preferences?.income_need_cad_month ? `${money(p.preferences.income_need_cad_month)}/month` : "—"],
  ];
  const tabBtn = (t: typeof tab, label: string) => (
    <button onClick={() => setTab(t)} className={`rounded-lg px-3 py-1.5 text-sm ${tab === t ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"}`}>{label}</button>
  );
  return (
    <div className="space-y-4">
      <a href="#/" className="text-sm text-sky-700">← Back to my book</a>
      <section className="rounded-xl border border-slate-200 bg-white p-4">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-semibold text-slate-900">{c.name}</h1><Status level={c.top_level} />
        </div>
        <dl className="mt-3 grid grid-cols-2 gap-3 text-sm md:grid-cols-7">
          {facts.map(([k, v]) => <div key={k}><dt className="text-xs text-slate-500">{k}</dt><dd className="font-medium text-slate-800">{v}</dd></div>)}
        </dl>
        {c.attention.length > 0 && (
          <ul className="mt-3 space-y-1 border-t border-slate-100 pt-3 text-sm">
            {c.attention.map((a, i) => <li key={i} className="flex items-center gap-2"><Status level={a.level} /> {a.text}</li>)}
          </ul>
        )}
      </section>
      <div className="flex gap-1">{tabBtn("overview", "Overview")}{tabBtn("ask", "Review & Ask")}</div>
      {tab === "overview" ? <Overview c={c} /> : <div className="h-[70vh]"><Chat clientId={c.client_id} /></div>}
    </div>
  );
}
