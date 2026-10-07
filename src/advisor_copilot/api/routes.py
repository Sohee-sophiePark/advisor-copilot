"""HTTP and SSE routes: advisor views, chat threads, runs; dev routes only when DEV_CONSOLE=1."""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from advisor_copilot import book
from advisor_copilot.actions import apply_approval
from advisor_copilot.config import ROOT
from advisor_copilot.data_access import get_client, load_fixtures
from advisor_copilot.db import source_hash
from advisor_copilot.harness.chat import answer_key, reply_text, thread_context
from advisor_copilot.harness.orchestrator import run_pipeline, start_run
from advisor_copilot.harness.state import RunState, load_state, state_path
from advisor_copilot.harness.trace import TraceBus, load_events
from advisor_copilot.models import BOOK, ApprovalDecision
from advisor_copilot.replay import scenario_for

router = APIRouter(prefix="/api")
SafeId = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,80}$")]  # ids become file paths
PRESET_TEXT = {"annual_review": "Prepare annual review"}


class ThreadRequest(BaseModel):
    client_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")


class MessageRequest(BaseModel):
    text: str = Field("", max_length=1000)
    preset: str | None = None


def _known_client(client_id: str) -> None:
    try:
        get_client(client_id)
    except KeyError:
        raise HTTPException(404, "unknown client") from None


@router.get("/health")
def health(request: Request) -> dict:
    s = request.app.state.settings
    return {"status": "ok", "run_mode": s.run_mode, "models": s.models.model_dump()}


@router.get("/book")
def get_book() -> dict:
    return book.book()


@router.get("/clients/{client_id}")
def client_detail(client_id: SafeId) -> dict:
    _known_client(client_id)
    return book.client_detail(client_id)


@router.get("/instruments/{ticker}")
def instrument(ticker: SafeId) -> dict:
    if ticker not in load_fixtures().instruments:
        raise HTTPException(404, "unknown ticker")
    return book.instrument_view(ticker)


@router.get("/market")
def market() -> dict:
    return book.market_view()


@router.post("/threads")
def create_thread(body: ThreadRequest, request: Request) -> dict:
    if body.client_id != BOOK:
        _known_client(body.client_id)
    thread_id = uuid.uuid4().hex[:12]
    request.app.state.store.create_thread(thread_id, body.client_id)
    return {"thread_id": thread_id, "client_id": body.client_id}


@router.get("/threads")
def list_threads(
    request: Request, client_id: Annotated[str, Query(pattern=r"^[A-Za-z0-9_-]{1,80}$")]
) -> list[dict]:
    return request.app.state.store.threads(client_id)


@router.get("/threads/{thread_id}")
def get_thread(thread_id: SafeId, request: Request) -> dict:
    store = request.app.state.store
    if not (client_id := store.thread_client(thread_id)):
        raise HTTPException(404, "unknown thread")
    return {"thread_id": thread_id, "client_id": client_id, "messages": store.messages(thread_id)}


@router.post("/threads/{thread_id}/messages")
async def post_message(thread_id: SafeId, body: MessageRequest, request: Request) -> dict:
    """One chat turn. Checks the thread budget, reuses a cached answer (live), else starts a run."""
    app = request.app.state
    s, store, runs = app.settings, app.store, app.settings.path("runs")
    if not (client_id := store.thread_client(thread_id)):
        raise HTTPException(404, "unknown thread")
    if not body.text.strip() and body.preset not in PRESET_TEXT:
        raise HTTPException(422, "empty message")
    calls, tokens = store.thread_totals(thread_id)
    if calls >= s.budget.thread_max_calls or tokens >= s.budget.thread_max_tokens:
        raise HTTPException(429, "This conversation reached its budget. Start a new one.")
    book = client_id == BOOK
    data = source_hash(s.path("data")) if book else get_client(client_id).model_dump_json()
    key = answer_key(thread_id, body.text, body.preset, data)
    ctx = thread_context(store, thread_id, runs, s.chat.summary_turns)
    store.add_message(thread_id, "advisor", body.text or PRESET_TEXT[body.preset])
    if (
        s.run_mode == "live"
        and (cached := store.cache_get(key))
        and state_path(runs, cached).exists()
    ):
        st = load_state(cached, runs)
        store.add_message(
            thread_id, "copilot", reply_text(st), cached, st.route.route if st.route else None
        )
        return {"run_id": cached, "cached": True}
    sc = (
        None if ctx.summary else scenario_for(client_id, body.text, body.preset)
    )  # replay: first turn only
    state, deps = await start_run(
        client_id, body.text, body.preset, s, sc and sc["id"], app.llm, thread_id
    )

    async def turn() -> None:
        st = await run_pipeline(state, deps, thread=ctx)
        route = st.route.route if st.route else None
        snap = st.budget_snapshot
        store.add_message(
            thread_id,
            "copilot",
            reply_text(st),
            st.run_id,
            route,
            snap.get("llm_calls", 0),
            snap.get("tokens", 0),
        )
        if s.run_mode == "live" and st.status in ("COMPLETED", "AWAITING_APPROVAL"):
            store.cache_put(key, st.run_id)

    app.runs[state.run_id] = (state, deps, asyncio.create_task(turn()))
    return {"run_id": state.run_id, "cached": False}


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


def loopback_only(request: Request) -> None:
    if request.client is None or request.client.host not in {"127.0.0.1", "::1"}:
        raise HTTPException(403, "developer console is local only")


dev = APIRouter(prefix="/api/dev", dependencies=[Depends(loopback_only)])


def _run_cost(events: list, request: Request) -> float:
    pricing = request.app.state.settings.pricing
    done = [e.payload for e in events if e.type == "llm_call_finished"]
    return round(
        sum(pricing.cost(p.get("model", ""), p["tokens_in"], p["tokens_out"]) for p in done), 6
    )


@dev.get("/runs")
def dev_runs(request: Request) -> list[dict]:
    runs = request.app.state.settings.path("runs")
    paths = sorted(runs.glob("*/state.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:200]
    out = []
    for p in paths:
        st = RunState.model_validate_json(p.read_text(encoding="utf-8"))
        out.append(
            {
                "run_id": st.run_id,
                "client_id": st.client_id,
                "request_text": st.request_text,
                "preset": st.preset,
                "thread_id": st.thread_id,
                "status": st.status,
                "mode": st.mode,
                "route": st.route.route if st.route else None,
                "created_at": st.created_at,
                **st.budget_snapshot,
            }
        )
    return out


@dev.get("/runs/{run_id}")
def dev_run(run_id: SafeId, request: Request) -> dict:
    state = _state(request, run_id)
    path = request.app.state.settings.path("runs") / run_id / "trace.jsonl"
    events = load_events(path) if path.exists() else []
    return {"state": state, "events": events, "cost_usd": _run_cost(events, request)}


@dev.get("/usage")
def dev_usage(request: Request) -> dict:
    s = request.app.state.settings
    rows = [
        {**r, "cost_usd": round(s.pricing.cost(r["model"], r["tokens_in"], r["tokens_out"]), 6)}
        for r in request.app.state.store.usage()
    ]
    return {
        "daily_call_cap": s.budget.daily_call_cap,
        "free_tier": s.pricing.free_tier,
        "rows": rows,
    }


@dev.get("/evals")
def dev_evals() -> dict:
    path = ROOT / "evals" / "reports" / "latest.md"
    return {
        "report": path.read_text(encoding="utf-8")
        if path.exists()
        else "No report yet: run make eval."
    }


def export_static(settings: object) -> str:
    """Everything the public replay build shows, as one JSON document (no LLM, no backend)."""
    from advisor_copilot.data_access import list_clients
    from advisor_copilot.replay import scenarios

    recorded: dict[str, list] = {}
    for sc in scenarios():
        path = settings.path("replays") / f"{sc['id']}.json"
        if sc.get("hidden") or not path.exists():
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        question = doc["request_text"] or PRESET_TEXT.get(doc.get("preset") or "", "")
        recorded.setdefault(doc["client_id"], []).append(
            {
                "scenario_id": doc["scenario_id"],
                "title": doc["title"],
                "question": question,
                "preset": doc.get("preset"),
                "state": doc["final_state"],
                "outbox": doc.get("outbox"),
            }
        )
    data = {
        "book": book.book(),
        "market": book.market_view(),
        "recorded": recorded,
        "clients": {c.client_id: book.client_detail(c.client_id) for c in list_clients()},
        "instruments": {t: book.instrument_view(t) for t in load_fixtures().instruments},
    }
    return json.dumps(data, default=str)
