"""Scripted LLM stand-ins: deterministic analyst, synthesizer and evaluator responses per scenario.

Used by the tests and, via `python evals/scripted_fixtures.py`, to write placeholder
cassettes/ and replays/ so `make eval`, CI and the UI work before `make record` replaces
them with real Gemini runs.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from advisor_copilot.actions import apply_approval  # noqa: E402
from advisor_copilot.config import get_settings  # noqa: E402
from advisor_copilot.data_access import get_client  # noqa: E402
from advisor_copilot.harness.gates import code_finding  # noqa: E402
from advisor_copilot.harness.orchestrator import make_deps, run_pipeline  # noqa: E402
from advisor_copilot.harness.state import RunState  # noqa: E402
from advisor_copilot.llm.base import LLMResponse, ToolCall  # noqa: E402
from advisor_copilot.llm.cassette import CassetteClient  # noqa: E402
from advisor_copilot.llm.scripted import ScriptedClient  # noqa: E402
from advisor_copilot.models import DOMAINS, ApprovalDecision  # noqa: E402
from advisor_copilot.replay import scenario_settings, scenarios, write_replay  # noqa: E402
from advisor_copilot.tools.registry import run_all_for_client, tools_for  # noqa: E402

PREFIX = {"portfolio": "PORT", "risk": "RISK", "tax": "TAX", "market": "MKT"}
CHECKS = [
    "suitability_respected",
    "critical_addressed",
    "faithful_to_findings",
    "client_specific",
    "untrusted_ignored",
]
PASS = {
    "verdict": "pass",
    "checks": dict.fromkeys(CHECKS, True),
    "scores": {"clarity_for_advisor": 5, "actionability": 4, "professional_tone": 5},
    "issues": [],
}
FAIL = {
    **PASS,
    "verdict": "revise",
    "checks": {**PASS["checks"], "critical_addressed": False},
    "issues": [{"criterion": "critical_addressed", "detail": "x", "suggested_fix": "y"}],
}
BASE_DRAFT = {
    "headline": "Reduce concentration in stages",
    "summary": "NRTH is {{m:conc.NRTH.pct}} of the portfolio.",
    "actions": [],
    "risks_and_considerations": [],
    "deferred": [],
    "client_talking_points": [],
}


def script_analysts(
    llm: ScriptedClient, client_id: str, domains: tuple[str, ...] = DOMAINS, prefetch: bool = False
) -> dict[str, list[str]]:
    """Each analyst calls all its tools and submits one finding per flag; returns id -> flags."""
    results = {r.tool: r for r in run_all_for_client(client_id)}
    must: dict[str, list[str]] = {}
    for d in domains:
        names = [t.name for t in tools_for(d)]
        calls = [
            ToolCall(
                id=str(i),
                name=n,
                args={"asset_classes": ["CA_BONDS"]} if n == "get_market_snapshot" else {},
            )
            for i, n in enumerate(names)
        ]
        findings = [code_finding(f, n).model_dump() for n in names for f in results[n].flags] or [
            {
                "finding_id": "i",
                "title": "Nothing to flag",
                "severity": "info",
                "detail": "All within limits.",
                "metric_refs": [],
                "flag_refs": [],
            }
        ]
        llm.add(
            f"analyst:{d}",
            *([] if prefetch else [LLMResponse(tool_calls=calls, tokens_in=1, tokens_out=1)]),
            LLMResponse(
                tool_calls=[ToolCall(id="s", name="submit_findings", args={"findings": findings})]
            ),
        )
        must.update(
            {
                f"{PREFIX[d]}-{i}": f["flag_refs"]
                for i, f in enumerate(findings, 1)
                if f["severity"] != "info"
            }
        )
    return must


def script_full_review(llm: ScriptedClient, client_id: str) -> list[str]:
    """Analysts + one draft that reduces any concentrated ticker and rebalances the rest."""
    refs = script_analysts(llm, client_id)
    client = get_client(client_id)
    conc = {
        i: f.split("FLAG-CONC-")[1]
        for i, flags in refs.items()
        for f in flags
        if f.startswith("FLAG-CONC-")
    }
    kinds = {  # remaining findings grouped by the action type that may address them (gate G5.11)
        "rebalance": ("FLAG-DRIFT", "FLAG-SUIT"),
        "relocate_holding": ("FLAG-L1",),
        "use_tfsa_room": ("FLAG-L3", "FLAG-L2"),
        "review_kyc": ("FLAG-GOAL",),
    }
    actions = [
        {
            "action_id": f"A{n}",
            "type": "reduce_position",
            "target": ticker,
            "direction": "decrease",
            "description": f"Reduce {ticker} in stages.",
            "rationale": "Concentration above the limit.",
            "finding_refs": [i],
            "priority": "high",
        }
        for n, (i, ticker) in enumerate(conc.items(), 1)
    ]
    for kind, prefixes in kinds.items():
        ids = [
            i
            for i, flags in refs.items()
            if i not in conc and any(f.startswith(prefixes) for f in flags)
        ]
        if ids:
            target, direction = (
                ("CA_BONDS", "increase") if kind == "rebalance" else ("TFSA", "move")
            )
            actions.append(
                {
                    "action_id": f"A-{kind}",
                    "type": kind,
                    "target": target,
                    "direction": direction,
                    "description": f"Address the {kind.replace('_', ' ')} findings.",
                    "rationale": "Findings from the analysts.",
                    "finding_refs": ids,
                    "priority": "high",
                }
            )
    draft = {
        **BASE_DRAFT,
        "summary": f"Total value is {{{{m:total.value.cad}}}} for {client.name}.",
        "actions": actions,
    }
    llm.add("synthesizer", LLMResponse(parsed=draft))
    llm.add("evaluator", LLMResponse(parsed=PASS))
    return list(refs)


def script_scenario(llm: ScriptedClient, sc: dict) -> None:
    sid, cid = sc["id"], sc["client_id"]
    if sid == "S2":
        llm.add("synthesizer", LLMResponse(parsed={**BASE_DRAFT, "summary": "Expect 12% returns."}))
    if sid == "S5":
        route = {
            "route": "targeted",
            "domains": ["tax"],
            "reason": "TFSA question",
            "confidence": 0.92,
        }
        llm.add("router", LLMResponse(parsed=route))
        script_analysts(llm, cid, ("tax",), prefetch=True)
        answer = {
            "answer": "Daniel has {{m:tax.tfsa_room.cad}} of TFSA room; idle cash fits there.",
            "suggested_questions": ["Should the US fund move to the RRSP?"],
        }
        llm.add("synthesizer", LLMResponse(parsed=answer))
        return
    if sid == "S11":
        llm.add(
            "router",
            LLMResponse(
                parsed={"route": "what_if", "domains": [], "reason": "x", "confidence": 0.9}
            ),
        )
        trade = {"sell_ticker": "NRTH", "sell_fraction": 0.5, "buy_ticker": "CBND"}
        submit = {
            "findings": [
                {
                    "finding_id": "x",
                    "title": "Concentration halves",
                    "severity": "info",
                    "detail": "NRTH goes to {{m:whatif.conc.NRTH.pct}}.",
                    "metric_refs": ["whatif.conc.NRTH.pct"],
                    "flag_refs": [],
                }
            ]
        }
        llm.add(
            "analyst:scenario",
            LLMResponse(tool_calls=[ToolCall(id="1", name="simulate_trade", args=trade)]),
            LLMResponse(tool_calls=[ToolCall(id="2", name="submit_findings", args=submit)]),
        )
        llm.add(
            "synthesizer",
            LLMResponse(
                parsed={
                    "answer": "NRTH would be {{m:whatif.conc.NRTH.pct}}.",
                    "suggested_questions": [],
                }
            ),
        )
        return
    if sid == "S6":
        llm.add(
            "router",
            LLMResponse(
                parsed={
                    "route": "out_of_scope",
                    "domains": [],
                    "reason": "crypto",
                    "confidence": 0.97,
                }
            ),
        )
        return
    if cid != "C004":
        script_full_review(llm, cid)
    if sid == "S2":
        llm.add("synthesizer", llm.queues["synthesizer"][-1])
        llm.queues["evaluator"].appendleft(LLMResponse(parsed=FAIL))


def main() -> None:
    settings = get_settings().model_copy(update={"run_mode": "record"})
    for sc in scenarios():
        s = scenario_settings(sc, settings)
        (s.path("cassettes") / f"{sc['id']}.jsonl").unlink(missing_ok=True)
        llm = ScriptedClient()
        script_scenario(llm, sc)
        state = RunState(
            run_id=f"scripted-{sc['id']}",
            client_id=sc["client_id"],
            request_text=sc["request_text"],
            preset=sc.get("preset"),
        )
        recorder = CassetteClient(s.path("cassettes") / f"{sc['id']}.jsonl", "record", llm)
        deps = make_deps(state.run_id, s, recorder, sc["id"])
        state = asyncio.run(run_pipeline(state, deps))
        if sc.get("approve") and state.status == "AWAITING_APPROVAL":
            apply_approval(state, ApprovalDecision(decision="approve"), s.path("runs"), deps.trace)
        if not sc.get("hidden"):
            write_replay(sc, state, deps.trace.events, s)
        print(f"{sc['id']:<12} {state.status:<20} calls={state.budget_snapshot['llm_calls']}")


if __name__ == "__main__":
    main()
