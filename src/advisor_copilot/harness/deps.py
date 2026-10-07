"""Per-run dependency container; `llm_call` = budget check → limiter → client → trace → charge."""

import json
from dataclasses import dataclass
from pathlib import Path

from advisor_copilot.config import Settings
from advisor_copilot.harness.budget import RunBudget
from advisor_copilot.harness.trace import TraceBus
from advisor_copilot.llm.base import LLMClient, LLMRequest, LLMResponse
from advisor_copilot.llm.limiter import RateLimiter


@dataclass
class Deps:
    settings: Settings
    llm: LLMClient
    limiter: RateLimiter
    budget: RunBudget
    trace: TraceBus
    run_dir: Path | None = None

    def __post_init__(self) -> None:
        self.limiter.on_retry = lambda status, wait, attempt: self.trace.emit(
            "llm_retry",
            "system",
            {"status": status, "wait_ms": int(wait * 1000), "attempt": attempt},
            "warn",
        )

    async def llm_call(self, req: LLMRequest) -> LLMResponse:
        self.budget.check()
        agent = req.purpose.split(":")[-1]
        started = self.trace.emit(
            "llm_call_started", agent, {"purpose": req.purpose, "model": req.model}
        )

        async def attempt(n: int) -> LLMResponse:
            return (await self.llm.generate(req)).model_copy(update={"attempt": n})

        try:
            resp = await self.limiter.call(req.model, attempt)
        except BaseException:
            self.budget.release()
            raise
        self.budget.charge(resp.tokens_in, resp.tokens_out)
        self.trace.emit(
            "llm_call_finished",
            agent,
            {
                "purpose": req.purpose,
                "tokens_in": resp.tokens_in,
                "tokens_out": resp.tokens_out,
                "latency_ms": resp.latency_ms,
                "attempt": resp.attempt,
                "source": resp.source,
            },
        )
        if self.run_dir and self.settings.trace.store_prompts:
            path = self.run_dir / "llm" / f"{started.seq:04d}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            dump = {
                "request": req.model_dump(exclude={"response_schema"}),
                "response": resp.model_dump(),
            }
            path.write_text(json.dumps(dump, indent=1, default=str), encoding="utf-8")
        return resp
