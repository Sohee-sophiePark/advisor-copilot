import type { TraceEvent } from "../lib/types";

export function RunStats({ events }: { events: TraceEvent[] }) {
  const done = events.filter((e) => e.type === "llm_call_finished").map((e) => e.payload);
  const stats = [
    ["LLM calls", done.length], ["tokens in", done.reduce((s, p) => s + p.tokens_in, 0)], ["tokens out", done.reduce((s, p) => s + p.tokens_out, 0)],
    ["wall", `${events.at(-1)?.t_ms ?? 0} ms`], ["retries", events.filter((e) => e.type === "llm_retry").length], ["cost", "$0.00"],
  ] as const;
  return (
    <div className="grid grid-cols-3 gap-1 border-t border-slate-200 pt-2 text-[11px] text-slate-600 sm:grid-cols-6">
      {stats.map(([k, v]) => <div key={k}><div className="uppercase tracking-wide text-slate-400">{k}</div><div className="font-mono text-slate-800">{v}</div></div>)}
    </div>
  );
}
