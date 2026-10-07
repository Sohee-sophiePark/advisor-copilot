export function formatValue(v: number, unit: string): string {
  if (unit === "pct") return `${v.toFixed(1)}%`;
  if (unit === "pp") return `${v >= 0 ? "+" : ""}${v.toFixed(1)} pp`;
  if (unit === "cad") return `${v < 0 ? "-" : ""}$${Math.abs(Math.round(v)).toLocaleString("en-CA")}`;
  if (unit === "years") return `${Math.round(v)} years`;
  return v.toFixed(2);
}

export const AGENT_COLOR: Record<string, string> = {
  portfolio: "#2a78d6", risk: "#eb6834", router: "#1baf7a", tax: "#eda100", market: "#e87ba4",
  synthesizer: "#008300", gate: "#4a3aa7", evaluator: "#e34948", orchestrator: "#52514e", human: "#52514e", system: "#898781",
};
export const SEVERITY_COLOR: Record<string, string> = { critical: "#d03b3b", warning: "#c98500", info: "#64748b" };
export const DOMAINS = ["portfolio", "risk", "tax", "market"] as const;
