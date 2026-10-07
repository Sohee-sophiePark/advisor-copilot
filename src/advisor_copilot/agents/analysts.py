"""The four AnalystSpecs: name, prompt file, tool allowlist, loop mode, and turn cap."""

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


def analyst_specs(settings: Settings) -> dict[Domain, AnalystSpec]:
    return {
        d: AnalystSpec(
            d,
            f"{d}_analyst.md",
            tuple(t.name for t in tools_for(d)),
            settings.agents.analyst_mode,
            settings.agents.max_turns,
        )
        for d in DOMAINS
    }
