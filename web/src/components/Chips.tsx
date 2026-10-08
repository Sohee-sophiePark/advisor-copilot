import { formatValue } from "../lib/format";
import type { Metric } from "../lib/types";

const PLACEHOLDER = /\{\{([mh]):([^}]+)\}\}/g;

/** Placeholders filled as plain text (household names, formatted values), e.g. for a follow-up question to send. */
export const plainText = (text: string, metrics: Record<string, Metric>, names: Record<string, string> = {}) =>
  text.replace(PLACEHOLDER, (_, kind, key) => (kind === "h" ? names[key] ?? key : metrics[key] ? formatValue(metrics[key].value, metrics[key].unit) : key));

/** Text with every {{m:key}} shown as a number chip (hover: what it is, where it came from) and every {{h:id}} as a link to the household. */
export function Chips({ text, metrics, names = {} }: { text: string; metrics: Record<string, Metric>; names?: Record<string, string> }) {
  const parts = text.split(PLACEHOLDER);
  return (
    <>
      {parts.map((p, i) => {
        if (i % 3 === 0) return <span key={i}>{p}</span>;
        if (i % 3 === 1) return null;
        if (parts[i - 1] === "h") return <a key={i} href={`#/client/${p}`} className="font-medium text-sky-700 hover:underline">{names[p] ?? p}</a>;
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
