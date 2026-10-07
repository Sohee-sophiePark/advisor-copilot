"""The five termination conditions of the analyst loop, plus G3 tool rules and trace events."""

import pytest

from advisor_copilot.agents.analysts import AnalystSpec
from advisor_copilot.data_access import get_client
from advisor_copilot.harness.agent_loop import run_agent
from advisor_copilot.harness.budget import BudgetExhausted
from advisor_copilot.harness.context import AgentContext
from advisor_copilot.harness.deps import Deps
from advisor_copilot.llm.base import FatalLLMError, LLMResponse, ToolCall

P = "analyst:risk"
CTX = AgentContext(get_client("C002"), [], "Prepare annual review")
GOOD = {
    "findings": [
        {
            "finding_id": "x",
            "title": "Volatility above band",
            "severity": "info",
            "detail": "Volatility is {{m:risk.vol.pct}} vs a band of {{m:risk.vol_band_max.pct}}.",
            "metric_refs": ["risk.vol.pct", "risk.vol_band_max.pct"],
            "flag_refs": ["FLAG-SUIT-VOL"],
        },
        {
            "finding_id": "y",
            "title": "Single stock concentration",
            "severity": "info",
            "detail": "One holding is {{m:conc.NRTH.pct}} of the portfolio.",
            "metric_refs": ["conc.NRTH.pct"],
            "flag_refs": ["FLAG-CONC-NRTH"],
        },
    ],
    "data_gaps": [],
}


def call(name: str, args: dict | None = None, cid: str = "1") -> LLMResponse:
    return LLMResponse(
        tool_calls=[ToolCall(id=cid, name=name, args=args or {})], tokens_in=5, tokens_out=3
    )


def spec(max_turns: int = 3) -> AnalystSpec:
    tools = ("compute_risk_metrics", "run_stress_test", "check_concentration")
    return AnalystSpec("risk", "risk_analyst.md", tools, "tool_loop", max_turns)


async def test_1_valid_submit_returns_code_corrected_report(deps: Deps) -> None:
    deps.llm.add(
        P,
        LLMResponse(
            tool_calls=[
                call("compute_risk_metrics").tool_calls[0],
                ToolCall(id="2", name="check_concentration", args={}),
            ],
            tokens_in=5,
            tokens_out=3,
        ),
    )
    deps.llm.add(P, call("submit_findings", GOOD))
    report = await run_agent(spec(), CTX, deps)
    assert report.status == "ok" and [f.finding_id for f in report.findings] == ["RISK-1", "RISK-2"]
    assert {f.severity for f in report.findings} == {"critical"}
    types = [e.type for e in deps.trace.events]
    assert types.count("llm_call_started") == types.count("llm_call_finished") == 2
    assert types.count("tool_call") == 2 and types[-1] == "agent_finished"
    assert all(
        e.payload["tokens_in"] == 5 for e in deps.trace.events if e.type == "llm_call_finished"
    )


async def test_2_invalid_submit_args_get_a_repair_turn(deps: Deps) -> None:
    deps.llm.add(P, call("submit_findings", {"findings": "nope"}))
    deps.llm.add(P, call("submit_findings", {"findings": [], "data_gaps": ["no tools called"]}))
    report = await run_agent(spec(), CTX, deps)
    assert report.status == "ok" and report.findings == []
    assert "findings" in deps.llm.requests[1].messages[-1].tool_result["error"]


async def test_3_last_turn_only_allows_submit(deps: Deps) -> None:
    deps.llm.add(P, call("compute_risk_metrics"))
    deps.llm.add(P, call("submit_findings", {"findings": [GOOD["findings"][0]]}))
    report = await run_agent(spec(max_turns=2), CTX, deps)
    last = deps.llm.requests[1]
    assert last.allowed_tools == ["submit_findings"] and [t.name for t in last.tools] == [
        "submit_findings"
    ]
    assert report.status == "ok"


async def test_4_loop_exhausted_degrades_with_code_findings(deps: Deps) -> None:
    for _ in range(3):
        deps.llm.add(P, call("compute_risk_metrics"))
    report = await run_agent(spec(), CTX, deps)
    assert report.status == "degraded" and [f.flag_refs for f in report.findings] == [
        ["FLAG-SUIT-VOL"]
    ]
    assert report.findings[0].severity == "critical" and deps.trace.events[-1].level == "warn"


async def test_5_budget_and_fatal_errors_propagate(deps: Deps) -> None:
    deps.budget.cfg = deps.budget.cfg.model_copy(update={"max_llm_calls": 1})
    deps.llm.add(P, call("compute_risk_metrics"), call("submit_findings", GOOD))
    with pytest.raises(BudgetExhausted):
        await run_agent(spec(), CTX, deps)
    deps.budget.cfg = deps.budget.cfg.model_copy(update={"max_llm_calls": 20})
    deps.llm.add(P, FatalLLMError("400 bad request"))
    with pytest.raises(FatalLLMError):
        await run_agent(spec(), CTX, deps)


async def test_g4_repair_then_code_correction(deps: Deps) -> None:
    bad = {
        "findings": [
            {
                "finding_id": "a",
                "title": "Vol is 11.9%",
                "severity": "info",
                "detail": "raw digits",
                "metric_refs": ["risk.vol.pct"],
                "flag_refs": ["FLAG-SUIT-VOL"],
            }
        ]
    }
    deps.llm.add(
        P, call("compute_risk_metrics"), call("submit_findings", bad), call("submit_findings", bad)
    )
    report = await run_agent(spec(), CTX, deps)
    assert "digits" in deps.llm.requests[2].messages[-1].tool_result["error"][0]
    assert report.status == "degraded" and report.findings[0].flag_refs == ["FLAG-SUIT-VOL"]


async def test_g3_unknown_tool_and_call_cap(deps: Deps) -> None:
    deps.settings.agents.max_tool_calls = 1
    deps.llm.add(
        P,
        LLMResponse(
            tool_calls=[
                ToolCall(id="1", name="sell_everything", args={}),
                ToolCall(id="2", name="run_stress_test", args={"scenario": "zombie"}),
            ]
        ),
    )
    deps.llm.add(P, call("submit_findings", {"findings": []}))
    await run_agent(spec(), CTX, deps)
    errors = [m.tool_result["error"] for m in deps.llm.requests[1].messages if m.role == "tool"]
    assert errors == [
        "tool not permitted for this agent",
        "tool call limit reached; call submit_findings now",
    ]
