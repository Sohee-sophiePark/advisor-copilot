"""AnalystSpecs per domain (review, what-if, book): prompt file, tool allowlist, mode, turn cap."""

from dataclasses import dataclass
from typing import Literal

from advisor_copilot.config import Settings
from advisor_copilot.models import DOMAINS, Domain
from advisor_copilot.tools.registry import tools_for


@dataclass(frozen=True)
class AnalystSpec:
    name: Domain
    prompt: str
    tools: tuple[str, ...]
    mode: Literal["tool_loop", "prefetch"]
    max_turns: int
    max_findings: int


def analyst_specs(settings: Settings, mode: str | None = None) -> dict[Domain, AnalystSpec]:
    """Specs per domain; `mode` overrides `agents.analyst_mode` (chat answers use prefetch)."""
    a = settings.agents
    return {
        d: AnalystSpec(
            d,
            f"{d}_analyst.md",
            tuple(t.name for t in tools_for(d)),
            mode or a.analyst_mode,
            a.max_turns,
            a.max_market_findings if d == "market" else a.max_findings,
        )
        for d in (*DOMAINS, "scenario", "book")
    }
