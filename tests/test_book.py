"""Book chat: book tools against the book figures, routing scope, G5.13, scripted run, API."""

from pathlib import Path

import pytest
from helpers import metrics
from test_api import client, settings, turn

from advisor_copilot.agents.router import post_rules
from advisor_copilot.api.app import create_app
from advisor_copilot.harness.chat import reply_text
from advisor_copilot.harness.context import SynthContext
from advisor_copilot.harness.deps import Deps
from advisor_copilot.harness.gates import answer_gates, input_gate
from advisor_copilot.harness.orchestrator import run_pipeline
from advisor_copilot.harness.state import RunState, RunStatus
from advisor_copilot.llm.base import LLMResponse, ToolCall
from advisor_copilot.llm.scripted import ScriptedClient
from advisor_copilot.models import BOOK, RouteDecision
from advisor_copilot.tools import registry as reg


def run(name: str, **args: object) -> tuple[dict, list[str]]:
    r = reg.run_tool(name, BOOK, args)
    return metrics(r), [h["client_id"] for h in r.data.get("households", [])]


def test_book_tools_match_book_figures() -> None:
    m, ids = run("book_attention", level="critical")
    assert m["book.attention_critical.matches.count"] == 13 and len(ids) == 10
    assert [
        m[f"book.attention_critical.{k}.count"] for k in ("risk_limit", "drift", "concentration")
    ] == [9, 5, 2]
    assert run("book_attention")[0]["book.attention_all.matches.count"] == 35
    assert run("book_attention", level="kyc")[1] == ["C101", "C004"]
    seg = run("book_segments", group_by="life_stage")[0]
    assert [
        seg[f"book.seg_{g}.households.count"]
        for g in ("accumulation", "pre_retirement", "retirement")
    ] == [40, 28, 32]
    m, ids = run("book_exposure", target="NRTH")
    assert sorted(ids) == ["C002", "C020", "C030", "C054", "C079", "C102", "C103"]
    assert m["book.C002.exposure_NRTH.pct"] == 28.57
    m, ids = run("book_market_impact", target="CA_EQUITY", move_pct=-10, limit=3)
    assert ids[0] == "C107" and m["book.C107.impact_CA_EQUITY.pct"] == -4.0
    assert run("book_risk", kind="volatility")[0]["book.risk_volatility.breaches.count"] == 9
    assert run("book_risk", kind="concentration")[0]["book.risk_concentration.breaches.count"] == 2
    assert (
        run("book_tax", kind="unused_tfsa_room")[0]["book.tax_unused_tfsa_room.matches.count"] == 8
    )
    assert run("book_tax", kind="us_in_tfsa")[0]["book.tax_us_in_tfsa.matches.count"] == 7
    assert run("book_goals")[1] == ["C110"]
    with pytest.raises(reg.ToolArgsError):
        run("book_exposure", target="DOGE")


def test_book_tools_are_book_only() -> None:
    assert {t.name for t in reg.tools_for("book")} == {
        "book_attention", "book_segments", "book_risk", "book_exposure",
        "book_market_impact", "book_tax", "book_goals", "get_market_snapshot",
    }  # fmt: skip
    assert not any(r.tool.startswith("book_") for r in reg.run_all_for_client("C001"))


def test_post_rules_keep_each_scope() -> None:
    d = lambda r, c=0.9: RouteDecision(route=r, domains=[], reason="x", confidence=c)  # noqa: E731
    assert post_rules(d("targeted"), 0.55, None, book=True)[0].route == "book_question"
    assert post_rules(d("book_question"), 0.55)[0].route == "full_review"
    assert post_rules(d("out_of_scope", 0.2), 0.55, None, True)[0].domains == ["book"]
    fu = post_rules(d("follow_up"), 0.55, ["book"], True)[0]
    assert (fu.route, fu.domains) == ("follow_up", ["book"])
    assert post_rules(d("follow_up"), 0.55, None, True)[0].route == "book_question"
    assert input_gate(BOOK, "Who first?", None).passed


def test_g5_13_known_households() -> None:
    r = reg.run_tool("book_exposure", BOOK, {"target": "NRTH"})
    ctx = SynthContext(None, [], "q", "book_question", [], {m.key: m for m in r.metrics}, {})
    ok = {
        "answer": "{{h:C002}} holds {{m:book.C002.exposure_NRTH.pct}}.",
        "suggested_questions": [],
    }
    assert answer_gates(ok, ctx, 120)[1].passed
    for text in (
        "{{h:C001}} holds none.",
        "C002 holds the most.",
        "Margaret Leblanc holds the most.",
        "The thirteen critical households come first.",
    ):
        v = answer_gates({"answer": text, "suggested_questions": []}, ctx, 120)[1].violations
        assert any(x.startswith("G5.13") for x in v), text


def script_book(llm: ScriptedClient) -> None:
    route = {"route": "book_question", "domains": [], "reason": "x", "confidence": 0.9}
    finding = {
        "finding_id": "x",
        "title": "Critical households",
        "severity": "info",
        "detail": "{{h:C006}} leads {{m:book.attention_critical.matches.count}} households.",
        "metric_refs": ["book.attention_critical.matches.count"],
        "flag_refs": [],
    }
    llm.add("router", LLMResponse(parsed=route))
    llm.add(
        "analyst:book",
        LLMResponse(
            tool_calls=[ToolCall(id="a", name="book_attention", args={"level": "critical"})]
        ),
        LLMResponse(
            tool_calls=[ToolCall(id="s", name="submit_findings", args={"findings": [finding]})]
        ),
    )
    answer = "Start with {{h:C006}}; {{m:book.attention_critical.matches.count}} are critical."
    llm.add("synthesizer", LLMResponse(parsed={"answer": answer, "suggested_questions": []}))


async def test_book_run_end_to_end(deps: Deps, tmp_path: Path) -> None:
    script_book(deps.llm)
    st = RunState(run_id="t-book", client_id=BOOK, request_text="Who should I call first?")
    st = await run_pipeline(st, deps, tmp_path)
    assert st.status == RunStatus.COMPLETED and st.mode == "answer"
    assert st.route.domains == ["book"] and [g.gate for g in st.gate_results] == ["G0", "G5"]
    assert reply_text(st).startswith("Start with ") and "13 are critical" in reply_text(st)
    assert "C006" not in reply_text(st)
    assert deps.llm.requests[0].system.startswith(
        "# Role\nYou classify an advisor's question about their whole book"
    )


async def test_book_thread_api(tmp_path: Path) -> None:
    llm = ScriptedClient()
    app = create_app(settings(tmp_path), llm)
    async with client(app) as c:
        assert (await c.post("/api/threads", json={"client_id": "C999"})).status_code == 404
        th = (await c.post("/api/threads", json={"client_id": BOOK})).json()["thread_id"]
        script_book(llm)
        st = await turn(c, app, th, text="Who should I call first?")
        assert st["status"] == "COMPLETED" and st["client_id"] == BOOK
