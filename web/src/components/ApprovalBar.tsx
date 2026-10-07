import { useState } from "react";
import type { Outbox, RunState } from "../lib/types";

export function ApprovalBar({ state, outbox, onDecide }: { state: RunState; outbox: Outbox | null; onDecide: (d: "approve" | "reject", note: string) => void }) {
  const [note, setNote] = useState("");
  if (state.approval) {
    return (
      <div className="space-y-2">
        <div className={`rounded-md p-2 text-sm ${state.approval.decision === "approve" ? "bg-emerald-50 text-emerald-800" : "bg-slate-100"}`}>
          Advisor {state.approval.decision === "approve" ? "approved" : "rejected"} this recommendation{state.approval.advisor_note && `: ${state.approval.advisor_note}`}
        </div>
        {outbox && <OutboxViewer outbox={outbox} />}
      </div>
    );
  }
  if (state.status !== "AWAITING_APPROVAL") return null;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Advisor note (optional)" className="min-w-40 flex-1 rounded border border-slate-200 p-1.5 text-sm" />
      <button onClick={() => onDecide("approve", note)} className="rounded bg-emerald-700 px-3 py-1.5 text-sm text-white">Approve</button>
      <button onClick={() => onDecide("reject", note)} className="rounded border border-slate-300 px-3 py-1.5 text-sm">Reject</button>
    </div>
  );
}

export function OutboxViewer({ outbox }: { outbox: Outbox }) {
  return (
    <div>
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">CRM outbox (mock, nothing sent)</div>
      <pre className="mt-1 max-h-64 overflow-auto rounded bg-slate-900 p-3 text-xs text-slate-100">{JSON.stringify(outbox, null, 2)}</pre>
    </div>
  );
}
