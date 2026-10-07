import type { Book, ClientDetail, Market, Outbox, Recorded, RunState, Source, TraceEvent } from "./types";

const json = async (url: string, init?: RequestInit) => {
  const r = await fetch(url, init);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? `${r.status}`);
  return r.json();
};
const post = (url: string, body: unknown) =>
  json(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

/** Live mode: the FastAPI backend on the advisor's laptop. */
export const liveSource: Source = {
  live: true,
  book: () => json("/api/book"),
  client: (id) => json(`/api/clients/${id}`),
  market: () => json("/api/market"),
  recorded: async () => [],
  async ask(clientId, threadId, text, preset, onEvent) {
    const tid: string = threadId ?? (await post("/api/threads", { client_id: clientId })).thread_id;
    const { run_id, cached } = await post(`/api/threads/${tid}/messages`, { text, preset });
    if (!cached) {
      await new Promise<void>((resolve) => {
        const es = new EventSource(`/api/runs/${run_id}/events`);
        es.onmessage = (m) => {
          const e = JSON.parse(m.data) as TraceEvent;
          onEvent(e);
          if (e.type === "run_completed" || e.type === "run_failed") { es.close(); resolve(); }
        };
        es.onerror = () => { es.close(); resolve(); };
      });
    }
    return { threadId: tid, state: await json(`/api/runs/${run_id}`) };
  },
  async approve(state, decision, note) {
    const r = await post(`/api/runs/${state.run_id}/approval`, { decision, advisor_note: note });
    return { state: r.state, outbox: r.outbox };
  },
};

interface StaticData { book: Book; market: Market; clients: Record<string, ClientDetail>; recorded: Record<string, Recorded[]> }
let data: Promise<StaticData> | null = null;
const load = (): Promise<StaticData> => (data ??= fetch("./static-data.json").then((r) => r.json()));
const pause = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Progress events reconstructed from a recorded state, so the replay shows the same steps. */
function steps(s: RunState): TraceEvent[] {
  const ev = (type: string, agent: string, payload: Record<string, any> = {}) =>
    ({ seq: 0, run_id: s.run_id, ts: "", t_ms: 0, type, agent, level: "info", payload }) as TraceEvent;
  if (s.status === "BLOCKED") return [ev("kyc_blocked", "gate")];
  const out = [ev("route_decided", "router", { route: s.route?.route })];
  for (const d of Object.keys(s.analyst_reports)) out.push(ev("agent_started", d), ev("agent_finished", d));
  if (s.drafts.length || s.answer) out.push(ev("draft_created", "synthesizer"));
  if (s.eval_verdicts.length) out.push(ev("evaluator_verdict", "evaluator"));
  return out;
}

/** Public demo: recorded runs bundled as JSON; no backend, no model calls. */
export const staticSource: Source = {
  live: false,
  book: async () => (await load()).book,
  client: async (id) => (await load()).clients[id],
  market: async () => (await load()).market,
  recorded: async (id) => (await load()).recorded[id] ?? [],
  async ask(clientId, _thread, text, preset, onEvent) {
    const rec = (await load()).recorded[clientId]?.find((r) => (preset ? r.preset === preset : r.question === text));
    if (!rec) throw new Error("This public demo replays recorded questions only. Live chat runs on the advisor's laptop.");
    for (const e of steps(rec.state)) { await pause(350); onEvent(e); }
    const s = rec.state;
    return { threadId: null, state: s.approval ? { ...s, approval: null, status: "AWAITING_APPROVAL" } : s };
  },
  async approve(state, decision, note) {
    const rec = (await load()).recorded[state.client_id]?.find((r) => r.state.run_id === state.run_id);
    const outbox: Outbox | null = decision === "approve" ? rec?.outbox ?? null : null;
    return { state: { ...state, status: "COMPLETED", approval: { decision, advisor_note: note } }, outbox };
  },
};

export const source: Source = import.meta.env.VITE_STATIC ? staticSource : liveSource;
