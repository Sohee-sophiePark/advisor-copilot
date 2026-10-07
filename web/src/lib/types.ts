export type Severity = "critical" | "warning" | "info";
export interface TraceEvent { seq: number; run_id: string; ts: string; t_ms: number; type: string; agent: string; level: "info" | "warn" | "error"; payload: Record<string, any> }
export interface Metric { key: string; value: number; unit: string; label: string; source_tool: string }
export interface Finding { finding_id: string; title: string; severity: Severity; detail: string; metric_refs: string[]; flag_refs: string[] }
export interface Action { action_id: string; type: string; target: string; direction: string; description: string; rationale: string; finding_refs: string[]; priority: "high" | "medium" | "low" }
export interface Recommendation { headline: string; summary: string; actions: Action[]; risks_and_considerations: string[]; deferred: { finding_id: string; reason: string }[]; client_talking_points: string[] }
export interface EvalIssue { criterion: string; detail: string; suggested_fix: string }
export interface RunState {
  run_id: string; client_id: string; request_text: string; preset: string | null; status: string;
  route: { route: string; domains: string[]; reason: string; confidence: number } | null;
  analyst_reports: Record<string, { agent: string; findings: Finding[]; data_gaps: string[]; status: string }>;
  metrics: Record<string, Metric>; flags: Record<string, { flag_id: string; severity: Severity; message: string }>;
  drafts: Recommendation[]; final: { recommendation: Recommendation; disclosure: string; metrics_used: Metric[] } | null;
  message: string | null; approval: { decision: string; advisor_note: string } | null;
  budget_snapshot: Record<string, number>; revision_count: number;
  eval_verdicts: { verdict: string; checks: Record<string, boolean>; scores: Record<string, number>; issues: EvalIssue[] }[];
  untrusted_flags: Record<string, any>[]; error: string | null;
}
export interface ClientSummary { client_id: string; name: string; age: number; risk_profile: string | null; total_cad: number; flag_count: number | null; kyc_complete: boolean }
export interface Scenario { scenario_id: string; title: string; client_id: string }
export interface Outbox { tasks: Record<string, string>[]; notes: Record<string, string>[] }
export interface ReplayDoc extends Scenario { request_text: string; preset: string | null; recorded_at: string; model_ids: Record<string, string>; events: TraceEvent[]; final_state: RunState; outbox: Outbox | null }
export interface RunRequest { client_id: string; request_text: string; preset?: string }
export interface RunHandle { done: Promise<RunState>; cancel: () => void }
export interface Decision { state: RunState; outbox: Outbox | null; events: TraceEvent[] }
export interface RunSource {
  mode: "live" | "static";
  info(): Promise<{ badge: string; models: Record<string, string> }>;
  clients(): Promise<ClientSummary[]>;
  scenarios(): Promise<Scenario[]>;
  run(req: RunRequest, onEvent: (e: TraceEvent) => void): RunHandle;
  play(scenarioId: string, speed: number, onEvent: (e: TraceEvent) => void): RunHandle;
  approve(state: RunState, decision: "approve" | "reject", note: string): Promise<Decision>;
}
