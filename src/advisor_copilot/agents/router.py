"""Router: preset fast path, LLM classifier, deterministic post-rules (03 §5)."""

from pydantic import ValidationError

from advisor_copilot.harness.context import load_prompt
from advisor_copilot.harness.deps import Deps
from advisor_copilot.harness.injection import wrap
from advisor_copilot.llm.base import LLMRequest, Message
from advisor_copilot.models import DOMAINS, RouteDecision

OUT_OF_SCOPE_TEMPLATE = (
    "I can help with portfolio reviews, allocation and drift, risk and concentration, account "
    "placement across TFSA/RRSP/RRIF and non-registered accounts, and market context for your "
    "clients. I can't predict prices of individual assets or recommend speculative investments."
)


def post_rules(d: RouteDecision, threshold: float) -> tuple[RouteDecision, list[str]]:
    rules: list[str] = []
    route, domains = d.route, [x for x in DOMAINS if x in d.domains]
    if route == "targeted" and not domains:
        route, rules = "full_review", ["targeted_without_domains"]
    if d.confidence < threshold and route != "full_review":
        route, rules = "full_review", rules + ["low_confidence"]
    domains = (
        list(DOMAINS) if route == "full_review" else [] if route == "out_of_scope" else domains
    )
    return RouteDecision(
        route=route, domains=domains, reason=d.reason, confidence=d.confidence
    ), rules


async def route(request_text: str, preset: str | None, deps: Deps) -> RouteDecision:
    s = deps.settings
    if preset in s.router.fast_path_presets:
        d = RouteDecision(
            route="full_review", domains=list(DOMAINS), reason="preset", confidence=1.0
        )
        deps.trace.emit(
            "route_decided", "router", {**d.model_dump(), "rules_applied": [], "fast_path": True}
        )
        return d
    req = LLMRequest(
        model=s.models.router,
        system=load_prompt("router.md", s),
        messages=[Message(role="user", text=wrap(request_text, "advisor_request", "request"))],
        temperature=s.temperature.router,
        thinking_level=s.thinking_level.router,
        response_schema=RouteDecision,
        purpose="router",
    )
    resp = await deps.llm_call(req)
    try:
        raw = RouteDecision.model_validate(resp.parsed or {})
    except ValidationError:
        raw = RouteDecision(
            route="full_review", domains=[], reason="unparseable router output", confidence=0.0
        )
    d, rules = post_rules(raw, s.router.low_confidence_threshold)
    deps.trace.emit(
        "route_decided", "router", {**d.model_dump(), "rules_applied": rules, "fast_path": False}
    )
    return d
