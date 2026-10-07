import { formatValue } from "../lib/format";
import type { Metric } from "../lib/types";

const PLACEHOLDER = /\{\{m:([^}]+)\}\}/g;

/** Text with every {{m:key}} rendered as a chip whose tooltip shows key · source tool · raw value. */
export function Chips({ text, metrics }: { text: string; metrics: Record<string, Metric> }) {
  const parts = text.split(PLACEHOLDER);
  return (
    <>
      {parts.map((p, i) => {
        if (i % 2 === 0) return <span key={i}>{p}</span>;
        const m = metrics[p];
        return m ? (
          <span key={i} title={`${m.key} · ${m.source_tool} · ${m.value}`}
            className="mx-0.5 rounded bg-sky-50 px-1.5 py-0.5 font-mono text-[0.9em] text-sky-900 ring-1 ring-sky-200">
            {formatValue(m.value, m.unit)}
          </span>
        ) : <span key={i} className="text-red-600">{`{{m:${p}}}`}</span>;
      })}
    </>
  );
}
