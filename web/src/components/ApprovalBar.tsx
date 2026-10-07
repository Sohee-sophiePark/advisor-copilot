import { useState } from "react";
import type { Outbox, RunState } from "../lib/types";

/** Human approval: nothing is created in the CRM until the advisor approves. */
export function ApprovalBar({ state, outbox, onDecide }: { state: RunState; outbox: Outbox | null; onDecide: (d: "approve" | "reject", note: string) => void }) {
  const [note, setNote] = useState("");
  if (state.approval) {
    return (
      <div className="space-y-2 text-sm">
        <div className={`rounded-lg p-2 ${state.approval.decision === "approve" ? "bg-emerald-50 text-emerald-800" : "bg-slate-100"}`}>
          {state.approval.decision === "approve" ? "✓ Approved. Tasks and a note were prepared for the CRM." : "Rejected. Nothing was sent."}
          {state.approval.advisor_note && ` Note: ${state.approval.advisor_note}`}
        </div>
        {outbox && (
          <ul className="rounded-lg border border-slate-200 p-2">
            {outbox.tasks.map((t, i) => <li key={i}>☐ {t.Subject} <span className="text-xs text-slate-500">({t.Priority})</span></li>)}
          </ul>
        )}
      </div>
    );
  }
  if (state.status !== "AWAITING_APPROVAL") return null;
  return (
    <div className="flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
      <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note (optional)" className="min-w-40 flex-1 rounded-lg border border-slate-200 p-1.5 text-sm" />
      <button onClick={() => onDecide("approve", note)} className="rounded-lg bg-emerald-700 px-3 py-1.5 text-sm text-white">Approve</button>
      <button onClick={() => onDecide("reject", note)} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm">Reject</button>
    </div>
  );
}
