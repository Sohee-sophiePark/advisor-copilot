"""Scripted runs: happy path, S3 injection, S4 KYC, S6 scope, G10/G11 loop, G12 budget, resume."""

from pathlib import Path

from helpers import synth_ctx
from scripted_fixtures import FAIL, PASS, script_full_review
from test_gates import FINDINGS, GOOD

from advisor_copilot.harness.deps import Deps
from advisor_copilot.harness.orchestrator import run_pipeline, synthesize_with_review
from advisor_copilot.harness.state import RunState, RunStatus, load_state
from advisor_copilot.llm.base import FatalLLMError, LLMResponse
from advisor_copilot.models import DOMAINS

CTX = synth_ctx("C002", FINDINGS)


def state_for(client_id: str, preset: str | None = "annual_review", request: str = "") -> RunState:
    return RunState(
        run_id=f"t-{client_id}", client_id=client_id, request_text=request, preset=preset
    )


async def test_happy_path_c001_with_checkpoints(deps: Deps, tmp_path: Path) -> None:
    must = script_full_review(deps.llm, "C001")
    state = await run_pipeline(state_for("C001"), deps, tmp_path)
    assert state.status == RunStatus.AWAITING_APPROVAL and deps.budget.calls == 10
    assert state.route.route == "full_review" and set(state.analyst_reports) == set(DOMAINS)
    assert sorted(must) == sorted(
        f.finding_id
        for r in state.analyst_reports.values()
        for f in r.findings
        if f.severity != "info"
    )
    assert state.final.recommendation.summary == "Total value is $219,000 for Daniel Okafor."
    assert "client.age.years" in state.metrics and state.revision_count == 0
    assert load_state("t-C001", tmp_path).completed_steps[-1] == "synthesis"
    assert [e.type for e in deps.trace.events][-2:] == ["awaiting_approval", "run_completed"]


async def test_s3_injection_flagged_and_redacted(deps: Deps, tmp_path: Path) -> None:
    script_full_review(deps.llm, "C003")
    state = await run_pipeline(state_for("C003"), deps, tmp_path)
    flagged = [e for e in deps.trace.events if e.type == "injection_flagged"]
    assert {e.payload["id"] for e in flagged} == {"N-302"} and state.untrusted_flags
    briefs = [m.text for r in deps.llm.requests for m in r.messages if m.role == "user"]
    assert all("admin mode" not in b and "NRTH" not in b for b in briefs)
    assert state.status == RunStatus.AWAITING_APPROVAL and state.final.recommendation.actions == []


async def test_s4_kyc_blocked_before_any_llm_call(deps: Deps, tmp_path: Path) -> None:
    state = await run_pipeline(state_for("C004"), deps, tmp_path)
    assert state.status == RunStatus.BLOCKED and deps.budget.calls == 0
    assert state.message.startswith("KYC update required")
    assert any(e.type == "kyc_blocked" and e.payload["missing_fields"] for e in deps.trace.events)


async def test_s6_out_of_scope_has_zero_analyst_calls(deps: Deps, tmp_path: Path) -> None:
    deps.llm.add(
        "router",
        LLMResponse(
            parsed={"route": "out_of_scope", "domains": [], "reason": "crypto", "confidence": 0.97}
        ),
    )
    state = await run_pipeline(
        state_for("C003", None, "Which crypto will 10x this year?"), deps, tmp_path
    )
    assert (
        state.status == RunStatus.COMPLETED
        and deps.budget.calls == 1
        and "I can help with" in state.message
    )


async def test_g0_unknown_client_fails(deps: Deps, tmp_path: Path) -> None:
    state = await run_pipeline(state_for("C999"), deps, tmp_path)
    assert state.status == RunStatus.FAILED and "unknown client" in state.error


async def test_g10_gate_fail_then_evaluator_fail_then_pass(deps: Deps) -> None:
    deps.llm.add(
        "synthesizer",
        LLMResponse(parsed={**GOOD, "summary": "12% returns"}),
        LLMResponse(parsed=GOOD),
        LLMResponse(parsed=GOOD),
    )
    deps.llm.add("evaluator", LLMResponse(parsed=FAIL), LLMResponse(parsed=PASS))
    res = await synthesize_with_review(CTX, deps)
    assert (
        res.status == RunStatus.AWAITING_APPROVAL and res.revisions == 2 and deps.budget.calls == 5
    )
    assert [g.passed for g in res.gates] == [False, True, True] and len(res.verdicts) == 2
    assert "G5.2" in deps.llm.requests[1].messages[0].text


async def test_g11_evaluator_never_passes(deps: Deps) -> None:
    deps.llm.add("synthesizer", *[LLMResponse(parsed=GOOD)] * 3)
    deps.llm.add("evaluator", *[LLMResponse(parsed=FAIL)] * 3)
    res = await synthesize_with_review(CTX, deps)
    assert (
        res.status == RunStatus.NEEDS_ADVISOR_REVIEW
        and res.revisions == 2
        and deps.budget.calls == 6
    )
    assert res.issues == ["critical_addressed: x Fix: y"] and res.draft is not None
    assert deps.trace.events[-1].type == "needs_advisor_review"


async def test_g12_budget_exhaustion_degrades_with_partial_output(
    deps: Deps, tmp_path: Path
) -> None:
    deps.budget.cfg = deps.budget.cfg.model_copy(update={"max_llm_calls": 3})
    script_full_review(deps.llm, "C002")
    state = await run_pipeline(state_for("C002"), deps, tmp_path)
    assert state.status == RunStatus.DEGRADED and deps.budget.calls == 3
    assert any(e.type == "budget_exhausted" for e in deps.trace.events)
    assert len(state.analyst_reports) == 4 and any(
        r.findings for r in state.analyst_reports.values()
    )
    assert "FLAG-CONC-NRTH" in state.flags or "FLAG-SUIT-VOL" in state.flags


async def test_resume_skips_completed_analysts(deps: Deps, tmp_path: Path) -> None:
    script_full_review(deps.llm, "C001")
    done = await run_pipeline(state_for("C001"), deps, tmp_path)
    deps.budget.calls, deps.llm.requests = 0, []
    interrupted = done.model_copy(
        update={
            "status": RunStatus.ANALYZING,
            "final": None,
            "drafts": [],
            "completed_steps": [s for s in done.completed_steps if s != "synthesis"],
        }
    )
    script_full_review(deps.llm, "C001")
    resumed = await run_pipeline(interrupted, deps, tmp_path)
    assert resumed.status == RunStatus.AWAITING_APPROVAL and deps.budget.calls == 2
    assert {r.purpose for r in deps.llm.requests} == {"synthesizer", "evaluator"}


async def test_failed_analyst_degrades_only_that_domain(deps: Deps, tmp_path: Path) -> None:
    script_full_review(deps.llm, "C001")
    deps.llm.queues["analyst:tax"].clear()
    deps.llm.add("analyst:tax", FatalLLMError("503 overloaded"))
    draft = deps.llm.queues["synthesizer"].pop().parsed
    draft["actions"] = [
        a for a in draft["actions"] if not any(r.startswith("TAX") for r in a["finding_refs"])
    ]
    deps.llm.add("synthesizer", LLMResponse(parsed=draft))
    state = await run_pipeline(state_for("C001"), deps, tmp_path)
    assert (
        state.analyst_reports["tax"].status == "degraded"
        and state.analyst_reports["risk"].status == "ok"
    )
    assert state.status in (RunStatus.AWAITING_APPROVAL, RunStatus.NEEDS_ADVISOR_REVIEW)
