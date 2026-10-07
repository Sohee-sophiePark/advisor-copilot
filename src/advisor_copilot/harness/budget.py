"""Per-run budget for LLM calls, tokens, and wall-clock time."""

import time
from collections.abc import Callable

from advisor_copilot.config import BudgetCfg


class BudgetExhausted(Exception):
    def __init__(self, which: str) -> None:
        super().__init__(f"budget exhausted: {which}")
        self.which = which


class RunBudget:
    def __init__(self, cfg: BudgetCfg, clock: Callable[[], float] = time.monotonic) -> None:
        self.cfg, self.clock, self.t0 = cfg, clock, clock()
        self.calls = self.tokens = self.pending = 0

    def check(self) -> None:
        """Reserve a slot for the next call, or raise BudgetExhausted; `charge` or `release` it."""
        if self.calls + self.pending >= self.cfg.max_llm_calls:
            raise BudgetExhausted("max_llm_calls")
        if self.tokens >= self.cfg.max_total_tokens:
            raise BudgetExhausted("max_total_tokens")
        if self.clock() - self.t0 >= self.cfg.max_wall_seconds:
            raise BudgetExhausted("max_wall_seconds")
        self.pending += 1

    def release(self) -> None:
        self.pending -= 1

    def charge(self, tokens_in: int, tokens_out: int) -> None:
        self.pending -= 1
        self.calls += 1
        self.tokens += tokens_in + tokens_out

    def snapshot(self) -> dict[str, int]:
        return {
            "llm_calls": self.calls,
            "tokens": self.tokens,
            "wall_ms": int((self.clock() - self.t0) * 1000),
        }
