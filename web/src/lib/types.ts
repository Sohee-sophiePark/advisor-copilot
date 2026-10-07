export type Severity = "critical" | "warning" | "info";
export type Level = "critical" | "warning" | "kyc" | "review";
export interface TraceEvent { seq: number; run_id: string; ts: string; t_ms: number; type: string; agent: string; level: "info" | "warn" | "error"; payload: Record<string, any> }
export interface Metric { key: string; value: number; unit: string; label: string; source_tool: string }
export interface Finding { finding_id: string; title: string; severity: Severity; detail: string; metric_refs: string[]; flag_refs: string[] }
export interface Action { action_id: string; type: string; target: string; direction: string; description: string; rationale: string; finding_refs: string[]; priority: "high" | "medium" | "low" }
export interface Recommendation { headline: string; summary: string; actions: Action[]; risks_and_considerations: string[]; deferred: { finding_id: string; reason: string }[]; client_talking_points: string[] }
export interface EvalIssue { criterion: string; detail: string; suggested_fix: string }
export interface RunState {
  run_id: string; client_id: string; request_text: string; preset: string | null; thread_id: string | null;
  mode: "recommendation" | "answer" | null; status: string;
  route: { route: string; domains: string[]; reason: string; confidence: number } | null;
  analyst_reports: Record<string, { agent: string; findings: Finding[]; data_gaps: string[]; status: string }>;
  metrics: Record<string, Metric>; flags: Record<string, { flag_id: string; severity: Severity; message: string }>;
  drafts: Recommendation[]; final: { recommendation: Recommendation; disclosure: string } | null;
  answer: { answer: string; suggested_questions: string[] } | null;
  message: string | null; approval: { decision: string; advisor_note: string } | null;
  budget_snapshot: Record<string, number>; revision_count: number; created_at?: string;
  eval_verdicts: { verdict: string; checks: Record<string, boolean>; scores: Record<string, number>; issues: EvalIssue[] }[];
  gate_results: { gate: string; passed: boolean; violations: string[] }[];
  untrusted_flags: Record<string, any>[]; error: string | null;
}
export interface Outbox { tasks: Record<string, string>[]; notes: Record<string, string>[] }
export interface Attention { level: Level; text: string; flag_id?: string }
export interface Household {
  client_id: string; name: string; age: number; life_stage: string | null; risk_profile: string | null;
  total_cad: number; aum_tier: string; review_due: string | null; attention: Attention[]; top_level: Level | null;
}
export interface Book { as_of: string; stats: Record<string, number>; households: Household[] }
export interface ClientDetail extends Household {
  profile: Record<string, any>; metrics: Record<string, number>;
  allocation: { asset_class: string; current_pct: number; target_pct: number | null }[];
  accounts: { type: string; value_cad: number; holdings: { ticker: string; name: string; asset_class: string; units: number; value_cad: number }[] }[];
  goals: { goal_id: string; name: string; target_cad: number; target_year: number; required_pct: number | null; model_pct: number | null }[];
  flags: { flag_id: string; severity: Severity; message: string }[];
  notes: { note_id: string; date: string; author: string; text: string }[];
}
export interface Indicator { key: string; label: string; value: number; asset_classes: string[]; history: number[]; most_exposed: { client_id: string; name: string; weight_pct: number }[] }
export interface Market { as_of: string; label: string; months: string[]; indicators: Indicator[]; headlines: { id: string; text: string }[] }
export interface Recorded { scenario_id: string; title: string; question: string; preset: string | null; state: RunState; outbox: Outbox | null }
export interface Source {
  live: boolean;
  book(): Promise<Book>;
  client(id: string): Promise<ClientDetail>;
  market(): Promise<Market>;
  recorded(id: string): Promise<Recorded[]>;
  ask(clientId: string, threadId: string | null, text: string, preset: string | undefined, onEvent: (e: TraceEvent) => void): Promise<{ threadId: string | null; state: RunState }>;
  approve(state: RunState, decision: "approve" | "reject", note: string): Promise<{ state: RunState; outbox: Outbox | null }>;
}
