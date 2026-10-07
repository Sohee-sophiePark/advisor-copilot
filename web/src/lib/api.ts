import { beforeApproval, playEvents } from "./player";
import type { Decision, ReplayDoc, RunSource, RunState, TraceEvent } from "./types";

const json = async (url: string, init?: RequestInit) => {
  const r = await fetch(url, init);
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
};
const post = (url: string, body: unknown) =>
  json(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

async function eventsAfter(runId: string, seq: number): Promise<TraceEvent[]> {
  const text = await (await fetch(`/api/runs/${runId}/events`)).text();
  return text.split("\n").filter((l) => l.startsWith("data:")).map((l) => JSON.parse(l.slice(5)) as TraceEvent).filter((e) => e.seq > seq);
}

let held: TraceEvent[] = [];
let lastDoc: ReplayDoc | null = null;

export const liveSource: RunSource = {
  mode: "live",
  async info() {
    const h = await json("/api/health");
    return { badge: h.run_mode === "live" ? "LIVE" : "REPLAY", models: h.models };
  },
  clients: () => json("/api/clients"),
  scenarios: () => json("/api/replays"),
  run(req, onEvent) {
    let es: EventSource | undefined;
    const done = (async () => {
      const { run_id } = await post("/api/runs", req);
      await new Promise<void>((resolve) => {
        es = new EventSource(`/api/runs/${run_id}/events`);
        es.onmessage = (m) => {
          const e = JSON.parse(m.data) as TraceEvent;
          onEvent(e);
          if (e.type === "run_completed" || e.type === "run_failed") { es!.close(); resolve(); }
        };
        es.onerror = () => { es!.close(); resolve(); };
      });
      lastDoc = null;
      return json(`/api/runs/${run_id}`) as Promise<RunState>;
    })();
    return { done, cancel: () => es?.close() };
  },
  play(id, speed, onEvent) {
    let inner: ReturnType<typeof playEvents> | undefined;
    const done = (async () => {
      lastDoc = (await json(`/api/replays/${id}`)) as ReplayDoc;
      inner = playEvents(lastDoc.events, speed, onEvent);
      held = await inner.done;
      return beforeApproval(lastDoc.final_state);
    })();
    return { done, cancel: () => inner?.cancel() };
  },
  async approve(state, decision, note): Promise<Decision> {
    if (lastDoc) return { state: lastDoc.final_state, outbox: lastDoc.outbox, events: held };
    const r = await post(`/api/runs/${state.run_id}/approval`, { decision, advisor_note: note });
    const all = await eventsAfter(state.run_id, 0);
    const seq = all.find((e) => e.type === "run_completed")?.seq ?? 0;
    return { state: r.state, outbox: r.outbox, events: all.filter((e) => e.seq > seq) };
  },
};
