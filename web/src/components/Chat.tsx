import { useEffect, useRef, useState } from "react";
import { source } from "../lib/source";
import type { Outbox, PastThread, Recorded, RunState, TraceEvent } from "../lib/types";
import { ApprovalBar } from "./ApprovalBar";
import { Chips } from "./Chips";
import { RecommendationCard } from "./RecommendationCard";

const FAQ: { label: string; preset?: string }[] = [
  { label: "Prepare annual review", preset: "annual_review" },
  { label: "Is the portfolio still suitable?" },
  { label: "Where can I save tax?" },
  { label: "How would a market drop affect them?" },
  { label: "Are their goals on track?" },
  { label: "What should I raise in the meeting?" },
  { label: "What if we sell half of the biggest single stock into bonds?" },
  { label: "How do today's rates and commodity prices affect this client?" },
  { label: "What is driving the drift in this portfolio?" },
];
export const BOOK = "BOOK";
const BOOK_FAQ = [
  "Who should I call first this week?", "Which households are above their risk limit?", "Who is most exposed to energy?",
  "If energy falls another 10%, who is hit hardest?", "Who has unused TFSA room with taxable cash?", "Whose goals need more return than their profile allows?",
  "If bond prices fall 5%, who is hit hardest?", "Who is most exposed to US stocks and the US dollar?",
].map((label) => ({ label, preset: undefined }));

interface Turn { question: string; events: TraceEvent[]; state?: RunState; outbox?: Outbox | null; error?: string }

/** Friendly progress derived from the run's events; no engineering detail. */
function Progress({ events }: { events: TraceEvent[] }) {
  const has = (t: string, agent?: string) => events.some((e) => e.type === t && (!agent || e.agent === agent));
  const lanes = ["portfolio", "risk", "tax", "market", "scenario", "book"].filter((d) => has("agent_started", d));
  const label: Record<string, string> = { scenario: "Running the what-if", book: "Looking across your book" };
  const steps: [string, boolean][] = [
    ["Compliance checks", true],
    ["Understanding the question", has("route_decided")],
    ...lanes.map((d): [string, boolean] => [label[d] ?? `Reviewing ${d}`, has("agent_finished", d)]),
    ["Writing the answer", has("draft_created")],
  ];
  return (
    <ul className="space-y-1 text-sm text-slate-600">
      {steps.map(([label, done]) => <li key={label}>{done ? "✓" : "…"} {label}</li>)}
    </ul>
  );
}

function Reply({ t, names, onAsk, onDecide }: { t: Turn; names: Record<string, string>; onAsk: (q: string) => void; onDecide: (d: "approve" | "reject", n: string) => void }) {
  if (t.error) return <div className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">{t.error}</div>;
  const s = t.state;
  if (!s) return <Progress events={t.events} />;
  if (s.status === "BLOCKED") return (
    <div className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900"><b>◆ {s.message}</b>
      <div className="mt-1">Advice is paused until the KYC is updated. No analysis was run.</div></div>
  );
  if (s.route?.route === "out_of_scope") return <div className="text-sm text-slate-700">{s.message}</div>;
  if (s.status === "FAILED" || s.status === "DEGRADED") return (
    <div className="rounded-lg bg-red-50 p-3 text-sm text-red-800">The copilot could not finish this one ({s.error ?? s.status}). Please try again.</div>
  );
  return (
    <div className="space-y-3">
      {s.status === "NEEDS_ADVISOR_REVIEW" && <div className="rounded-lg bg-amber-50 p-2 text-sm text-amber-900">▲ Draft did not pass every compliance check; review carefully before using it.</div>}
      {s.mode === "recommendation" ? <RecommendationCard state={s} /> : s.answer && (
        <div className="space-y-2 text-sm">
          <p className="leading-relaxed text-slate-800"><Chips text={s.answer.answer} metrics={s.metrics} names={names} /></p>
          <div className="flex flex-wrap gap-1">{s.answer.suggested_questions.map((q) => (
            <button key={q} onClick={() => onAsk(q)} className="rounded-full border border-slate-200 px-2.5 py-0.5 text-xs hover:bg-slate-50">{q}</button>))}</div>
        </div>
      )}
      <ApprovalBar state={s} outbox={t.outbox ?? null} onDecide={onDecide} />
    </div>
  );
}

/** Review & Ask: one conversation per client (or for the whole book); presets for the most frequent questions. */
export function Chat({ clientId }: { clientId: string }) {
  const book = clientId === BOOK;
  const [names, setNames] = useState<Record<string, string>>({});
  const [turns, setTurns] = useState<Turn[]>([]);
  const [thread, setThread] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [recorded, setRecorded] = useState<Recorded[]>([]);
  const [past, setPast] = useState<PastThread[]>([]);
  const busy = turns.some((t) => !t.state && !t.error);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { setTurns([]); setThread(null); source.recorded(clientId).then(setRecorded); }, [clientId]);
  useEffect(() => { if (book) source.book().then((b) => setNames(Object.fromEntries(b.households.map((h) => [h.client_id, h.name])))); }, [book]);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }); }, [turns]);
  useEffect(() => { source.threads(clientId).then(setPast); }, [clientId, thread]);
  const resume = async (id: string) => {
    const old = id ? await source.thread(id) : [];
    setThread(id || null);
    setTurns(old.map((t) => ({ question: t.question, events: [], state: t.state ?? undefined, error: t.state ? undefined : t.text })));
  };

  const update = (i: number, patch: Partial<Turn>) => setTurns((ts) => ts.map((t, k) => (k === i ? { ...t, ...patch } : t)));
  const ask = async (question: string, preset?: string) => {
    const i = turns.length;
    setTurns((ts) => [...ts, { question, events: [] }]);
    setText("");
    try {
      const r = await source.ask(clientId, thread, preset ? "" : question, preset, (e) =>
        setTurns((ts) => ts.map((t, k) => (k === i ? { ...t, events: [...t.events, e] } : t))));
      setThread(r.threadId);
      update(i, { state: r.state });
    } catch (e) { update(i, { error: e instanceof Error ? e.message : String(e) }); }
  };
  const decide = (i: number) => async (d: "approve" | "reject", note: string) => {
    const r = await source.approve(turns[i].state!, d, note);
    update(i, { state: r.state, outbox: r.outbox });
  };
  const chips = source.live ? (book ? BOOK_FAQ : FAQ) : recorded.map((r) => ({ label: r.question, preset: r.preset ?? undefined }));

  return (
    <div className="flex h-full flex-col rounded-xl border border-slate-200 bg-white">
      {source.live && (past.length > 0 || turns.length > 0) && (
        <div className="flex gap-2 border-b border-slate-100 p-2">
          <select value={thread ?? ""} disabled={busy} onChange={(e) => resume(e.target.value)} className="min-w-0 flex-1 rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs">
            <option value="">Past conversations ({past.length})</option>
            {past.map((p) => <option key={p.thread_id} value={p.thread_id}>{new Date(`${p.created_at.replace(" ", "T")}Z`).toLocaleString([], { dateStyle: "short", timeStyle: "short" })} · {p.title}</option>)}
          </select>
          <button disabled={busy} onClick={() => resume("")} className="rounded-lg border border-slate-200 px-2 text-xs hover:bg-slate-50 disabled:opacity-40">New conversation</button>
        </div>
      )}
      <div className="min-h-0 flex-1 space-y-4 overflow-auto p-4">
        {!turns.length && <p className="text-sm text-slate-500">{book ? "Ask about your whole book" : "Ask about this client"}, or start with a common question below.
          {!source.live && " This public demo replays recorded conversations; live chat runs on the advisor's laptop."}</p>}
        {turns.map((t, i) => (
          <div key={i} className="space-y-2">
            <div className="ml-auto w-fit max-w-[85%] rounded-xl bg-teal-700 px-3 py-2 text-sm text-white">{t.question}</div>
            <div className="max-w-[95%] rounded-xl border border-slate-100 bg-slate-50 p-3"><Reply t={t} names={names} onAsk={(q) => ask(q)} onDecide={decide(i)} /></div>
          </div>
        ))}
        <div ref={end} />
      </div>
      <div className="space-y-2 border-t border-slate-100 p-3">
        <div className="flex flex-wrap gap-1">{chips.map((c) => (
          <button key={c.label} disabled={busy} onClick={() => ask(c.label, c.preset)}
            className="rounded-full border border-slate-200 px-2.5 py-0.5 text-xs hover:bg-slate-50 disabled:opacity-40">{c.label}</button>))}
          {!source.live && !chips.length && <span className="text-xs text-slate-500">No recorded conversation for this {book ? "book" : "client"} in the public demo.</span>}
        </div>
        {source.live && (
          <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (text.trim()) ask(text.trim()); }}>
            <input value={text} onChange={(e) => setText(e.target.value)} maxLength={1000} disabled={busy}
              placeholder={book ? "Ask about your book…" : "Ask about this client…"} className="flex-1 rounded-lg border border-slate-200 p-2 text-sm" />
            <button disabled={busy || !text.trim()} className="rounded-lg bg-teal-700 px-4 text-sm text-white disabled:opacity-40">Ask</button>
          </form>
        )}
      </div>
    </div>
  );
}
