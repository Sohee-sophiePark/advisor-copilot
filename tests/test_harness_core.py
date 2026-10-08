"""Trace bus with JSONL sink and subscribers; atomic state checkpoints; run budget."""

from pathlib import Path

import pytest

from advisor_copilot.config import BudgetCfg
from advisor_copilot.harness.budget import BudgetExhausted, RunBudget
from advisor_copilot.harness.state import RunState, RunStatus, load_state, save_state
from advisor_copilot.harness.trace import TraceBus, load_events


async def test_trace_sink_and_subscribers(tmp_path: Path) -> None:
    bus = TraceBus("r1", tmp_path / "trace.jsonl")
    bus.emit("run_started", "orchestrator", {"client_id": "C001"})
    q = bus.subscribe()
    bus.emit("llm_call_finished", "router", {"tokens_in": 3, "tokens_out": 4, "latency_ms": 1})
    bus.close()
    assert [e.seq for e in load_events(tmp_path / "trace.jsonl")] == [1, 2]
    assert [(await q.get()).type for _ in range(2)] == ["run_started", "llm_call_finished"]
    assert await q.get() is None
    assert bus.totals()["llm_calls"] == 1 and bus.totals()["tokens_in"] == 3


def test_state_round_trip_is_atomic(tmp_path: Path) -> None:
    state = RunState(run_id="r1", client_id="C001", request_text="", status=RunStatus.ROUTED)
    path = save_state(state, tmp_path)
    assert path == tmp_path / "r1" / "state.json" and not path.with_suffix(".tmp").exists()
    assert load_state("r1", tmp_path).status == RunStatus.ROUTED


def test_budget_limits() -> None:
    budget = RunBudget(
        BudgetCfg(
            max_llm_calls=2,
            max_total_tokens=100,
            max_wall_seconds=60,
            per_call_timeout_seconds=1,
            daily_call_cap=9,
            thread_max_calls=9,
            thread_max_tokens=9,
        )
    )
    for _ in range(2):
        budget.check()
        budget.charge(10, 10)
    with pytest.raises(BudgetExhausted, match="max_llm_calls"):
        budget.check()
    assert budget.snapshot()["llm_calls"] == 2 and budget.snapshot()["tokens"] == 40


async def test_live_fallback_switches_model_on_quota_and_stays(deps) -> None:  # noqa: ANN001
    from advisor_copilot.llm.base import FatalLLMError, LLMRequest, LLMResponse, RetryableLLMError

    deps.settings = deps.settings.model_copy(update={"run_mode": "live"})
    primary = deps.settings.models.router
    quota = RetryableLLMError(
        429, retry_after_s=80_000.0
    )  # daily quota: fails fast, then falls back
    deps.llm.add("router", quota, LLMResponse(text="a"), LLMResponse(text="b"))
    req = LLMRequest(model=primary, system="s", messages=[], purpose="router")
    assert (await deps.llm_call(req)).text == "a"
    assert [r.model for r in deps.llm.requests] == [primary, "gemini-3.5-flash-lite"]
    assert any(e.type == "model_fallback" for e in deps.trace.events)
    await deps.llm_call(req)  # the exhausted model is skipped for the rest of the run
    assert deps.llm.requests[-1].model == "gemini-3.5-flash-lite"
    deps.llm.add("router", FatalLLMError("400 bad request"))
    with pytest.raises(FatalLLMError):  # real errors never switch models
        await deps.llm_call(req)


async def test_replay_never_falls_back(deps) -> None:  # noqa: ANN001
    from advisor_copilot.llm.base import LLMRequest, RetryableLLMError

    deps.llm.add("router", RetryableLLMError(429, retry_after_s=80_000.0))
    with pytest.raises(RetryableLLMError):
        model = deps.settings.models.router
        await deps.llm_call(LLMRequest(model=model, system="s", messages=[], purpose="router"))
    assert len(deps.llm.requests) == 1
