"""What-if simulator: deterministic before/after, breach bookkeeping, argument checks, routing."""

import pytest
from helpers import metrics

from advisor_copilot.agents.router import post_rules
from advisor_copilot.harness.deps import Deps
from advisor_copilot.harness.orchestrator import run_pipeline
from advisor_copilot.harness.state import RunState, RunStatus
from advisor_copilot.llm.base import LLMResponse, ToolCall
from advisor_copilot.models import RouteDecision
from advisor_copilot.tools import registry as reg
from advisor_copilot.tools.scenario import TradeArgs, simulate_trade


def sim(**args: object):  # noqa: ANN201
    return simulate_trade(
        "C002", TradeArgs.model_validate({"sell_ticker": "NRTH", "buy_ticker": "CBND", **args})
    )


def test_half_of_nrth_into_bonds() -> None:
    r = sim(sell_fraction=0.5)
    m = metrics(r)
    assert m["conc.NRTH.pct"] == pytest.approx(28.57) and m[
        "whatif.conc.NRTH.pct"
    ] == pytest.approx(14.29)
    assert m["whatif.trade.cad"] == 37800 and m["whatif.risk.vol.pct"] < m["risk.vol.pct"]
    assert "FLAG-CONC-NRTH" in r.data["remaining"] and r.flags == []


def test_selling_enough_resolves_the_concentration() -> None:
    r = sim(sell_fraction=0.7)
    assert (
        metrics(r)["whatif.conc.NRTH.pct"] == pytest.approx(8.57)
        and "FLAG-CONC-NRTH" in r.data["resolved"]
    )


def test_amount_is_capped_at_the_holding() -> None:
    assert metrics(sim(sell_amount_cad=1e9))["whatif.trade.cad"] == 75600


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"sell_fraction": 0.5, "sell_amount_cad": 10},
        {"sell_fraction": 0.5, "buy_ticker": "BTC"},
        {"sell_fraction": 0.5, "buy_ticker": "NRTH"},
    ],
)
def test_bad_args_are_rejected(args: dict) -> None:
    with pytest.raises(reg.ToolArgsError):
        reg.run_tool(
            "simulate_trade", "C002", {"sell_ticker": "NRTH", "buy_ticker": "CBND", **args}
        )


def test_selling_something_not_held_is_an_error() -> None:
    with pytest.raises(reg.ToolArgsError, match="not held"):
        reg.run_tool("simulate_trade", "C001", {"sell_ticker": "NRTH", "sell_fraction": 0.5})


def test_router_assigns_the_scenario_analyst() -> None:
    d, _ = post_rules(
        RouteDecision(route="what_if", domains=["tax"], reason="x", confidence=0.9), 0.55
    )
    assert d.domains == ["scenario"]


async def test_what_if_turn_end_to_end(deps: Deps, tmp_path) -> None:  # noqa: ANN001
    deps.llm.add(
        "router",
        LLMResponse(parsed={"route": "what_if", "domains": [], "reason": "x", "confidence": 0.9}),
    )
    call = ToolCall(
        id="1",
        name="simulate_trade",
        args={"sell_ticker": "NRTH", "sell_fraction": 0.5, "buy_ticker": "CBND"},
    )
    finding = {
        "finding_id": "x",
        "title": "Concentration halves but stays above limit",
        "severity": "info",
        "detail": "NRTH falls from {{m:conc.NRTH.pct}} to {{m:whatif.conc.NRTH.pct}}.",
        "metric_refs": ["conc.NRTH.pct", "whatif.conc.NRTH.pct"],
        "flag_refs": [],
    }
    deps.llm.add(
        "analyst:scenario",
        LLMResponse(tool_calls=[call]),
        LLMResponse(
            tool_calls=[ToolCall(id="2", name="submit_findings", args={"findings": [finding]})]
        ),
    )
    deps.llm.add(
        "synthesizer",
        LLMResponse(
            parsed={
                "answer": "NRTH would drop to {{m:whatif.conc.NRTH.pct}}.",
                "suggested_questions": [],
            }
        ),
    )
    s = await run_pipeline(
        RunState(run_id="w", client_id="C002", request_text="Sell half NRTH?"), deps, tmp_path
    )
    assert (
        s.status == RunStatus.COMPLETED
        and s.route.route == "what_if"
        and list(s.analyst_reports) == ["scenario"]
    )
    assert (
        s.analyst_reports["scenario"].findings[0].finding_id == "WHATIF-1"
        and deps.budget.calls == 4
    )
