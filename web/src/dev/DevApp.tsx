import { useEffect, useState } from "react";
import type { RunState, TraceEvent } from "../lib/types";
import { PipelineStepper } from "./PipelineStepper";
import { RunStats } from "./RunStats";
import { TracePanel } from "./TracePanel";

const get = async (url: string) => {
  const r = await fetch(url);
  if (!r.ok) throw new Error(r.status === 404 ? "Developer routes are off: start the API with DEV_CONSOLE=1 (make dev does)." : `${r.status}`);
  return r.json();
};

type Row = Record<string, any>;

/** Engineering view (laptop only): runs, trace, gates, evaluator, usage and cost, eval report. */
export function DevApp() {
  const [tab, setTab] = useState<"runs" | "usage" | "evals">("runs");
  const [runs, setRuns] = useState<Row[]>([]);
  const [sel, setSel] = useState<{ state: RunState; events: TraceEvent[]; cost_usd: number }>();
  const [usage, setUsage] = useState<Row>();
  const [report, setReport] = useState("");
  const [error, setError] = useState("");
  const load = () => get("/api/dev/runs").then(setRuns).catch((e) => setError(String(e.message)));
  useEffect(() => {
    load();
    get("/api/dev/usage").then(setUsage).catch(() => undefined);
    get("/api/dev/evals").then((r) => setReport(r.report)).catch(() => undefined);
  }, []);
  const open = (id: string) => get(`/api/dev/runs/${id}`).then(setSel);
  const tabBtn = (t: typeof tab, label: string) => (
    <button onClick={() => setTab(t)} className={`rounded-lg px-3 py-1.5 text-sm ${tab === t ? "bg-slate-900 text-white" : "text-slate-600"}`}>{label}</button>
  );
  return (
    <div className="p-4">
      <header className="mb-3 flex items-center gap-3">
        <b>Developer console</b><span className="rounded bg-slate-800 px-2 py-0.5 text-xs text-white">local only</span>
        {tabBtn("runs", "Runs & trace")}{tabBtn("usage", "Usage & cost")}{tabBtn("evals", "Eval report")}
        <button onClick={load} className="ml-auto text-sm text-sky-700">Refresh</button>
      </header>
      {error && <p className="mb-3 rounded bg-amber-50 p-2 text-sm text-amber-900">{error}</p>}
      {tab === "runs" && (
        <div className="grid gap-4 lg:grid-cols-[520px_minmax(0,1fr)]">
          <div className="max-h-[85vh] overflow-auto rounded-lg border border-slate-200 bg-white">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-slate-50 text-left text-slate-500"><tr>{["client", "question", "route", "status", "calls", "tokens", "ms"].map((h) => <th key={h} className="p-2">{h}</th>)}</tr></thead>
              <tbody>{runs.map((r) => (
                <tr key={r.run_id} onClick={() => open(r.run_id)} className={`cursor-pointer border-t border-slate-100 hover:bg-slate-50 ${sel?.state.run_id === r.run_id ? "bg-sky-50" : ""}`}>
                  <td className="p-2">{r.client_id}</td><td className="max-w-40 truncate p-2">{r.request_text || r.preset}</td><td className="p-2">{r.route}</td>
                  <td className="p-2">{r.status}</td><td className="p-2">{r.llm_calls}</td><td className="p-2">{r.tokens}</td><td className="p-2">{r.wall_ms}</td>
                </tr>))}</tbody>
            </table>
          </div>
          {sel ? (
            <div className="space-y-3">
              <PipelineStepper events={sel.events} />
              <div className="grid gap-3 xl:grid-cols-2">
                <div className="flex h-[60vh] flex-col rounded-lg border border-slate-200 bg-white p-3"><TracePanel events={sel.events} /><RunStats events={sel.events} /></div>
                <div className="space-y-3 text-xs">
                  <div className="rounded-lg border border-slate-200 bg-white p-3"><b>Gates</b>
                    <ul>{sel.state.gate_results.map((g, i) => <li key={i}>{g.gate} {g.passed ? "✓" : `✗ ${g.violations.join(" | ")}`}</li>)}</ul></div>
                  <div className="rounded-lg border border-slate-200 bg-white p-3"><b>Evaluator</b>
                    <ul>{sel.state.eval_verdicts.map((v, i) => <li key={i}>#{i + 1} {v.verdict} · {JSON.stringify(v.scores)} {v.issues.map((x) => x.criterion).join(", ")}</li>)}</ul></div>
                  <div className="rounded-lg border border-slate-200 bg-white p-3"><b>Cost</b> ${sel.cost_usd.toFixed(4)} · mode {sel.state.mode ?? "—"} · thread {sel.state.thread_id ?? "—"}</div>
                  <details className="rounded-lg border border-slate-200 bg-white p-3"><summary>Raw state</summary><pre className="max-h-96 overflow-auto">{JSON.stringify(sel.state, null, 1)}</pre></details>
                </div>
              </div>
            </div>
          ) : <p className="text-sm text-slate-500">Select a run.</p>}
        </div>
      )}
      {tab === "usage" && usage && (
        <div className="rounded-lg border border-slate-200 bg-white p-3 text-sm">
          <p>Daily cap {usage.daily_call_cap} live calls per model · {usage.free_tier ? "free tier: cost shown as $0" : "priced from settings.yaml"}</p>
          <table className="mt-2 w-full text-xs"><thead className="text-left text-slate-500"><tr>{["day", "model", "calls", "tokens in", "tokens out", "cost"].map((h) => <th key={h} className="p-1">{h}</th>)}</tr></thead>
            <tbody>{usage.rows.map((r: Row) => <tr key={r.day + r.model} className="border-t border-slate-100"><td className="p-1">{r.day}</td><td className="p-1">{r.model}</td><td className="p-1">{r.calls}</td><td className="p-1">{r.tokens_in}</td><td className="p-1">{r.tokens_out}</td><td className="p-1">${r.cost_usd.toFixed(4)}</td></tr>)}</tbody></table>
        </div>
      )}
      {tab === "evals" && <pre className="overflow-auto rounded-lg border border-slate-200 bg-white p-3 text-xs">{report}</pre>}
    </div>
  );
}
