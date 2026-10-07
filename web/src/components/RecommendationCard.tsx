import { useState } from "react";
import { word } from "../lib/format";
import type { Finding, RunState } from "../lib/types";
import { Chips } from "./Chips";

const PRIORITY = { high: "bg-red-50 text-red-800 ring-red-200", medium: "bg-amber-50 text-amber-900 ring-amber-200", low: "bg-slate-100 text-slate-700 ring-slate-200" };

/** The recommendation an advisor reviews: what to do, why, what to say, what to watch. */
export function RecommendationCard({ state }: { state: RunState }) {
  const [open, setOpen] = useState<string | null>(null);
  const draft = state.drafts.at(-1);
  if (!draft) return null;
  const m = state.metrics;
  const findings: Record<string, Finding> = {};
  for (const r of Object.values(state.analyst_reports)) for (const f of r.findings) findings[f.finding_id] = f;
  return (
    <div className="space-y-3">
      <h3 className="text-base font-semibold text-slate-900"><Chips text={draft.headline} metrics={m} /></h3>
      <p className="text-sm leading-relaxed text-slate-700"><Chips text={draft.summary} metrics={m} /></p>
      {draft.actions.map((a) => (
        <div key={a.action_id} className="rounded-lg border border-slate-200 p-3 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`rounded-full px-2 py-0.5 text-xs ring-1 ${PRIORITY[a.priority]}`}>{a.priority} priority</span>
            <span className="font-medium">{word(a.type)}{a.type !== "no_action" && ` · ${word(a.target)}`}</span>
          </div>
          <div className="mt-1"><Chips text={a.description} metrics={m} /></div>
          <div className="text-slate-500">Why: <Chips text={a.rationale} metrics={m} /></div>
          {a.finding_refs.length > 0 && (
            <button className="mt-1 text-xs text-sky-700 underline" onClick={() => setOpen(open === a.action_id ? null : a.action_id)}>
              {open === a.action_id ? "Hide" : "Show"} the evidence ({a.finding_refs.length})
            </button>
          )}
          {open === a.action_id && (
            <ul className="mt-1 space-y-1 rounded bg-slate-50 p-2 text-xs">
              {a.finding_refs.map((id) => findings[id] && <li key={id}><b>{findings[id].title}</b>: <Chips text={findings[id].detail} metrics={m} /></li>)}
            </ul>
          )}
        </div>
      ))}
      {draft.deferred.length > 0 && <List title="Deliberately deferred" items={draft.deferred.map((d) => `${findings[d.finding_id]?.title ?? d.finding_id}: ${d.reason}`)} m={m} />}
      <List title="What to say to the client" items={draft.client_talking_points} m={m} />
      <List title="Watch-outs" items={draft.risks_and_considerations} m={m} />
      {state.final && <p className="border-t border-slate-100 pt-2 text-xs text-slate-500">{state.final.disclosure}</p>}
    </div>
  );
}

function List({ title, items, m }: { title: string; items: string[]; m: RunState["metrics"] }) {
  if (!items.length) return null;
  return (
    <div className="text-sm"><div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</div>
      <ul className="list-disc pl-5 text-slate-700">{items.map((t, i) => <li key={i}><Chips text={t} metrics={m} /></li>)}</ul></div>
  );
}
