"""HTTP and SSE routes (02 §5)."""

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from advisor_copilot.actions import apply_approval
from advisor_copilot.data_access import get_client, get_targets, list_clients
from advisor_copilot.harness.context import profile_summary
from advisor_copilot.harness.orchestrator import run_pipeline, start_run
from advisor_copilot.harness.state import RunState, load_state, state_path
from advisor_copilot.harness.trace import TraceBus, load_events
from advisor_copilot.models import ApprovalDecision
from advisor_copilot.replay import load_replay, scenario_for, scenarios
from advisor_copilot.tools.common import positions
from advisor_copilot.tools.portfolio import allocation
from advisor_copilot.tools.registry import flags_for_client

router = APIRouter(prefix="/api")
SafeId = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,80}$")]  # ids become file paths


class RunRequest(BaseModel):
    client_id: str
    request_text: str = ""
    preset: str | None = None


@router.get("/health")
def health(request: Request) -> dict:
    s = request.app.state.settings
    return {"status": "ok", "run_mode": s.run_mode, "models": s.models.model_dump()}


@router.get("/clients")
def clients() -> list[dict]:
    out = []
    for c in list_clients():
        total, _ = allocation(c)
        kyc = not c.kyc_missing()
        flags = [f for f in flags_for_client(c.client_id) if f.severity != "info"] if kyc else []
        out.append(
            {
                "client_id": c.client_id,
                "name": c.name,
                "age": c.age,
                "risk_profile": c.risk_profile,
                "total_cad": round(total, 2),
                "flag_count": len(flags) if kyc else None,
                "kyc_complete": kyc,
            }
        )
    return out


@router.get("/clients/{client_id}")
def client_detail(client_id: SafeId) -> dict:
    try:
        c = get_client(client_id)
    except KeyError:
        raise HTTPException(404, "unknown client") from None
    total, alloc = allocation(c)
    targets = get_targets(c.risk_profile) if c.risk_profile else {}
    return {
        "client": profile_summary(c),
        "total_cad": round(total, 2),
        "positions": [
            {
                "account_type": p.account_type,
                "ticker": p.ticker,
                "units": p.units,
                "market_value_cad": round(p.market_value, 2),
            }
            for p in positions(c)
        ],
        "allocation": [
            {"asset_class": ac, "current_pct": round(v, 2), "target_pct": targets.get(ac)}
            for ac, v in alloc.items()
        ],
    }


@router.post("/runs")
async def create_run(body: RunRequest, request: Request) -> dict:
    app = request.app.state
    sc = scenario_for(body.client_id, body.request_text, body.preset)
    state, deps = await start_run(
        body.client_id,
        body.request_text,
        body.preset,
        app.settings,
        sc["id"] if sc else None,
        app.llm,
    )
    app.runs[state.run_id] = (state, deps, asyncio.create_task(run_pipeline(state, deps)))
    return {"run_id": state.run_id}


def _state(request: Request, run_id: str) -> RunState:
    app = request.app.state
    if run_id in app.runs:
        return app.runs[run_id][0]
    if not state_path(app.settings.path("runs"), run_id).exists():
        raise HTTPException(404, "unknown run")
    return load_state(run_id, app.settings.path("runs"))


@router.get("/runs/{run_id}")
def get_run(run_id: SafeId, request: Request) -> RunState:
    return _state(request, run_id)


@router.get("/runs/{run_id}/events")
async def run_events(run_id: SafeId, request: Request) -> EventSourceResponse:
    app = request.app.state
    path = app.settings.path("runs") / run_id / "trace.jsonl"
    if run_id not in app.runs and not path.exists():
        raise HTTPException(404, "unknown run")

    async def gen() -> AsyncIterator[dict]:
        if run_id in app.runs:
            q = app.runs[run_id][1].trace.subscribe()
            while (e := await q.get()) is not None:
                yield {"id": str(e.seq), "data": e.model_dump_json()}
        else:
            for e in load_events(path):
                yield {"id": str(e.seq), "data": e.model_dump_json()}

    return EventSourceResponse(gen())


@router.post("/runs/{run_id}/approval")
def approval(run_id: SafeId, decision: ApprovalDecision, request: Request) -> dict:
    app = request.app.state
    state = _state(request, run_id)
    runs = app.settings.path("runs")
    trace = (
        app.runs[run_id][1].trace
        if run_id in app.runs
        else TraceBus(run_id, runs / run_id / "trace.jsonl")
    )
    try:
        outbox = apply_approval(state, decision, runs, trace)
    except ValueError as e:
        raise HTTPException(409, str(e)) from None
    return {"state": state, "outbox": outbox}


@router.get("/replays")
def replays(request: Request) -> list[dict]:
    d = request.app.state.settings.path("replays")
    return [
        {"scenario_id": sc["id"], "title": sc["title"], "client_id": sc["client_id"]}
        for sc in scenarios()
        if not sc.get("hidden") and (d / f"{sc['id']}.json").exists()
    ]


@router.get("/replays/{scenario_id}")
def replay(scenario_id: SafeId, request: Request) -> dict:
    try:
        return load_replay(scenario_id, request.app.state.settings)
    except FileNotFoundError:
        raise HTTPException(404, "no replay for that scenario") from None
