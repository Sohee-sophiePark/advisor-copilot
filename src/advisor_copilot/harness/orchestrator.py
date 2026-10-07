"""The pipeline: gates, router, parallel analysts, synthesis/evaluation loop, render (02 §3)."""

import asyncio
import datetime as dt
import hashlib
import json
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from advisor_copilot.agents.analysts import AnalystSpec, analyst_specs
from advisor_copilot.agents.evaluator import evaluate, passes
from advisor_copilot.agents.router import OUT_OF_SCOPE_TEMPLATE, route
from advisor_copilot.agents.synthesizer import synthesize
from advisor_copilot.config import RateLimitsCfg, Settings, get_settings
from advisor_copilot.data_access import get_client, get_market, get_notes
from advisor_copilot.db import Store
from advisor_copilot.harness.agent_loop import default_args, degraded_report, run_agent
from advisor_copilot.harness.budget import BudgetExhausted, RunBudget
from advisor_copilot.harness.context import AgentContext, Feedback, SynthContext, load_prompt
from advisor_copilot.harness.deps import Deps
from advisor_copilot.harness.gates import answer_gates, input_gate, kyc_gate, output_gates
from advisor_copilot.harness.injection import detect, redact
from advisor_copilot.harness.state import RunState, RunStatus, save_state
from advisor_copilot.harness.trace import TraceBus
from advisor_copilot.llm.base import FatalLLMError, LLMClient, RetryableLLMError
from advisor_copilot.llm.cassette import CassetteClient
from advisor_copilot.llm.limiter import RateLimiter
from advisor_copilot.models import (
    BOOK,
    AnalystReport,
    ChatAnswer,
    EvalVerdict,
    GateResult,
    Recommendation,
    ToolResult,
)
from advisor_copilot.render import render
from advisor_copilot.tools import registry
from advisor_copilot.tools.common import K_CLIENT_AGE, K_CLIENT_HORIZON, metric

KYC_MESSAGE = "KYC update required before a suitability-based recommendation"
KYC_REFRESH_MESSAGE = "KYC refresh required: the last review is more than a year old"


@dataclass(frozen=True)
class ThreadContext:
    """What a chat turn knows about its thread: a short summary and the last analysed run."""

    summary: str = ""
    last: RunState | None = None


@dataclass
class LoopResult:
    status: RunStatus = RunStatus.SYNTHESIZING
    drafts: list[Recommendation] = field(default_factory=list)
    answer: ChatAnswer | None = None
    gates: list[GateResult] = field(default_factory=list)
    verdicts: list[EvalVerdict] = field(default_factory=list)
    revisions: int = 0
    issues: list[str] = field(default_factory=list)

    @property
    def draft(self) -> Recommendation | None:
        return self.drafts[-1] if self.drafts else None


async def synthesize_with_review(
    ctx: SynthContext, deps: Deps, res: LoopResult | None = None, answer_mode: bool = False
) -> LoopResult:
    """Draft, G5 gates, evaluator (recommendations only); at most `loop.max_revisions` revisions."""
    cfg, res, feedback = deps.settings.loop, res if res is not None else LoopResult(), None
    while True:
        raw = await synthesize(ctx, deps, feedback, answer_mode)
        if answer_mode:
            res.answer, gate = answer_gates(raw, ctx, deps.settings.chat.answer_max_words)
            draft = None
        else:
            draft, gate = output_gates(raw, ctx)
        res.gates.append(gate)
        if draft:
            res.drafts.append(draft)
        deps.trace.emit(
            "draft_created",
            "synthesizer",
            {
                "revision": res.revisions,
                "mode": "answer" if answer_mode else "recommendation",
                "actions_count": len(raw.get("actions", [])),
            },
        )
        deps.trace.emit("gate_result", "gate", gate.model_dump(), "info" if gate.passed else "warn")
        if gate.passed and answer_mode:
            res.status = RunStatus.COMPLETED
            return res
        if gate.passed and draft:
            verdict = await evaluate(draft, ctx, deps)
            res.verdicts.append(verdict)
            ok = passes(verdict, cfg)
            deps.trace.emit(
                "evaluator_verdict",
                "evaluator",
                {
                    "passed": ok,
                    "checks": verdict.checks,
                    "scores": verdict.scores,
                    "issues_count": len(verdict.issues),
                },
            )
            if ok:
                res.status = RunStatus.AWAITING_APPROVAL
                return res
            source = "evaluator"
            items = [f"{i.criterion}: {i.detail} Fix: {i.suggested_fix}" for i in verdict.issues]
        else:
            source, items = "gates", gate.violations
        res.issues = items
        if res.revisions >= cfg.max_revisions:
            res.status = RunStatus.NEEDS_ADVISOR_REVIEW
            deps.trace.emit("needs_advisor_review", "orchestrator", {"issues": items}, "warn")
            return res
        res.revisions += 1
        deps.trace.emit("revision_requested", "orchestrator", {"source": source, "items": items})
        feedback = Feedback(source, items, raw)


def new_run_id(client_id: str) -> str:
    return f"{client_id}-{dt.datetime.now(dt.UTC):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"


def make_deps(
    run_id: str, settings: Settings, llm: LLMClient | None = None, scenario: str | None = None
) -> Deps:
    """Wire the client for `settings.run_mode`; record/replay use `cassettes/<scenario>.jsonl`."""
    if llm is None:
        if settings.run_mode == "live":
            from advisor_copilot.llm.gemini import GeminiClient

            llm = GeminiClient()
        else:
            path = settings.path("cassettes") / f"{scenario or run_id}.jsonl"
            inner = None
            if settings.run_mode == "record":
                from advisor_copilot.llm.gemini import GeminiClient

                inner = GeminiClient()
            llm = CassetteClient(path, settings.run_mode, inner)
    run_dir = settings.path("runs") / run_id
    limits = settings.rate_limits
    if settings.run_mode == "replay":  # nothing reaches the API, so no pacing
        rpm = {m: {"rpm": 10**6} for m in settings.models.model_dump().values()}
        limits = RateLimitsCfg.model_validate(rpm)
    limiter = RateLimiter(limits, settings.retry, settings.budget.per_call_timeout_seconds)
    store = Store(settings.path("db")) if settings.run_mode == "live" else None
    trace = TraceBus(run_id, run_dir / "trace.jsonl")
    return Deps(settings, llm, limiter, RunBudget(settings.budget), trace, run_dir, store)


def findings_key(spec: AnalystSpec, ctx: AgentContext, s: Settings) -> str:
    """Cache key: same client data, notes, request, prompt and model settings → same findings."""
    payload = {
        "client": ctx.client.model_dump(mode="json"),
        "notes": [n.text for n in ctx.notes],
        "request": ctx.request_text,
        "prompt": load_prompt(spec.prompt, s),
        "spec": spec.__dict__,
        "model": s.models.analyst,
        "temperature": s.temperature.analyst,
        "as_of": str(s.rules.as_of),
    }
    return (
        "findings:"
        + hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    )


async def _analyse(state: RunState, deps: Deps, ctx: AgentContext, mode: str | None) -> None:
    """Run or reuse (cache) the analysts for the routed domains; degrade per domain on errors."""
    s, t, done = deps.settings, deps.trace, state.completed_steps
    store = deps.store if ctx.client else None  # book findings depend on the model's tool args
    specs = analyst_specs(s, mode)
    todo = [d for d in state.route.domains if f"analyst:{d}" not in done]
    results: dict[str, dict[str, ToolResult]] = {d: {} for d in todo}
    cached: dict[str, AnalystReport] = {}
    for d in todo:
        hit = store.cache_get(findings_key(specs[d], ctx, s)) if store else None
        if hit:
            cached[d] = AnalystReport.model_validate_json(hit)
            results[d] = {
                n: registry.run_tool(n, ctx.client_id, default_args(n, ctx)) for n in specs[d].tools
            }
            t.emit("cache_hit", d, {"kind": "findings", "findings_count": len(cached[d].findings)})
    live = [d for d in todo if d not in cached]
    reports = dict(
        zip(
            live,
            await asyncio.gather(
                *(run_agent(specs[d], ctx, deps, results[d]) for d in live), return_exceptions=True
            ),
            strict=True,
        )
    )
    exhausted = None
    for d in todo:
        report = cached.get(d) or reports[d]
        if isinstance(report, BudgetExhausted):
            exhausted, report = report, degraded_report(specs[d], results[d])
        elif isinstance(report, RetryableLLMError | FatalLLMError):
            t.emit(
                "agent_finished",
                d,
                {"findings_count": 0, "status": "degraded", "error": str(report)},
                "warn",
            )
            report = degraded_report(specs[d], results[d])
        elif isinstance(report, BaseException):
            raise report
        elif store and d in live and report.status == "ok":
            store.cache_put(findings_key(specs[d], ctx, s), report.model_dump_json())
        state.analyst_reports[d] = report
        for r in results[d].values():
            state.metrics.update({m.key: m for m in r.metrics})
            state.flags.update({f.flag_id: f for f in r.flags})
        done.append(f"analyst:{d}")
    if exhausted:
        raise exhausted


async def _steps(state: RunState, deps: Deps, runs_dir: Path, thread: ThreadContext) -> None:
    s, t, done = deps.settings, deps.trace, state.completed_steps

    def checkpoint(status: RunStatus, step: str | None = None) -> None:
        state.status = status
        if step:
            done.append(step)
        save_state(state, runs_dir)

    g0 = input_gate(state.client_id, state.request_text, state.preset)
    state.gate_results.append(g0)
    t.emit("gate_result", "gate", g0.model_dump(), "info" if g0.passed else "error")
    if not g0.passed:
        raise ValueError("; ".join(g0.violations))
    book = state.client_id == BOOK
    client, notes = None if book else get_client(state.client_id), get_notes(state.client_id)
    request_text = state.request_text
    sources = [("advisor_request", "request", request_text)]
    sources += [("crm_note", n.note_id, n.text) for n in notes]
    sources += [("headline", h.id, h.text) for h in get_market().headlines]
    for source, sid, text in sources:
        for hit in detect(text):
            payload = {
                "source": source,
                "id": sid,
                "pattern": hit.pattern,
                "excerpt": hit.excerpt,
                "redacted": s.injection.redact,
            }
            t.emit("injection_flagged", "gate", payload, "warn")
            state.untrusted_flags.append(payload)
    if s.injection.redact:
        request_text = redact(request_text)
        notes = [n.model_copy(update={"text": redact(n.text)}) for n in notes]
    checkpoint(RunStatus.INPUT_GATED, "input_gate")
    if client:  # book questions give no advice to one client, so no suitability gate
        g1 = kyc_gate(client, s.rules)
        state.gate_results.append(g1)
        t.emit("gate_result", "gate", g1.model_dump(), "info" if g1.passed else "warn")
        if not g1.passed:
            t.emit(
                "kyc_blocked",
                "gate",
                {"missing_fields": client.kyc_missing(), "reasons": g1.violations},
                "warn",
            )
            state.message = KYC_MESSAGE if client.kyc_missing() else KYC_REFRESH_MESSAGE
            checkpoint(RunStatus.BLOCKED, "kyc_gate")
            return
        done.append("kyc_gate")
    last = thread.last
    if "router" not in done:
        previous = list(last.route.domains) if last and last.route else None
        state.route = await route(request_text, state.preset, deps, thread.summary, previous, book)
        checkpoint(RunStatus.ROUTED, "router")
    assert state.route is not None
    if state.route.route == "out_of_scope":
        state.message = OUT_OF_SCOPE_TEMPLATE
        checkpoint(RunStatus.COMPLETED, "out_of_scope")
        return
    state.mode = "recommendation" if state.route.route == "full_review" else "answer"
    checkpoint(RunStatus.ANALYZING)
    ctx = AgentContext(client, notes, request_text)
    if state.route.route == "follow_up" and last:
        state.analyst_reports = dict(last.analyst_reports)
        state.metrics, state.flags = dict(last.metrics), dict(last.flags)
        t.emit("cache_hit", "orchestrator", {"kind": "follow_up", "from_run": last.run_id})
        done.append("follow_up")
    else:
        prefetch = state.route.route not in ("full_review", "what_if", "book_question")  # tool args
        await _analyse(state, deps, ctx, s.agents.answer_analyst_mode if prefetch else None)
    if client:
        state.metrics[K_CLIENT_AGE] = metric(
            K_CLIENT_AGE, client.age, "years", "Client age", "context"
        )
        state.metrics[K_CLIENT_HORIZON] = metric(
            K_CLIENT_HORIZON, client.time_horizon_years or 0, "years", "Time horizon", "context"
        )
    checkpoint(RunStatus.ANALYZING)
    findings = [f for d in state.route.domains for f in state.analyst_reports[d].findings]
    sctx = SynthContext(
        client,
        notes,
        request_text,
        state.route.route,
        findings,
        state.metrics,
        state.flags,
        thread.summary,
    )
    res = LoopResult()
    checkpoint(RunStatus.SYNTHESIZING)
    try:
        await synthesize_with_review(sctx, deps, res, state.mode == "answer")
    finally:
        state.drafts, state.eval_verdicts, state.revision_count = (
            res.drafts,
            res.verdicts,
            res.revisions,
        )
        state.gate_results += res.gates
        if res.draft:
            state.final = render(res.draft, state.metrics)
        state.answer = res.answer
    if res.status == RunStatus.AWAITING_APPROVAL and state.final:
        t.emit("awaiting_approval", "orchestrator", {"summary": state.final.recommendation.summary})
    elif res.status == RunStatus.NEEDS_ADVISOR_REVIEW:
        state.message = "Checks did not pass: " + "; ".join(res.issues)
    checkpoint(res.status, "synthesis")


async def run_pipeline(
    state: RunState, deps: Deps, runs_dir: Path | None = None, thread: ThreadContext | None = None
) -> RunState:
    """Run or resume the pipeline for `state`; never raises, a terminal status is always saved."""
    runs_dir, t = runs_dir or deps.settings.path("runs"), deps.trace
    t.emit(
        "run_started",
        "orchestrator",
        {
            "client_id": state.client_id,
            "request_text": state.request_text,
            "preset": state.preset,
            "thread_id": state.thread_id,
            "run_mode": deps.settings.run_mode,
            "models": deps.settings.models.model_dump(),
        },
    )
    try:
        await _steps(state, deps, runs_dir, thread or ThreadContext())
    except BudgetExhausted as e:
        t.emit("budget_exhausted", "system", {"which": e.which}, "warn")
        state.status, state.error = RunStatus.DEGRADED, str(e)
    except Exception as e:
        t.emit(
            "run_failed",
            "orchestrator",
            {"error": repr(e), "traceback": traceback.format_exc()[-1500:]},
            "error",
        )
        state.status, state.error = RunStatus.FAILED, repr(e)
    state.budget_snapshot = deps.budget.snapshot()
    if state.status != RunStatus.FAILED:
        t.emit("run_completed", "orchestrator", {"status": state.status, "totals": t.totals()})
    save_state(state, runs_dir)
    t.close()
    if close := getattr(deps.llm, "aclose", None):
        await close()
    return state


async def start_run(
    client_id: str,
    request_text: str,
    preset: str | None,
    settings: Settings | None = None,
    scenario: str | None = None,
    llm: LLMClient | None = None,
    thread_id: str | None = None,
) -> tuple[RunState, Deps]:
    settings = settings or get_settings()
    state = RunState(
        run_id=new_run_id(client_id),
        client_id=client_id,
        request_text=request_text,
        preset=preset,
        thread_id=thread_id,
    )
    return state, make_deps(state.run_id, settings, llm, scenario)
