import { useEffect, useRef, useState } from "react";
import { AllocationChart } from "./components/AllocationChart";
import { ApprovalBar } from "./components/ApprovalBar";
import { ClientList } from "./components/ClientList";
import { PipelineStepper } from "./components/PipelineStepper";
import { RecommendationCard } from "./components/RecommendationCard";
import { RequestBox, ScenarioPicker } from "./components/RequestBox";
import { RunStats } from "./components/RunStats";
import { TracePanel } from "./components/TracePanel";
import { liveSource } from "./lib/api";
import { staticSource } from "./lib/replay";
import type { ClientSummary, Outbox, RunHandle, RunState, Scenario, TraceEvent } from "./lib/types";

const source = import.meta.env.VITE_STATIC ? staticSource : liveSource;

export default function App() {
  const [info, setInfo] = useState<{ badge: string; models: Record<string, string> }>();
  const [clients, setClients] = useState<ClientSummary[]>([]);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [clientId, setClientId] = useState("C001");
  const [request, setRequest] = useState("");
  const [preset, setPreset] = useState<string | undefined>("annual_review");
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [state, setState] = useState<RunState | null>(null);
  const [outbox, setOutbox] = useState<Outbox | null>(null);
  const [running, setRunning] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const handle = useRef<RunHandle | null>(null);

  useEffect(() => {
    source.info().then(setInfo).catch((e) => setError(String(e)));
    source.clients().then(setClients).catch(() => undefined);
    source.scenarios().then(setScenarios).catch(() => undefined);
  }, []);

  const begin = (h: RunHandle) => {
    handle.current?.cancel();
    setEvents([]); setState(null); setOutbox(null); setError(null); setRunning(true);
    handle.current = h;
    h.done.then(setState).catch((e) => setError(String(e))).finally(() => setRunning(false));
  };
  const onEvent = (e: TraceEvent) => setEvents((prev) => [...prev, e]);
  const decide = async (decision: "approve" | "reject", note: string) => {
    const r = await source.approve(state!, decision, note);
    setState(r.state); setOutbox(r.outbox); setEvents((prev) => [...prev, ...r.events]);
  };

  return (
    <div className="mx-auto max-w-[1600px] overflow-x-hidden p-3 sm:p-5">
      <header className="mb-4 flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold tracking-tight">Advisor Copilot</h1>
        {info && (
          <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold text-white ${info.badge === "LIVE" ? "bg-emerald-600" : "bg-blue-600"}`}>{info.badge}</span>
        )}
        {info && <span className="text-xs text-slate-500">{[...new Set(Object.values(info.models))].join(" · ")}</span>}
        <span className="ml-auto rounded-md bg-amber-100 px-2 py-1 text-xs text-amber-900">All clients, instruments and market data are fictional</span>
      </header>
      {error && <div className="mb-3 rounded-md bg-red-50 p-2 text-sm text-red-800">{error}</div>}
      <div className="grid gap-4 lg:grid-cols-[300px_minmax(0,1fr)_400px]">
        <aside className="min-w-0 space-y-4">
          {source.mode === "live" && (
            <>
              <ClientList clients={clients} selected={clientId} onSelect={setClientId} />
              <RequestBox request={request} preset={preset} running={running}
                onChange={(r, p) => { setRequest(r); setPreset(p); }}
                onRun={() => begin(source.run({ client_id: clientId, request_text: request, preset }, onEvent))} />
            </>
          )}
          {scenarios.length > 0 && (
            <div>
              <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Recorded runs</div>
              <ScenarioPicker scenarios={scenarios} running={running} speed={speed} onSpeed={setSpeed} onPlay={(id) => begin(source.play(id, speed, onEvent))} />
            </div>
          )}
        </aside>
        <main className="min-w-0 space-y-3">
          <PipelineStepper events={events} />
          {state && <AllocationChart metrics={state.metrics} />}
          {state && <RecommendationCard state={state} />}
          {state && <ApprovalBar state={state} outbox={outbox} onDecide={decide} />}
          {!state && !running && <div className="rounded-lg border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">Pick a client and run, or play a recorded run.</div>}
        </main>
        <aside className="flex h-[70vh] min-w-0 flex-col rounded-lg border border-slate-200 bg-white p-3 lg:h-[calc(100vh-7rem)]">
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Trace</div>
          <TracePanel events={events} />
          <RunStats events={events} />
        </aside>
      </div>
    </div>
  );
}
