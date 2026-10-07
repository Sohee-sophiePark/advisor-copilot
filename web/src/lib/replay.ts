import { beforeApproval, playEvents } from "./player";
import type { Decision, ReplayDoc, RunSource, TraceEvent } from "./types";

const docs = Object.values(import.meta.glob("../../../replays/*.json", { eager: true, import: "default" })) as ReplayDoc[];
let held: TraceEvent[] = [];
let lastDoc: ReplayDoc | null = null;

export const staticSource: RunSource = {
  mode: "static",
  async info() {
    return { badge: "REPLAY", models: docs[0]?.model_ids ?? {} };
  },
  async clients() { return []; },
  async scenarios() { return docs.map(({ scenario_id, title, client_id }) => ({ scenario_id, title, client_id })); },
  run() { throw new Error("live runs need the API; this build is replay-only"); },
  play(id, speed, onEvent) {
    lastDoc = docs.find((d) => d.scenario_id === id) ?? null;
    if (!lastDoc) throw new Error(`no replay for ${id}`);
    const inner = playEvents(lastDoc.events, speed, onEvent);
    const doc = lastDoc;
    const done = inner.done.then((rest) => { held = rest; return beforeApproval(doc.final_state); });
    return { done, cancel: inner.cancel };
  },
  async approve(): Promise<Decision> {
    return { state: lastDoc!.final_state, outbox: lastDoc!.outbox, events: held };
  },
};
