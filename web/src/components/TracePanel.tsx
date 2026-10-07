import { useState } from "react";
import { AGENT_COLOR } from "../lib/format";
import type { TraceEvent } from "../lib/types";

const ICON: Record<string, string> = {
  llm_call_started: "✦", llm_call_finished: "✦", tool_call: "⚙", gate_result: "⛨", evaluator_verdict: "⚖", llm_retry: "⟳",
  injection_flagged: "⚠", kyc_blocked: "⛔", budget_exhausted: "⛔", run_failed: "✖", approval_recorded: "✍", crm_outbox_written: "✉",
};

function summary(e: TraceEvent): string {
  const p = e.payload;
  switch (e.type) {
    case "llm_call_finished": return `${p.purpose} · ${p.tokens_in}/${p.tokens_out} tok · ${p.latency_ms} ms · attempt ${p.attempt} · ${p.source}`;
    case "llm_call_started": return `${p.purpose} → ${p.model}`;
    case "tool_call": return `${p.name} · ${p.metrics_count} metrics${p.flags?.length ? " · flags " + p.flags.map((f: any) => f.id).join(", ") : ""}${p.error ? " · " + p.error : ""}`;
    case "gate_result": return `${p.gate} ${p.passed ? "✓" : "✗ " + p.violations.join(" | ")}`;
    case "evaluator_verdict": return `${p.passed ? "pass" : "revise"} · scores ${Object.values(p.scores).join("/")} · ${p.issues_count} issues`;
    case "route_decided": return `${p.route} [${p.domains.join(", ")}] conf ${p.confidence}${p.fast_path ? " · fast path" : ""}`;
    case "injection_flagged": return `${p.source} ${p.id}: ${p.pattern}${p.redacted ? " (redacted)" : ""}`;
    case "llm_retry": return `HTTP ${p.status}, waiting ${p.wait_ms} ms (attempt ${p.attempt})`;
    case "agent_finished": return `${p.findings_count} findings · ${p.status}`;
    case "revision_requested": return `${p.source}: ${p.items.join(" | ")}`;
    case "run_completed": return `${p.status} · ${p.totals.llm_calls} calls · ${p.totals.wall_ms} ms`;
    default: return Object.entries(p).slice(0, 3).map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v).slice(0, 40) : v}`).join(" ");
  }
}

export function TracePanel({ events }: { events: TraceEvent[] }) {
  const [filter, setFilter] = useState<string | null>(null);
  const agents = [...new Set(events.map((e) => e.agent))];
  const shown = filter ? events.filter((e) => e.agent === filter) : events;
  return (
    <div className="flex h-full flex-col">
      <div className="mb-2 flex flex-wrap gap-1">
        {agents.map((a) => (
          <button key={a} onClick={() => setFilter(filter === a ? null : a)}
            className={`rounded-full border px-2 py-0.5 text-[11px] ${filter === a ? "bg-slate-800 text-white" : "bg-white"}`} style={{ borderColor: AGENT_COLOR[a] ?? "#cbd5e1" }}>{a}</button>
        ))}
      </div>
      <ol className="min-h-0 flex-1 space-y-0.5 overflow-auto font-mono text-[11px] leading-snug">
        {shown.map((e) => (
          <li key={e.seq} className={`flex gap-2 rounded px-1 ${e.level === "error" ? "bg-red-50" : e.level === "warn" ? "bg-amber-50" : ""}`}>
            <span className="w-14 shrink-0 text-right text-slate-400">{e.t_ms} ms</span>
            <span className="w-3 shrink-0 text-center">{ICON[e.type] ?? "·"}</span>
            <span className="w-20 shrink-0 truncate" style={{ color: AGENT_COLOR[e.agent] ?? "#334155" }}>{e.agent}</span>
            <span className="min-w-0 flex-1 break-words"><span className="text-slate-500">{e.type}</span> {summary(e)}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}
