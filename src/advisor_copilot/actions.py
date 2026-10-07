"""Approval handler: writes the CRM-shaped outbox on approve, stores the note on reject (03 §12)."""

import json
from pathlib import Path

from advisor_copilot.harness.state import RunState, RunStatus, save_state
from advisor_copilot.harness.trace import TraceBus
from advisor_copilot.models import ApprovalDecision

PRIORITY = {"high": "High", "medium": "Normal", "low": "Low"}


def build_outbox(state: RunState) -> dict:
    assert state.final is not None
    rec = state.final.recommendation
    tasks = [
        {
            "Subject": f"Review: {a.description[:60]}",
            "WhatId": state.client_id,
            "Priority": PRIORITY[a.priority],
            "Status": "Not Started",
            "Description": f"{a.description} {a.rationale}",
            "Source": f"AdvisorCopilot/{state.run_id}",
        }
        for a in rec.actions
        if a.type != "no_action"
    ]
    note = {
        "Title": "Advisor Copilot recommendation (approved)",
        "ParentId": state.client_id,
        "Body": f"{rec.headline}\n\n{rec.summary}\n\n{state.final.disclosure}",
    }
    return {"tasks": tasks, "notes": [note]}


def apply_approval(
    state: RunState, decision: ApprovalDecision, runs_dir: Path, trace: TraceBus
) -> dict | None:
    """Record the decision; approve writes `crm_outbox.json`, reject stores the note only."""
    if state.status != RunStatus.AWAITING_APPROVAL:
        raise ValueError(f"run {state.run_id} is {state.status}, not AWAITING_APPROVAL")
    state.approval = decision
    trace.emit(
        "approval_recorded",
        "human",
        {"decision": decision.decision, "advisor_note": decision.advisor_note},
    )
    outbox = None
    if decision.decision == "approve":
        outbox = build_outbox(state)
        path = runs_dir / state.run_id / "crm_outbox.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(outbox, indent=2), encoding="utf-8")
        trace.emit(
            "crm_outbox_written", "human", {"tasks_count": len(outbox["tasks"]), "notes_count": 1}
        )
    state.status = RunStatus.COMPLETED
    state.completed_steps.append("approval")
    save_state(state, runs_dir)
    return outbox
