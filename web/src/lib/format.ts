export function formatValue(v: number, unit: string): string {
  if (unit === "pct") return `${v.toFixed(1)}%`;
  if (unit === "pp") return `${v >= 0 ? "+" : ""}${v.toFixed(1)} pp`;
  if (unit === "cad") return `${v < 0 ? "-" : ""}$${Math.abs(Math.round(v)).toLocaleString("en-CA")}`;
  if (unit === "years") return `${Math.round(v)} years`;
  return v.toFixed(2);
}

export const money = (v: number) =>
  v >= 1e6 ? `$${(v / 1e6).toFixed(1)}M` : v >= 1e4 ? `$${Math.round(v / 1e3)}k` : `$${Math.round(v).toLocaleString("en-CA")}`;

const WORDS: Record<string, string> = {
  CASH: "Cash", CA_BONDS: "Canadian bonds", CA_EQUITY: "Canadian equity", US_EQUITY: "US equity",
  INTL_EQUITY: "International equity", REAL_ASSETS: "Real estate", NON_REG: "Non-registered",
  accumulation: "Building wealth", pre_retirement: "Pre-retirement", retirement: "Retired",
  rebalance: "Rebalance", reduce_position: "Reduce position", relocate_holding: "Move holding",
  use_tfsa_room: "Use TFSA room", review_kyc: "Update KYC or goals", no_action: "No change needed",
};
export const word = (k: string | null | undefined) => (k ? WORDS[k] ?? k.charAt(0).toUpperCase() + k.slice(1).replaceAll("_", " ") : "—");

export const AGENT_COLOR: Record<string, string> = {
  portfolio: "#2a78d6", risk: "#eb6834", router: "#1baf7a", tax: "#eda100", market: "#e87ba4",
  synthesizer: "#008300", gate: "#4a3aa7", evaluator: "#e34948", orchestrator: "#52514e", human: "#52514e", system: "#898781",
};
export const DOMAINS = ["portfolio", "risk", "tax", "market"] as const;
