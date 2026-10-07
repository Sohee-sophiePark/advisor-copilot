import { useState } from "react";
import { SEVERITY_COLOR } from "../lib/format";
import type { Finding, RunState } from "../lib/types";
import { Chips } from "./Chips";

const PRIORITY = { high: "bg-red-50 text-red-800 ring-red-200", medium: "bg-amber-50 text-amber-800 ring-amber-200", low: "bg-slate-100 text-slate-700 ring-slate-200" };

export function RecommendationCard({ state }: { state: RunState }) {
  const [open, setOpen] = useState<string | null>(null);
  const findings: Record<string, Finding> = {};
  for (const r of Object.values(state.analyst_reports)) for (const f of r.findings) findings[f.finding_id] = f;
  const draft = state.drafts.at(-1);
  const m = state.metrics;
  const issues = state.eval_verdicts.at(-1)?.issues ?? [];
  return (
    <div className="space-y-3 rounded-lg border border-slate-200 bg-white p-4">
      {state.status === "BLOCKED" && (
        <div className="rounded-md bg-amber-50 p-3 text-sm text-amber-900">
          <div className="font-medium">KYC update required</div>
          <div>{state.message}</div>
          <button className="mt-2 rounded border border-amber-400 px-2 py-1 text-xs" onClick={() => alert("Mock: a KYC task would be created in the CRM.")}>Request KYC update</button>
        </div>
      )}
      {state.route?.route === "out_of_scope" && <div className="rounded-md bg-slate-100 p-3 text-sm">{state.message}</div>}
      {state.status === "NEEDS_ADVISOR_REVIEW" && (
        <div className="rounded-md bg-amber-50 p-3 text-sm text-amber-900">
          <div className="font-medium">Needs advisor review: the evaluator did not pass this draft after {state.revision_count} revisions</div>
          <ul className="mt-1 list-disc pl-5">{issues.map((i, k) => <li key={k}><b>{i.criterion}</b>: {i.detail} <i>{i.suggested_fix}</i></li>)}</ul>
          {!issues.length && <div>{state.message}</div>}
        </div>
      )}
      {state.status === "DEGRADED" && <div className="rounded-md bg-amber-50 p-3 text-sm text-amber-900">Degraded: {state.error}. Showing what was produced.</div>}
      {state.status === "FAILED" && <div className="rounded-md bg-red-50 p-3 text-sm text-red-900">Run failed: {state.error}</div>}
      {draft && (
        <>
          <h2 className="text-lg font-semibold"><Chips text={draft.headline} metrics={m} /></h2>
          <p className="text-sm leading-relaxed"><Chips text={draft.summary} metrics={m} /></p>
          {draft.actions.length > 0 && <Section title="Actions">
            {draft.actions.map((a) => (
              <div key={a.action_id} className="rounded-md border border-slate-200 p-2 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <span className={`rounded-full px-2 py-0.5 text-xs ring-1 ${PRIORITY[a.priority]}`}>{a.priority}</span>
                  <span className="font-mono text-xs text-slate-600">{a.type} · {a.target} · {a.direction}</span>
                </div>
                <div className="mt-1"><Chips text={a.description} metrics={m} /></div>
                <div className="text-slate-600"><Chips text={a.rationale} metrics={m} /></div>
                <div className="mt-1 flex flex-wrap gap-1 text-xs">
                  based on
                  {a.finding_refs.map((id) => (
                    <button key={id} onClick={() => setOpen(open === id ? null : id)}
                      className="rounded-full px-2 py-0.5 ring-1 ring-slate-300" style={{ color: SEVERITY_COLOR[findings[id]?.severity ?? "info"] }}>{id}</button>
                  ))}
                </div>
                {a.finding_refs.includes(open ?? "") && findings[open!] && (
                  <div className="mt-1 rounded bg-slate-50 p-2 text-xs"><b>{findings[open!].title}</b> — <Chips text={findings[open!].detail} metrics={m} /></div>
                )}
              </div>
            ))}
          </Section>}
          {draft.deferred.length > 0 && <Section title="Deferred">{draft.deferred.map((d) => <div key={d.finding_id} className="text-sm"><b>{d.finding_id}</b>: <Chips text={d.reason} metrics={m} /></div>)}</Section>}
          {draft.risks_and_considerations.length > 0 && <Section title="Risks and considerations"><ul className="list-disc pl-5 text-sm">{draft.risks_and_considerations.map((r, i) => <li key={i}><Chips text={r} metrics={m} /></li>)}</ul></Section>}
          {draft.client_talking_points.length > 0 && <Section title="Client talking points"><ul className="list-disc pl-5 text-sm">{draft.client_talking_points.map((r, i) => <li key={i}><Chips text={r} metrics={m} /></li>)}</ul></Section>}
        </>
      )}
      {!draft && state.status === "DEGRADED" && Object.values(state.analyst_reports).map((r) => (
        <div key={r.agent} className="text-sm"><b className="capitalize">{r.agent}</b>: {r.findings.map((f) => f.title).join("; ") || "no findings"}</div>
      ))}
      {state.final && <p className="border-t border-slate-100 pt-2 text-xs text-slate-500">{state.final.disclosure}</p>}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <div className="space-y-1"><div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</div>{children}</div>;
}
