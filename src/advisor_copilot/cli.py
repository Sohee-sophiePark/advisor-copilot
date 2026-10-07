"""Command-line entry point: `advisor-copilot <command>`."""

import argparse
import asyncio
import json
import sys
from collections.abc import Callable, Sequence

COMMANDS: dict[str, str] = {
    "run": "run the pipeline for one client",
    "approve": "record an approve or reject decision for a run",
    "resume": "resume a run from its last checkpoint",
    "record": "run every demo scenario live and write cassettes/ and replays/",
    "replay": "print the recorded events of a scenario",
    "eval": "run the eval tiers (M8)",
    "tools": "print metrics and flags for a client with no LLM call",
    "smoke": "list flash models, one structured-output call, one function-call round trip (live)",
    "port": "print the first free API port in the configured range",
    "seed": "rebuild the local SQLite database from the synthetic JSON",
    "export": "write the data the public replay build shows to a JSON file",
    "fetch": "laptop only: fetch free market data (BoC, SEC EDGAR, Tiingo) under daily caps",
}


def _print_state(state) -> None:  # noqa: ANN001
    print(
        f"run {state.run_id}: {state.status}  calls={state.budget_snapshot.get('llm_calls')} "
        f"tokens={state.budget_snapshot.get('tokens')} "
        f"wall_ms={state.budget_snapshot.get('wall_ms')}"
    )
    if state.message:
        print(f"  {state.message}")
    if state.final:
        rec = state.final.recommendation
        print(f"  {rec.headline}\n  {rec.summary}")
        for a in rec.actions:
            print(f"  - [{a.priority}] {a.type} {a.target} {a.direction}: {a.description}")
    if state.error:
        print(f"  error: {state.error}", file=sys.stderr)


def _cmd_run(args: argparse.Namespace) -> int:
    from advisor_copilot.config import get_settings
    from advisor_copilot.harness.orchestrator import run_pipeline, start_run
    from advisor_copilot.replay import scenario_for

    settings = get_settings()
    if args.mode:
        settings = settings.model_copy(update={"run_mode": args.mode})
    sc = scenario_for(args.client_id, args.request, args.preset)
    scenario = args.scenario or (sc["id"] if sc else None)

    async def go() -> object:
        state, deps = await start_run(args.client_id, args.request, args.preset, settings, scenario)
        return await run_pipeline(state, deps)

    state = asyncio.run(go())
    _print_state(state)
    return 0 if state.status not in ("FAILED",) else 1


def _cmd_approve(args: argparse.Namespace) -> int:
    from advisor_copilot.actions import apply_approval
    from advisor_copilot.config import get_settings
    from advisor_copilot.harness.state import load_state
    from advisor_copilot.harness.trace import TraceBus
    from advisor_copilot.models import ApprovalDecision

    runs = get_settings().path("runs")
    state = load_state(args.run_id, runs)
    decision = ApprovalDecision(
        decision="reject" if args.reject else "approve", advisor_note=args.note
    )
    outbox = apply_approval(
        state, decision, runs, TraceBus(args.run_id, runs / args.run_id / "trace.jsonl")
    )
    print(json.dumps(outbox, indent=2) if outbox else f"run {args.run_id}: rejected")
    return 0


def _cmd_resume(args: argparse.Namespace) -> int:
    from advisor_copilot.config import get_settings
    from advisor_copilot.harness.orchestrator import make_deps, run_pipeline
    from advisor_copilot.harness.state import load_state
    from advisor_copilot.replay import scenario_for

    settings = get_settings()
    state = load_state(args.run_id, settings.path("runs"))
    sc = scenario_for(state.client_id, state.request_text, state.preset)

    async def go() -> object:
        deps = make_deps(state.run_id, settings, scenario=sc["id"] if sc else None)
        return await run_pipeline(state, deps)

    state = asyncio.run(go())
    _print_state(state)
    return 0


def _cmd_record(args: argparse.Namespace) -> int:
    from advisor_copilot.actions import apply_approval
    from advisor_copilot.config import get_settings
    from advisor_copilot.harness.orchestrator import run_pipeline, start_run
    from advisor_copilot.models import ApprovalDecision
    from advisor_copilot.replay import scenario_settings, scenarios, write_replay

    if get_settings().data_source != "fictional":
        raise SystemExit("record uses the illustrative data only: unset DATA_SOURCE")
    settings = get_settings().model_copy(update={"run_mode": "record"})
    for sc in scenarios():
        if args.scenario and sc["id"] != args.scenario:
            continue
        (settings.path("cassettes") / f"{sc['id']}.jsonl").unlink(missing_ok=True)

        async def go(sc: dict = sc) -> tuple:
            state, deps = await start_run(
                sc["client_id"],
                sc["request_text"],
                sc.get("preset"),
                scenario_settings(sc, settings),
                sc["id"],
            )
            state = await run_pipeline(state, deps)
            if sc.get("approve") and state.status == "AWAITING_APPROVAL":
                apply_approval(
                    state, ApprovalDecision(decision="approve"), settings.path("runs"), deps.trace
                )
            return state, deps

        state, deps = asyncio.run(go())
        path = (
            write_replay(sc, state, deps.trace.events, settings) if not sc.get("hidden") else None
        )
        print(
            f"{sc['id']} {state.status:<22} calls={state.budget_snapshot['llm_calls']:<3} "
            f"tokens={state.budget_snapshot['tokens']:<6} "
            f"wall_ms={state.budget_snapshot['wall_ms']:<6} -> "
            f"{path.name if path else 'cassette only'}"
        )
    return 0


def _cmd_replay(args: argparse.Namespace) -> int:
    from advisor_copilot.config import get_settings
    from advisor_copilot.replay import load_replay

    doc = load_replay(args.scenario, get_settings())
    print(f"{doc['scenario_id']} {doc['title']} ({doc['client_id']}) recorded {doc['recorded_at']}")
    for e in doc["events"]:
        print(
            f"{e['t_ms']:>7} ms  {e['agent']:<12} {e['type']:<20} {json.dumps(e['payload'])[:100]}"
        )
    print(f"final status: {doc['final_state']['status']}")
    return 0


def _cmd_tools(args: argparse.Namespace) -> int:
    from advisor_copilot.tools.registry import run_all_for_client

    results = run_all_for_client(args.client_id)
    print(f"{'metric key':<34}{'value':>14}  {'unit':<6}source")
    for r in results:
        for m in r.metrics:
            print(f"{m.key:<34}{m.value:>14,.2f}  {m.unit:<6}{m.source_tool}")
    flags = [f for r in results for f in r.flags]
    print("\nflags:" if flags else "\nflags: (none)")
    for f in flags:
        print(f"  {f.flag_id:<24}{f.severity:<10}{f.message}")
    return 0


def _cmd_smoke(args: argparse.Namespace) -> int:
    from pydantic import BaseModel

    from advisor_copilot.config import get_settings
    from advisor_copilot.llm.base import LLMRequest, Message, ToolDecl
    from advisor_copilot.llm.gemini import GeminiClient

    class Answer(BaseModel):
        city: str
        country: str

    async def run() -> None:
        s, client = get_settings(), GeminiClient()
        print(
            "flash models available:",
            *[n for n in await client.list_models() if "flash" in n],
            sep="\n  ",
        )
        r1 = await client.generate(
            LLMRequest(
                model=s.models.router,
                system="Answer in JSON.",
                messages=[Message(role="user", text="What is the capital of Canada?")],
                response_schema=Answer,
                purpose="smoke:schema",
            )
        )
        print(
            "structured:",
            Answer.model_validate(r1.parsed),
            f"[{r1.tokens_in}/{r1.tokens_out} tok, {r1.latency_ms} ms]",
        )
        decl = ToolDecl(
            name="get_time",
            description="Current local time in a city",
            parameters={
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        )
        req = LLMRequest(
            model=s.models.analyst,
            system="Use the tool, then answer in one sentence.",
            messages=[Message(role="user", text="What time is it in Halifax?")],
            tools=[decl],
            tool_mode="ANY",
            purpose="smoke:tool",
        )
        r2 = await client.generate(req)
        call = r2.tool_calls[0]
        print("tool call:", call.name, call.args)
        req.messages += [
            Message(role="model", tool_calls=r2.tool_calls),
            Message(
                role="tool",
                tool_name=call.name,
                tool_call_id=call.id,
                tool_result={"time": "09:41"},
            ),
        ]
        req.tool_mode = "AUTO"
        print("final:", (await client.generate(req)).text)

    asyncio.run(run())
    return 0


def _cmd_port(args: argparse.Namespace) -> int:
    import socket

    from advisor_copilot.config import get_settings

    api = get_settings().api
    for port in range(api.port_min, api.port_max + 1):
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                print(port)
                return 0
    print(f"no free port in {api.port_min}-{api.port_max}", file=sys.stderr)
    return 1


def _cmd_seed(args: argparse.Namespace) -> int:
    from advisor_copilot import db
    from advisor_copilot.config import get_settings
    from advisor_copilot.data_access import read_json

    s = get_settings()
    raw = read_json(s.path("data"))
    db.seed(raw, s.path("data"), s.path("db"))
    print(f"seeded {s.paths.db}: {len(raw['clients'])} clients, {len(raw['notes'])} notes")
    return 0


def _cmd_fetch(args: argparse.Namespace) -> int:
    import os

    import httpx

    from advisor_copilot import fetch
    from advisor_copilot.config import get_settings
    from advisor_copilot.data_access import read_json
    from advisor_copilot.db import Store, seed

    s = get_settings()
    with httpx.Client(timeout=30) as http:
        for source, result in fetch.run(s, Store(s.path("db")), http, os.environ).items():
            print(f"{source:<7} {result}")
    seed(read_json(s.path("data")), s.path("data"), s.path("db"))  # facts file may have changed
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    from pathlib import Path

    from advisor_copilot.api.routes import export_static
    from advisor_copilot.config import get_settings

    if get_settings().data_source != "fictional":
        raise SystemExit("export is public: real prices are never published, unset DATA_SOURCE")
    out = Path(args.path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(export_static(get_settings()), encoding="utf-8")
    print(f"wrote {args.path}")
    return 0


HANDLERS: dict[str, Callable[[argparse.Namespace], int]] = {
    "run": _cmd_run,
    "approve": _cmd_approve,
    "resume": _cmd_resume,
    "record": _cmd_record,
    "replay": _cmd_replay,
    "tools": _cmd_tools,
    "smoke": _cmd_smoke,
    "port": _cmd_port,
    "seed": _cmd_seed,
    "export": _cmd_export,
    "fetch": _cmd_fetch,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="advisor-copilot", description="Advisor Copilot CLI")
    sub = parser.add_subparsers(dest="command", metavar="{" + " | ".join(COMMANDS) + "}")
    p = {name: sub.add_parser(name, help=help_text) for name, help_text in COMMANDS.items()}
    p["run"].add_argument("client_id")
    p["run"].add_argument("--request", default="")
    p["run"].add_argument("--preset", choices=["annual_review"])
    p["run"].add_argument("--mode", choices=["live", "record", "replay"])
    p["run"].add_argument("--scenario", help="cassette name for record/replay, e.g. S1")
    p["approve"].add_argument("run_id")
    p["approve"].add_argument("--reject", action="store_true")
    p["approve"].add_argument("--note", default="")
    p["resume"].add_argument("run_id")
    p["record"].add_argument("--scenario", help="record one scenario only")
    p["replay"].add_argument("scenario")
    p["tools"].add_argument("client_id", help="client id, e.g. C002")
    p["export"].add_argument("path", help="output file, e.g. web/public/static-data.json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    handler = HANDLERS.get(args.command)
    if handler is None:
        print(f"{args.command}: not implemented yet ({COMMANDS[args.command]})", file=sys.stderr)
        return 2
    return handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
