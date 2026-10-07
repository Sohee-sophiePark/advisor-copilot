"""Approval writes a CRM-shaped outbox; rejection stores the note only; wrong status is refused."""

from pathlib import Path

import pytest
from test_gates import GOOD

from advisor_copilot.actions import apply_approval
from advisor_copilot.harness.state import RunState, RunStatus
from advisor_copilot.harness.trace import TraceBus
from advisor_copilot.models import ApprovalDecision, Metric, Recommendation
from advisor_copilot.render import render


def awaiting(tmp_path: Path) -> RunState:
    m = {
        "conc.NRTH.pct": Metric(
            key="conc.NRTH.pct", value=28.57, unit="pct", label="x", source_tool="t"
        )
    }
    return RunState(
        run_id="r1",
        client_id="C002",
        request_text="",
        status=RunStatus.AWAITING_APPROVAL,
        final=render(Recommendation.model_validate(GOOD), m),
    )


def test_approve_writes_outbox(tmp_path: Path) -> None:
    state, bus = awaiting(tmp_path), TraceBus("r1")
    outbox = apply_approval(state, ApprovalDecision(decision="approve"), tmp_path, bus)
    task = outbox["tasks"][0]
    assert (
        task["WhatId"] == "C002"
        and task["Priority"] == "High"
        and task["Source"] == "AdvisorCopilot/r1"
    )
    assert outbox["notes"][0]["Body"].endswith("verify before discussing with the client.")
    assert (tmp_path / "r1" / "crm_outbox.json").exists() and state.status == RunStatus.COMPLETED
    assert [e.type for e in bus.events] == ["approval_recorded", "crm_outbox_written"]


def test_reject_stores_note_without_outbox(tmp_path: Path) -> None:
    state = awaiting(tmp_path)
    assert (
        apply_approval(
            state,
            ApprovalDecision(decision="reject", advisor_note="too aggressive"),
            tmp_path,
            TraceBus("r1"),
        )
        is None
    )
    assert (
        state.approval.advisor_note == "too aggressive"
        and not (tmp_path / "r1" / "crm_outbox.json").exists()
    )


def test_approval_refused_unless_awaiting(tmp_path: Path) -> None:
    state = awaiting(tmp_path).model_copy(update={"status": RunStatus.BLOCKED})
    with pytest.raises(ValueError, match="not AWAITING_APPROVAL"):
        apply_approval(state, ApprovalDecision(decision="approve"), tmp_path, TraceBus("r1"))
