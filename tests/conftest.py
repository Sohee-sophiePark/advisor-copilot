"""Shared fixtures: the golden expected values from docs/05 §6."""

import json
from pathlib import Path
from typing import Any

import pytest

from advisor_copilot.config import RateLimitsCfg, load_settings
from advisor_copilot.harness.budget import RunBudget
from advisor_copilot.harness.deps import Deps
from advisor_copilot.harness.trace import TraceBus
from advisor_copilot.llm.limiter import RateLimiter
from advisor_copilot.llm.scripted import ScriptedClient

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def expected() -> dict[str, Any]:
    return json.loads((FIXTURES / "expected_values.json").read_text(encoding="utf-8"))


@pytest.fixture
def deps() -> Deps:
    """Scripted client, real prompts, unlimited rpm so tests never sleep."""
    s = load_settings(env={})
    limits = RateLimitsCfg.model_validate(
        {m: {"rpm": 10**6} for m in [*s.models.model_dump().values(), *s.fallback_models]}
    )
    limiter = RateLimiter(limits, s.retry, 5.0, jitter=lambda: 0.0)
    return Deps(s, ScriptedClient(), limiter, RunBudget(s.budget), TraceBus("t"))
