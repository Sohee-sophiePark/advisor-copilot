import type { Scenario } from "../lib/types";

export const PRESETS = [
  { label: "Annual review", preset: "annual_review", request: "" },
  { label: "TFSA question", request: "How much TFSA room does Daniel have and what should go in it?" },
  { label: "Out-of-scope test", request: "Which crypto will 10x this year?" },
];

export function RequestBox({ request, preset, running, onChange, onRun }: {
  request: string; preset?: string; running: boolean; onChange: (request: string, preset?: string) => void; onRun: () => void;
}) {
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1">
        {PRESETS.map((p) => (
          <button key={p.label} onClick={() => onChange(p.request, p.preset)}
            className={`rounded-full border px-2.5 py-0.5 text-xs ${preset === p.preset && request === p.request ? "border-teal-600 bg-teal-50 text-teal-800" : "border-slate-200 bg-white"}`}>
            {p.label}
          </button>
        ))}
      </div>
      <textarea value={request} onChange={(e) => onChange(e.target.value, undefined)} rows={3} maxLength={1000}
        placeholder="Or type a request for the selected client"
        className="w-full rounded-lg border border-slate-200 bg-white p-2 text-sm" />
      <button onClick={onRun} disabled={running}
        className="w-full rounded-lg bg-teal-700 py-2 text-sm font-medium text-white disabled:opacity-40">
        {running ? "Running…" : "Run"}
      </button>
    </div>
  );
}

export function ScenarioPicker({ scenarios, running, speed, onSpeed, onPlay }: {
  scenarios: Scenario[]; running: boolean; speed: number; onSpeed: (s: number) => void; onPlay: (id: string) => void;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-xs text-slate-600">
        Speed
        {[1, 4].map((s) => (
          <button key={s} onClick={() => onSpeed(s)}
            className={`rounded-full border px-2 py-0.5 ${speed === s ? "border-teal-600 bg-teal-50 text-teal-800" : "border-slate-200 bg-white"}`}>{s}x</button>
        ))}
      </div>
      {scenarios.map((s) => (
        <button key={s.scenario_id} onClick={() => onPlay(s.scenario_id)} disabled={running}
          className="w-full rounded-lg border border-slate-200 bg-white p-3 text-left text-sm hover:border-slate-300 disabled:opacity-40">
          <span className="mr-2 font-mono text-xs text-slate-500">{s.scenario_id}</span>{s.title}
        </button>
      ))}
    </div>
  );
}
