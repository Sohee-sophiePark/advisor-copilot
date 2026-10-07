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
