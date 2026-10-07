import { useEffect, useMemo, useState } from "react";
import { Status, Tile } from "../components/Status";
import { money, word } from "../lib/format";
import { source } from "../lib/source";
import type { Book } from "../lib/types";

const select = "rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm";

/** Home: who needs the advisor today, most urgent first. */
export function Home() {
  const [book, setBook] = useState<Book>();
  const [onlyAttention, setOnlyAttention] = useState(true);
  const [stage, setStage] = useState("");
  const [tier, setTier] = useState("");
  const [profile, setProfile] = useState("");
  const [q, setQ] = useState("");
  useEffect(() => { source.book().then(setBook); }, []);
  const rows = useMemo(() => (book?.households ?? []).filter((h) =>
    (!onlyAttention || h.top_level) && (!stage || h.life_stage === stage) && (!tier || h.aum_tier === tier)
    && (!profile || h.risk_profile === profile) && h.name.toLowerCase().includes(q.toLowerCase())), [book, onlyAttention, stage, tier, profile, q]);
  if (!book) return <p className="text-slate-500">Loading your book…</p>;
  const s = book.stats;
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
        <Tile label="Households" value={s.households} />
        <Tile label="Assets" value={money(s.aum_cad)} />
        <Tile label="Need attention" value={s.need_attention} hint="Any critical or warning item, KYC due, or review overdue" />
        <Tile label="Critical" value={s.critical} hint="Suitability, concentration or large drift breaches" />
        <Tile label="KYC due" value={s.kyc_due} hint="KYC incomplete or older than a year" />
        <Tile label="Review overdue" value={s.review_overdue} />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm">
          <input type="checkbox" checked={onlyAttention} onChange={(e) => setOnlyAttention(e.target.checked)} /> Needs attention only
        </label>
        <select className={select} value={stage} onChange={(e) => setStage(e.target.value)}>
          <option value="">All life stages</option>
          {["accumulation", "pre_retirement", "retirement"].map((v) => <option key={v} value={v}>{word(v)}</option>)}
        </select>
        <select className={select} value={tier} onChange={(e) => setTier(e.target.value)}>
          <option value="">All sizes</option>
          {["Core", "Premier", "Private"].map((v) => <option key={v}>{v}</option>)}
        </select>
        <select className={select} value={profile} onChange={(e) => setProfile(e.target.value)}>
          <option value="">All risk profiles</option>
          {["conservative", "balanced", "growth"].map((v) => <option key={v} value={v}>{word(v)}</option>)}
        </select>
        <input className={`${select} min-w-48`} placeholder="Search by name" value={q} onChange={(e) => setQ(e.target.value)} />
        <span className="ml-auto text-sm text-slate-500">{rows.length} households · data as of {book.as_of}</span>
      </div>
      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
            <tr><th className="p-3">Household</th><th className="p-3">Status</th><th className="p-3">Why</th><th className="p-3">Profile</th><th className="p-3 text-right">Assets</th></tr>
          </thead>
          <tbody>
            {rows.map((h) => (
              <tr key={h.client_id} onClick={() => (location.hash = `#/client/${h.client_id}`)}
                className="cursor-pointer border-t border-slate-100 hover:bg-slate-50">
                <td className="p-3"><div className="font-medium text-slate-900">{h.name}</div>
                  <div className="text-xs text-slate-500">{h.age} · {word(h.life_stage)}</div></td>
                <td className="p-3"><Status level={h.top_level} /></td>
                <td className="p-3 text-slate-700">{h.attention[0]?.text ?? "Nothing to act on"}
                  {h.attention.length > 1 && <span className="ml-1 text-xs text-slate-400">+{h.attention.length - 1} more</span>}</td>
                <td className="p-3">{word(h.risk_profile)}</td>
                <td className="p-3 text-right"><div>{money(h.total_cad)}</div><div className="text-xs text-slate-500">{h.aum_tier}</div></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
