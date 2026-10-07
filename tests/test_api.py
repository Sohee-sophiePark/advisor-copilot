"""Advisor views, chat thread (review, follow-up, approval), thread budget, dev routes, export."""

import json
from pathlib import Path

import httpx
import pytest
from scripted_fixtures import script_full_review

from advisor_copilot.api.app import create_app
from advisor_copilot.api.routes import export_static
from advisor_copilot.config import load_settings
from advisor_copilot.llm.base import LLMResponse
from advisor_copilot.llm.scripted import ScriptedClient


def settings(tmp_path: Path, **budget: int):  # noqa: ANN201
    s = load_settings(env={"RUN_MODE": "replay"})
    paths = s.paths.model_copy(
        update={"runs": str(tmp_path / "runs"), "db": str(tmp_path / "app.db")}
    )
    return s.model_copy(update={"paths": paths, "budget": s.budget.model_copy(update=budget)})


def client(app, host: str = "127.0.0.1") -> httpx.AsyncClient:  # noqa: ANN001
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=(host, 1)), base_url="http://t"
    )


@pytest.fixture
def scripted() -> ScriptedClient:
    return ScriptedClient()


async def turn(c: httpx.AsyncClient, app, thread_id: str, **body: str) -> dict:  # noqa: ANN001
    run_id = (await c.post(f"/api/threads/{thread_id}/messages", json=body)).json()["run_id"]
    await app.state.runs[run_id][2]
    return (await c.get(f"/api/runs/{run_id}")).json()


async def test_views(tmp_path: Path) -> None:
    async with client(create_app(settings(tmp_path))) as c:
        b = (await c.get("/api/book")).json()
        assert b["stats"]["households"] == 100
        rows = {h["client_id"]: h for h in b["households"]}
        assert rows["C002"]["top_level"] == "critical" and rows["C004"]["top_level"] == "kyc"
        assert rows["C115"]["attention"][0]["text"].startswith("Review overdue")
        d = (await c.get("/api/clients/C001")).json()
        assert d["allocation"][1] == {
            "asset_class": "CA_BONDS",
            "current_pct": 27.4,
            "target_pct": 37,
        }
        assert d["goals"][0]["required_pct"] < d["goals"][0]["model_pct"]
        assert (await c.get("/api/clients/C999")).status_code == 404
        assert (await c.get("/api/clients/..%2Fx")).status_code in (404, 422)
        m = (await c.get("/api/market")).json()
        assert len(m["indicators"]) == 7 and all(len(i["history"]) == 9 for i in m["indicators"])


async def test_thread_review_follow_up_approval(tmp_path: Path, scripted: ScriptedClient) -> None:
    app = create_app(settings(tmp_path), scripted)
    async with client(app) as c:
        th = (await c.post("/api/threads", json={"client_id": "C001"})).json()["thread_id"]
        script_full_review(scripted, "C001")
        first = await turn(c, app, th, preset="annual_review")
        assert first["status"] == "AWAITING_APPROVAL" and first["mode"] == "recommendation"
        scripted.add(
            "router",
            LLMResponse(
                parsed={"route": "follow_up", "domains": [], "reason": "x", "confidence": 0.9}
            ),
        )
        scripted.add(
            "synthesizer",
            LLMResponse(
                parsed={
                    "answer": "Daniel has {{m:tax.tfsa_room.cad}} of room.",
                    "suggested_questions": [],
                }
            ),
        )
        second = await turn(c, app, th, text="How much room again?")
        assert (
            second["route"]["route"] == "follow_up" and second["budget_snapshot"]["llm_calls"] == 2
        )
        msgs = (await c.get(f"/api/threads/{th}")).json()["messages"]
        assert [m["role"] for m in msgs] == ["advisor", "copilot", "advisor", "copilot"]
        assert msgs[0]["text"] == "Prepare annual review" and msgs[3]["route"] == "follow_up"
        assert msgs[3]["text"] == "Daniel has $14,000 of room."
        body = (
            await c.post(f"/api/runs/{first['run_id']}/approval", json={"decision": "approve"})
        ).json()
        assert body["state"]["status"] == "COMPLETED" and body["outbox"]["tasks"]


async def test_kyc_blocked_turn_and_budget(tmp_path: Path) -> None:
    app = create_app(settings(tmp_path))
    async with client(app) as c:
        th = (await c.post("/api/threads", json={"client_id": "C101"})).json()["thread_id"]
        st = await turn(c, app, th, preset="annual_review")
        assert st["status"] == "BLOCKED" and st["message"].startswith("KYC refresh required")
        assert (await c.post(f"/api/threads/{th}/messages", json={})).status_code == 422
    capped = create_app(settings(tmp_path, thread_max_calls=0))
    async with client(capped) as c:
        th = (await c.post("/api/threads", json={"client_id": "C001"})).json()["thread_id"]
        assert (await c.post(f"/api/threads/{th}/messages", json={"text": "hi"})).status_code == 429


async def test_dev_routes_need_flag_and_loopback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with client(create_app(settings(tmp_path))) as c:
        assert (await c.get("/api/dev/runs")).status_code == 404
    monkeypatch.setenv("DEV_CONSOLE", "1")
    app = create_app(settings(tmp_path))
    async with client(app) as c:
        assert (await c.get("/api/dev/runs")).json() == []
        assert (await c.get("/api/dev/usage")).json()["daily_call_cap"] == 500
    async with client(app, host="10.0.0.5") as c:
        assert (await c.get("/api/dev/runs")).status_code == 403


def test_export_static() -> None:
    data = json.loads(export_static(load_settings(env={})))
    assert len(data["clients"]) == 100 and data["book"]["stats"]["households"] == 100
    assert {"C001", "C002", "C003"} <= set(data["recorded"])
