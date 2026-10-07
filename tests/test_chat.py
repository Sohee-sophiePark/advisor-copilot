"""Chat engine (scripted): follow-up reuse, answer mode, findings cache, daily cap, new gates."""

from pathlib import Path

from helpers import synth_ctx
from scripted_fixtures import script_full_review
from test_gates import ACTION, FINDINGS, GOOD

from advisor_copilot.db import Store
from advisor_copilot.harness.chat import reply_text
from advisor_copilot.harness.deps import Deps
from advisor_copilot.harness.gates import answer_gates, output_gates
from advisor_copilot.harness.orchestrator import ThreadContext, run_pipeline
from advisor_copilot.harness.state import RunState, RunStatus
from advisor_copilot.llm.base import LLMResponse, ToolCall
from advisor_copilot.models import Finding

ANSWER = {
    "answer": "Margaret holds {{m:conc.SU.pct}} in one stock.",
    "suggested_questions": ["Why stages?"],
}


def state(cid: str, text: str = "", preset: str | None = "annual_review") -> RunState:
    return RunState(run_id=f"t-{cid}-{len(text)}", client_id=cid, request_text=text, preset=preset)


def route(r: str, domains: list[str]) -> LLMResponse:
    return LLMResponse(parsed={"route": r, "domains": domains, "reason": "x", "confidence": 0.9})


async def test_follow_up_reuses_findings_without_analysts(deps: Deps, tmp_path: Path) -> None:
    script_full_review(deps.llm, "C002")
    first = await run_pipeline(state("C002"), deps, tmp_path)
    assert first.mode == "recommendation"
    deps.budget.calls, deps.llm.requests = 0, []
    deps.llm.add("router", route("follow_up", []))
    deps.llm.add("synthesizer", LLMResponse(parsed=ANSWER))
    turn = await run_pipeline(
        state("C002", "Why sell in stages?", None), deps, tmp_path, ThreadContext("Q1", first)
    )
    assert turn.status == RunStatus.COMPLETED and turn.mode == "answer" and deps.budget.calls == 2
    assert reply_text(turn) == "Margaret holds 28.6% in one stock."
    assert {r.purpose for r in deps.llm.requests} == {"router", "synthesizer"}
    assert "previous domains: portfolio, risk, tax, market" in deps.llm.requests[0].messages[0].text


async def test_follow_up_without_previous_widens(deps: Deps, tmp_path: Path) -> None:
    script_full_review(deps.llm, "C003")
    deps.llm.add("router", route("follow_up", []))
    s = await run_pipeline(state("C003", "And why?", None), deps, tmp_path)
    assert s.route.route == "full_review" and s.mode == "recommendation"


async def test_targeted_answer_mode_uses_prefetch(deps: Deps, tmp_path: Path) -> None:
    deps.llm.add("router", route("targeted", ["tax"]))
    submit = {
        "findings": [
            {
                "finding_id": "x",
                "title": "Unused TFSA room",
                "severity": "info",
                "detail": "Room is {{m:tax.tfsa_room.cad}}.",
                "metric_refs": ["tax.tfsa_room.cad"],
                "flag_refs": ["FLAG-L1-VTI", "FLAG-L2", "FLAG-L3"],
            }
        ]
    }
    deps.llm.add(
        "analyst:tax",
        LLMResponse(tool_calls=[ToolCall(id="s", name="submit_findings", args=submit)]),
    )
    deps.llm.add(
        "synthesizer",
        LLMResponse(
            parsed={
                "answer": "Daniel has {{m:tax.tfsa_room.cad}} of room.",
                "suggested_questions": [],
            }
        ),
    )
    s = await run_pipeline(state("C001", "TFSA room?", None), deps, tmp_path)
    assert s.status == RunStatus.COMPLETED and reply_text(s) == "Daniel has $14,000 of room."
    assert deps.budget.calls == 3 and s.final is None


async def test_findings_cache_skips_analysts_on_unchanged_data(deps: Deps, tmp_path: Path) -> None:
    deps.store = Store(tmp_path / "t.db")
    script_full_review(deps.llm, "C001")
    await run_pipeline(state("C001"), deps, tmp_path)
    deps.llm.requests = []
    again = await run_pipeline(state("C001"), deps, tmp_path)
    assert sum(e.type == "cache_hit" for e in deps.trace.events) == 4
    assert len(again.analyst_reports) == 4
    assert not any(r.purpose.startswith("analyst") for r in deps.llm.requests)


async def test_daily_cap_stops_live_calls(deps: Deps, tmp_path: Path) -> None:
    deps.store = Store(tmp_path / "t.db")
    deps.settings = deps.settings.model_copy(
        update={"budget": deps.settings.budget.model_copy(update={"daily_call_cap": 1})}
    )
    deps.store.add_usage(deps.settings.models.router, 1, 1)
    s = await run_pipeline(state("C003", "Which crypto?", None), deps, tmp_path)
    assert s.status == RunStatus.DEGRADED and "daily_call_cap" in s.error


def test_store_threads_and_totals(tmp_path: Path) -> None:
    st = Store(tmp_path / "t.db")
    st.create_thread("th1", "C001")
    st.add_message("th1", "advisor", "Prepare review")
    st.add_message("th1", "copilot", "Done", run_id="r1", route="full_review", calls=10, tokens=500)
    assert st.thread_client("th1") == "C001" and [m["seq"] for m in st.messages("th1")] == [1, 2]
    assert st.thread_totals("th1") == (10, 500)


def test_g5_11_action_must_match_finding_type() -> None:
    ctx = synth_ctx("C002", FINDINGS)
    bad = {**GOOD, "actions": [{**ACTION, "type": "review_kyc", "direction": "none"}]}
    assert any(v.startswith("G5.11") for v in output_gates(bad, ctx)[1].violations)


def test_g5_12_advisor_voice() -> None:
    ctx = synth_ctx("C002", FINDINGS)
    assert any(
        v.startswith("G5.12")
        for v in output_gates({**GOOD, "summary": "Your stock is large."}, ctx)[1].violations
    )
    talking = {**GOOD, "client_talking_points": ["You can sell in stages."]}
    assert output_gates(talking, ctx)[1].passed


def test_answer_gates() -> None:
    ctx = synth_ctx("C002", [Finding.model_validate(f.model_dump()) for f in FINDINGS])
    assert answer_gates(ANSWER, ctx, 120)[1].passed
    v = answer_gates({"answer": "It returns 12% a year.", "suggested_questions": []}, ctx, 120)[
        1
    ].violations
    assert v == ["G5.2 no_raw_numbers: digits outside {{m:...}} placeholders"]
