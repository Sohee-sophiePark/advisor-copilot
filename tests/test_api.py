"""Health, clients, run creation, SSE through run_completed, approval, replays (replay mode)."""

import json
from pathlib import Path

import httpx
import pytest
from scripted_fixtures import script_full_review

from advisor_copilot.api.app import create_app
from advisor_copilot.config import load_settings
from advisor_copilot.llm.scripted import ScriptedClient


@pytest.fixture
async def api(tmp_path: Path):  # noqa: ANN201
    s = load_settings(env={"RUN_MODE": "replay"})
    s = s.model_copy(
        update={
            "paths": s.paths.model_copy(update={"runs": str(tmp_path), "replays": str(tmp_path)})
        }
    )
    scripted = ScriptedClient()
    app = create_app(s, scripted)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c, scripted, app


async def events_until_done(c: httpx.AsyncClient, run_id: str) -> list[str]:
    types = []
    async with c.stream("GET", f"/api/runs/{run_id}/events") as r:
        async for line in r.aiter_lines():
            if line.startswith("data:"):
                types.append(json.loads(line[5:])["type"])
            if types and types[-1] == "run_completed":
                break
    return types


async def test_health_and_clients(api) -> None:  # noqa: ANN001
    c, _, _ = api
    assert (await c.get("/api/health")).json()["run_mode"] == "replay"
    clients = {x["client_id"]: x for x in (await c.get("/api/clients")).json()}
    assert clients["C002"]["flag_count"] == 4 and clients["C002"]["total_cad"] == 264600.0
    assert clients["C004"]["flag_count"] is None and clients["C004"]["kyc_complete"] is False
    detail = (await c.get("/api/clients/C001")).json()
    assert detail["allocation"][1] == {
        "asset_class": "CA_BONDS",
        "current_pct": 27.4,
        "target_pct": 37,
    }
    assert (await c.get("/api/clients/C999")).status_code == 404


async def test_kyc_blocked_run_streams_to_completion(api) -> None:  # noqa: ANN001
    c, _, _ = api
    run_id = (
        await c.post("/api/runs", json={"client_id": "C004", "preset": "annual_review"})
    ).json()["run_id"]
    types = await events_until_done(c, run_id)
    assert types[0] == "run_started" and "kyc_blocked" in types and types[-1] == "run_completed"
    state = (await c.get(f"/api/runs/{run_id}")).json()
    assert state["status"] == "BLOCKED" and state["budget_snapshot"]["llm_calls"] == 0
    assert (
        await c.post(f"/api/runs/{run_id}/approval", json={"decision": "approve"})
    ).status_code == 409


async def test_full_run_then_approval_writes_outbox(api, tmp_path: Path) -> None:  # noqa: ANN001
    c, scripted, app = api
    script_full_review(scripted, "C001")
    run_id = (
        await c.post("/api/runs", json={"client_id": "C001", "preset": "annual_review"})
    ).json()["run_id"]
    types = await events_until_done(c, run_id)
    assert types.count("agent_started") == 4 and "awaiting_approval" in types
    body = (await c.post(f"/api/runs/{run_id}/approval", json={"decision": "approve"})).json()
    assert body["state"]["status"] == "COMPLETED" and body["outbox"]["tasks"][0]["WhatId"] == "C001"
    assert (tmp_path / run_id / "crm_outbox.json").exists()
    late = await events_until_done(c, run_id)  # late subscriber gets history and ends
    assert late[0] == "run_started" and "run_completed" in late


async def test_replays_list_and_404(api) -> None:  # noqa: ANN001
    c, _, _ = api
    assert (await c.get("/api/replays")).json() == []
    assert (await c.get("/api/replays/S1")).status_code == 404
    assert (await c.get("/api/runs/nope")).status_code == 404
