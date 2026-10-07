import { formatValue } from "../lib/format";
import type { Metric } from "../lib/types";

const PLACEHOLDER = /\{\{m:([^}]+)\}\}/g;

/** Text with every {{m:key}} shown as a number chip; hover tells the advisor what it is and where it came from. */
export function Chips({ text, metrics }: { text: string; metrics: Record<string, Metric> }) {
  return (
    <>
      {text.split(PLACEHOLDER).map((p, i) => {
        if (i % 2 === 0) return <span key={i}>{p}</span>;
        const m = metrics[p];
        return m ? (
          <span key={i} title={`${m.label} · calculated by ${m.source_tool.replaceAll("_", " ")}`}
            className="mx-0.5 rounded bg-sky-50 px-1 font-medium text-sky-900 ring-1 ring-sky-200">
            {formatValue(m.value, m.unit)}
          </span>
        ) : <span key={i}>—</span>;
      })}
    </>
  );
}
