import { DOMAINS } from "../lib/format";
import type { TraceEvent } from "../lib/types";

type Status = "pending" | "active" | "done" | "warn" | "fail";
const STYLE: Record<Status, string> = {
  pending: "border-slate-200 text-slate-400", active: "border-teal-500 text-teal-800 animate-pulse",
  done: "border-emerald-500 bg-emerald-50 text-emerald-800", warn: "border-amber-500 bg-amber-50 text-amber-800", fail: "border-red-500 bg-red-50 text-red-800",
};

function gate(events: TraceEvent[], id: string): Status {
  const g = events.filter((e) => e.type === "gate_result" && e.payload.gate === id).at(-1);
  return g ? (g.payload.passed ? "done" : id === "G1" ? "warn" : "fail") : "pending";
}

export function PipelineStepper({ events }: { events: TraceEvent[] }) {
  const has = (t: string) => events.some((e) => e.type === t);
  const evals = events.filter((e) => e.type === "evaluator_verdict");
  const drafts = events.filter((e) => e.type === "draft_created").length;
  const lastG5 = events.filter((e) => e.type === "gate_result" && e.payload.gate === "G5").at(-1);
  const approval: Status = has("approval_recorded") ? "done" : has("awaiting_approval") ? "active" : has("needs_advisor_review") ? "warn" : "pending";
  const steps: [string, Status, string?][] = [
    ["Input gate", gate(events, "G0")],
    ["KYC gate", gate(events, "G1")],
    ["Route", has("route_decided") ? "done" : "pending", events.find((e) => e.type === "route_decided")?.payload.route],
    ["Synthesis", drafts ? "done" : "pending", drafts ? `draft ${drafts}` : undefined],
    ["Output gates", lastG5 ? (lastG5.payload.passed ? "done" : "warn") : "pending"],
    ["Evaluator", evals.length ? (evals.at(-1)!.payload.passed ? "done" : "warn") : "pending", evals.length ? `iteration ${evals.length}/3` : undefined],
    ["Approval", approval],
  ];
  const lane = (d: string): Status => {
    const fin = events.find((e) => e.type === "agent_finished" && e.agent === d);
    if (fin) return fin.payload.status === "ok" ? "done" : "warn";
    return events.some((e) => e.type === "agent_started" && e.agent === d) ? "active" : "pending";
  };
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-xs">
      {steps.slice(0, 3).map(([l, s, d]) => <Pill key={l} label={l} status={s} detail={d} />)}
      <div className="flex flex-col gap-0.5 rounded-lg border border-slate-200 bg-white p-1">
        {DOMAINS.map((d) => <Pill key={d} label={d} status={lane(d)} small />)}
      </div>
      {steps.slice(3).map(([l, s, d]) => <Pill key={l} label={l} status={s} detail={d} />)}
    </div>
  );
}

function Pill({ label, status, detail, small }: { label: string; status: Status; detail?: string; small?: boolean }) {
  return (
    <span className={`rounded-full border bg-white ${small ? "px-2 py-0 text-[10px]" : "px-2.5 py-1"} ${STYLE[status]}`}>
      {label}{detail && <span className="ml-1 opacity-70">· {detail}</span>}
    </span>
  );
}
