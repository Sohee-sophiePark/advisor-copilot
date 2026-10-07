"""RunState, RunStatus, and atomic checkpoint save/load."""

import datetime as dt
import os
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from advisor_copilot.models import (
    AnalystReport,
    ApprovalDecision,
    EvalVerdict,
    Flag,
    GateResult,
    Metric,
    Recommendation,
    RenderedRecommendation,
    RouteDecision,
)


class RunStatus(StrEnum):
    CREATED = "CREATED"
    INPUT_GATED = "INPUT_GATED"
    BLOCKED = "BLOCKED"
    ROUTED = "ROUTED"
    ANALYZING = "ANALYZING"
    SYNTHESIZING = "SYNTHESIZING"
    GATING = "GATING"
    EVALUATING = "EVALUATING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    NEEDS_ADVISOR_REVIEW = "NEEDS_ADVISOR_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    DEGRADED = "DEGRADED"


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class RunState(BaseModel):
    run_id: str
    client_id: str
    request_text: str
    preset: str | None = None
    status: RunStatus = RunStatus.CREATED
    route: RouteDecision | None = None
    analyst_reports: dict[str, AnalystReport] = {}
    metrics: dict[str, Metric] = {}
    flags: dict[str, Flag] = {}
    drafts: list[Recommendation] = []
    gate_results: list[GateResult] = []
    eval_verdicts: list[EvalVerdict] = []
    revision_count: int = 0
    final: RenderedRecommendation | None = None
    message: str | None = None
    approval: ApprovalDecision | None = None
    budget_snapshot: dict[str, Any] = {}
    untrusted_flags: list[dict[str, Any]] = []
    error: str | None = None
    created_at: dt.datetime = Field(default_factory=_now)
    updated_at: dt.datetime = Field(default_factory=_now)
    completed_steps: list[str] = []


def state_path(runs_dir: Path, run_id: str) -> Path:
    return runs_dir / run_id / "state.json"


def save_state(state: RunState, runs_dir: Path) -> Path:
    """Write `runs/<run_id>/state.json` atomically (tmp file + os.replace)."""
    state.updated_at = _now()
    path = state_path(runs_dir, state.run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(state.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return path


def load_state(run_id: str, runs_dir: Path) -> RunState:
    return RunState.model_validate_json(state_path(runs_dir, run_id).read_text(encoding="utf-8"))
