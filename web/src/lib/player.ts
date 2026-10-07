import type { RunState, TraceEvent } from "./types";

const TERMINAL = new Set(["run_completed", "run_failed"]);

/** Re-emit events honouring recorded gaps (÷ speed, capped at 3 s); stops after the terminal event and returns the rest. */
export function playEvents(events: TraceEvent[], speed: number, onEvent: (e: TraceEvent) => void) {
  let cancelled = false;
  const done = (async () => {
    let prev = 0;
    for (const [i, e] of events.entries()) {
      const wait = Math.min((e.t_ms - prev) / speed, 3000);
      prev = e.t_ms;
      if (wait > 0) await new Promise((r) => setTimeout(r, wait));
      if (cancelled) throw new Error("cancelled");
      onEvent(e);
      if (TERMINAL.has(e.type)) return events.slice(i + 1);
    }
    return [] as TraceEvent[];
  })();
  return { done, cancel: () => { cancelled = true; } };
}

/** The run as it looked before the recorded approval, so the viewer can click Approve/Reject. */
export function beforeApproval(state: RunState): RunState {
  return state.approval ? { ...state, approval: null, status: "AWAITING_APPROVAL" } : state;
}
