"""Router: preset fast path, LLM classifier, deterministic post-rules (03 §5)."""

from pydantic import ValidationError

from advisor_copilot.harness.context import load_prompt, thread_block
from advisor_copilot.harness.deps import Deps
from advisor_copilot.harness.injection import wrap
from advisor_copilot.llm.base import LLMRequest, Message
from advisor_copilot.models import DOMAINS, RouteDecision

OUT_OF_SCOPE_TEMPLATE = (
    "I can help with portfolio reviews, allocation and drift, risk and concentration, account "
    "placement across TFSA/RRSP/RRIF and non-registered accounts, and market context for your "
    "clients. I can't predict prices of individual assets or recommend speculative investments."
)


def post_rules(
    d: RouteDecision, threshold: float, previous: list[str] | None = None, book: bool = False
) -> tuple[RouteDecision, list[str]]:
    """Widen, never narrow: follow_up needs a previous analysis; low confidence → the widest
    route of the scope (full_review for a client, book_question for the book)."""
    rules: list[str] = []
    wide = "book_question" if book else "full_review"
    route, domains = d.route, [x for x in DOMAINS if x in d.domains]
    if (route == "book_question") != book and route not in ("follow_up", "out_of_scope"):
        route, rules = wide, ["route_outside_scope"]
    if route == "follow_up" and previous is None:
        route, rules = wide, ["follow_up_without_findings"]
    if route == "follow_up":
        domains = list(previous or [])
    if route == "what_if":
        domains = ["scenario"]
    if route == "targeted" and not domains:
        route, rules = "full_review", ["targeted_without_domains"]
    if d.confidence < threshold and route != wide:
        route, rules = wide, rules + ["low_confidence"]
    domains = {"full_review": list(DOMAINS), "book_question": ["book"], "out_of_scope": []}.get(
        route, domains
    )
    return RouteDecision(
        route=route, domains=domains, reason=d.reason, confidence=d.confidence
    ), rules


def router_input(request_text: str, thread_summary: str, previous: list[str] | None) -> str:
    text = wrap(request_text, "advisor_request", "request")
    if previous is None and not thread_summary:
        return text
    head = f"previous domains: {', '.join(previous) if previous else 'none'}"
    return f"{text}\n<thread_context>{head}</thread_context>\n{thread_block(thread_summary)}"


async def route(
    request_text: str,
    preset: str | None,
    deps: Deps,
    thread_summary: str = "",
    previous: list[str] | None = None,
    book: bool = False,
) -> RouteDecision:
    """`previous` = domains of the thread's last analysis (None if there is none)."""
    s = deps.settings
    if preset in s.router.fast_path_presets and not book:
        d = RouteDecision(
            route="full_review", domains=list(DOMAINS), reason="preset", confidence=1.0
        )
        deps.trace.emit(
            "route_decided", "router", {**d.model_dump(), "rules_applied": [], "fast_path": True}
        )
        return d
    req = LLMRequest(
        model=s.models.router,
        system=load_prompt("book_router.md" if book else "router.md", s),
        messages=[Message(role="user", text=router_input(request_text, thread_summary, previous))],
        temperature=s.temperature.router,
        thinking_level=s.thinking_level.router,
        max_output_tokens=s.max_output_tokens.router,
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
    d, rules = post_rules(raw, s.router.low_confidence_threshold, previous, book)
    deps.trace.emit(
        "route_decided", "router", {**d.model_dump(), "rules_applied": rules, "fast_path": False}
    )
    return d
