"""Per-run dependency container; `llm_call` = budget check → limiter → client → trace → charge."""

import json
from dataclasses import dataclass, field
from pathlib import Path

from advisor_copilot.config import Settings
from advisor_copilot.db import Store
from advisor_copilot.harness.budget import BudgetExhausted, RunBudget
from advisor_copilot.harness.trace import TraceBus
from advisor_copilot.llm.base import LLMClient, LLMRequest, LLMResponse, RetryableLLMError
from advisor_copilot.llm.limiter import RateLimiter


@dataclass
class Deps:
    settings: Settings
    llm: LLMClient
    limiter: RateLimiter
    budget: RunBudget
    trace: TraceBus
    run_dir: Path | None = None
    store: Store | None = None  # live mode only: daily usage cap and caches
    exhausted: set[str] = field(default_factory=set)  # models that ran out of quota in this run

    def __post_init__(self) -> None:
        self.limiter.on_retry = lambda status, wait, attempt: self.trace.emit(
            "llm_retry",
            "system",
            {"status": status, "wait_ms": int(wait * 1000), "attempt": attempt},
            "warn",
        )

    async def llm_call(self, req: LLMRequest) -> LLMResponse:
        """Live mode: on quota (429) or overload (503) after retries, use the next model in
        `fallback_models` for the rest of the run. Record and replay never switch models."""
        chain = (
            [req.model, *self.settings.fallback_models] if self.settings.run_mode == "live" else []
        )
        models = [m for m in dict.fromkeys(chain) if m not in self.exhausted] or [req.model]
        for i, model in enumerate(models):
            try:
                return await self._call(req.model_copy(update={"model": model}))
            except RetryableLLMError as e:
                if i == len(models) - 1 or e.status not in (429, 503):
                    raise
                self.exhausted.add(model)
                payload = {"from": model, "to": models[i + 1], "status": e.status}
                self.trace.emit("model_fallback", req.purpose.split(":")[-1], payload, "warn")
        raise AssertionError("unreachable")

    async def _call(self, req: LLMRequest) -> LLMResponse:
        if self.store and self.store.usage_today(req.model) >= self.settings.budget.daily_call_cap:
            raise BudgetExhausted("daily_call_cap")
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
        if self.store and resp.source == "live":
            self.store.add_usage(req.model, resp.tokens_in, resp.tokens_out)
        self.trace.emit(
            "llm_call_finished",
            agent,
            {
                "purpose": req.purpose,
                "model": req.model,
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
