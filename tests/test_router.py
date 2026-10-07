"""Fast path needs no LLM; post-rules widen, never narrow; the LLM path is parsed and traced."""

from advisor_copilot.agents.router import post_rules, route
from advisor_copilot.harness.deps import Deps
from advisor_copilot.llm.base import LLMResponse
from advisor_copilot.models import RouteDecision


def rd(r: str, d: list[str], c: float) -> RouteDecision:
    return RouteDecision(route=r, domains=d, reason="r", confidence=c)


def test_post_rules() -> None:
    assert post_rules(rd("targeted", [], 0.9), 0.55)[0].route == "full_review"
    assert post_rules(rd("targeted", ["tax"], 0.4), 0.55)[1] == ["low_confidence"]
    assert post_rules(rd("out_of_scope", [], 0.3), 0.55)[0].route == "full_review"
    assert post_rules(rd("targeted", ["market", "tax", "tax"], 0.9), 0.55)[0].domains == [
        "tax",
        "market",
    ]
    assert post_rules(rd("out_of_scope", ["tax"], 0.9), 0.55)[0].domains == []


async def test_fast_path_skips_llm(deps: Deps) -> None:
    d = await route("", "annual_review", deps)
    assert d.route == "full_review" and d.confidence == 1.0
    ev = deps.trace.events[-1]
    assert ev.type == "route_decided" and ev.payload["fast_path"] is True and deps.budget.calls == 0


async def test_llm_path_applies_post_rules(deps: Deps) -> None:
    deps.llm.add(
        "router",
        LLMResponse(
            parsed={"route": "targeted", "domains": ["tax"], "reason": "x", "confidence": 0.9}
        ),
    )
    deps.llm.add(
        "router",
        LLMResponse(
            parsed={"route": "targeted", "domains": ["tax"], "reason": "x", "confidence": 0.3}
        ),
    )
    deps.llm.add("router", LLMResponse(parsed={"route": "nonsense"}))
    assert (await route("TFSA?", None, deps)).domains == ["tax"]
    d = await route("TFSA??", None, deps)
    assert d.route == "full_review" and deps.trace.events[-1].payload["rules_applied"] == [
        "low_confidence"
    ]
    assert (await route("??", None, deps)).reason == "unparseable router output"
