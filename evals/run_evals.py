"""Eval runner: `--tier 1,2` (offline, CI gate) or `--tier 3 --k 3` (live capability report)."""

import argparse
import asyncio
import datetime as dt
import json
import statistics
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from advisor_copilot.agents.evaluator import evaluate, passes  # noqa: E402
from advisor_copilot.config import get_settings  # noqa: E402
from advisor_copilot.data_access import get_client, get_notes  # noqa: E402
from advisor_copilot.harness.chat import reply_text  # noqa: E402
from advisor_copilot.harness.context import SynthContext  # noqa: E402
from advisor_copilot.harness.gates import code_finding  # noqa: E402
from advisor_copilot.harness.orchestrator import make_deps, run_pipeline  # noqa: E402
from advisor_copilot.harness.state import RunState  # noqa: E402
from advisor_copilot.models import Recommendation  # noqa: E402
from advisor_copilot.replay import scenario_settings, scenarios  # noqa: E402
from advisor_copilot.tools.registry import run_all_for_client  # noqa: E402

REPORTS = ROOT / "evals" / "reports"


def metrics_of(state: RunState, events: list) -> dict:
    done = [e.payload for e in events if e.type == "llm_call_finished"]
    return {
        "llm_calls": len(done),
        "tokens_in": sum(p["tokens_in"] for p in done),
        "tokens_out": sum(p["tokens_out"] for p in done),
        "wall_ms": state.budget_snapshot.get("wall_ms", 0),
        "retries": sum(e.type == "llm_retry" for e in events),
        "revision_count": state.revision_count,
        "gate_violations_by_check": sorted(
            {v.split()[0] for g in state.gate_results for v in g.violations}
        ),
        "analyst_status": {d: r.status for d, r in state.analyst_reports.items()},
        "final_status": state.status,
    }


def check(expect: dict, state: RunState, events: list) -> list[str]:
    """Outcome assertions (not path assertions); returns human-readable failures."""
    fails: list[str] = []
    draft = state.drafts[-1] if state.drafts else None
    actions = draft.actions if draft else []
    texts = " ".join(f"{a.target} {a.description} {a.rationale}" for a in actions)
    flags = state.flags
    calls = sum(e.type == "llm_call_finished" for e in events)
    g5 = [g for g in state.gate_results if g.gate == "G5"]
    finding_flags = {
        f.finding_id: f.flag_refs for r in state.analyst_reports.values() for f in r.findings
    }

    def refs_flag(ids: list[str], flag: str) -> bool:
        return any(flag in finding_flags.get(i, []) for i in ids)

    def matches(a, pattern: dict) -> bool:  # noqa: ANN001
        return all(getattr(a, k) == v for k, v in pattern.items())

    for key, want in expect.items():
        ok = True
        if key == "status":
            ok = state.status == want
        elif key == "route":
            ok = state.route is not None and state.route.route == want
        elif key == "domains":
            ok = state.route is not None and state.route.domains == want
        elif key == "analysts_run":
            ok = set(state.analyst_reports) == set(want)
        elif key == "flags_present":
            ok = all(f in flags for f in want)
        elif key == "flags_absent":
            ok = not any(f in flags for f in want)
        elif key == "flags_count":
            ok = len(flags) == want
        elif key == "flag_severity":
            ok = all(f in flags and flags[f].severity == sev for f, sev in want.items())
        elif key == "action_types_any_of":
            ok = all(any(a.type in group for a in actions) for group in want)
        elif key == "forbidden_actions":
            ok = not any(matches(a, p) for a in actions for p in want)
        elif key == "addressed_any_of":
            deferred = draft.deferred if draft else []
            ok = any(matches(a, want["action"]) for a in actions) or any(
                refs_flag([d.finding_id], want["deferred_flag"]) for d in deferred
            )
        elif key == "gates_final_pass":
            ok = bool(g5) and g5[-1].passed == want
        elif key == "max_llm_calls":
            ok = calls <= want
        elif key == "llm_calls":
            ok = calls == want
        elif key == "events":
            ok = all(
                any(
                    e.type == w["type"]
                    and all(e.payload.get(k) == v for k, v in w.items() if k != "type")
                    for e in events
                )
                for w in want
            )
        elif key == "purposes_absent":
            ok = not any(
                e.type == "llm_call_finished" and e.payload["purpose"] in want for e in events
            )
        elif key == "actions_empty_or_no_action":
            ok = (not actions or (len(actions) == 1 and actions[0].type == "no_action")) == want
        elif key == "no_action_text_contains":
            ok = not any(w in texts for w in want)
        elif key == "final_summary_contains":
            ok = state.final is not None and want in state.final.recommendation.summary
        elif key == "metrics_present":
            ok = all(k in state.metrics for k in want)
        elif key == "mode":
            ok = state.mode == want
        elif key == "answer_contains":
            ok = want in reply_text(state)
        elif key == "message_contains":
            ok = bool(state.message) and want in state.message
        else:
            ok, want = False, f"unknown expectation {key!r}"
        if not ok:
            fails.append(f"{key}: expected {want!r}")
    return fails


async def run_case(case: dict, run_mode: str) -> tuple[list[str], dict]:
    sc = next(s for s in scenarios() if s["id"] == case["scenario"])
    settings = scenario_settings(sc, get_settings().model_copy(update={"run_mode": run_mode}))
    run_id = f"eval-{case['id']}-{dt.datetime.now(dt.UTC):%H%M%S%f}"
    state = RunState(
        run_id=run_id,
        client_id=sc["client_id"],
        request_text=sc["request_text"],
        preset=sc.get("preset"),
    )
    deps = make_deps(run_id, settings, None, sc["id"])
    state = await run_pipeline(state, deps)
    return check(case["expect"], state, deps.trace.events), metrics_of(state, deps.trace.events)


def run_pytest(node: str) -> list[str]:
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--tb=line", "-p", "no:cacheprovider", node],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return [] if r.returncode == 0 else [r.stdout.strip().splitlines()[-1]]


def tier_1() -> tuple[int, int]:
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    last = r.stdout.strip().splitlines()[-1]
    passed = int(next((w for w in last.split() if w.isdigit()), 0))
    return passed, r.returncode


def tier_2() -> list[dict]:
    rows = []
    for case in yaml.safe_load((ROOT / "evals" / "golden_cases.yaml").read_text()):
        if "pytest" in case:
            fails, metrics = run_pytest(case["pytest"]), {}
        else:
            fails, metrics = asyncio.run(run_case(case, "replay"))
        rows.append({"id": case["id"], "title": case["title"], "fails": fails, **metrics})
    return rows


def write_report(path: Path, title: str, rows: list[dict], header: str) -> None:
    cols = [
        "id",
        "result",
        "llm_calls",
        "tokens_in",
        "tokens_out",
        "wall_ms",
        "retries",
        "revision_count",
        "final_status",
        "notes",
    ]
    lines = [f"# {title}", "", header, "", "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        notes = "; ".join(r["fails"]) or ", ".join(r.get("gate_violations_by_check", [])) or ""
        vals = (
            [r["id"], "PASS" if not r["fails"] else "FAIL"]
            + [str(r.get(c, "")) for c in cols[2:-1]]
            + [notes]
        )
        lines.append("| " + " | ".join(vals) + " |")
    ran = [r for r in rows if "llm_calls" in r]
    if ran:
        agg = [
            f"{sum(r[c] for r in ran)}"
            for c in [
                "llm_calls",
                "tokens_in",
                "tokens_out",
                "wall_ms",
                "retries",
                "revision_count",
            ]
        ]
        lines.append(
            "| **total** | "
            + f"{sum(not r['fails'] for r in rows)}/{len(rows)}"
            + " | "
            + " | ".join(agg)
            + " |  |  |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def calibration_ctx(client_id: str) -> SynthContext:
    results = run_all_for_client(client_id)
    findings, n = [], {}
    for r in results:
        for f in r.flags:
            prefix = {
                "get_positions": "PORT",
                "compute_allocation": "PORT",
                "compute_drift": "PORT",
                "check_asset_location": "TAX",
                "get_contribution_room": "TAX",
                "get_market_snapshot": "MKT",
            }.get(r.tool, "RISK")
            n[prefix] = n.get(prefix, 0) + 1
            findings.append(
                code_finding(f, r.tool).model_copy(update={"finding_id": f"{prefix}-{n[prefix]}"})
            )
    return SynthContext(
        get_client(client_id),
        get_notes(client_id),
        "Prepare annual review",
        "full_review",
        findings,
        {m.key: m for r in results for m in r.metrics},
        {f.flag_id: f for r in results for f in r.flags},
    )


async def calibrate(deps_factory) -> tuple[int, int, list[str]]:  # noqa: ANN001
    labels = yaml.safe_load((ROOT / "evals" / "calibration" / "labels.yaml").read_text())
    agree, total, notes = 0, 0, []
    for path in sorted((ROOT / "evals" / "calibration").glob("*.json")):
        doc = json.loads(path.read_text())
        label = labels.get(path.stem)
        if label not in ("pass", "fail"):
            notes.append(f"{path.stem}: label TODO")
            continue
        ctx = calibration_ctx(doc["client_id"])
        verdict = await evaluate(
            Recommendation.model_validate(doc["draft"]), ctx, deps_factory(f"cal-{path.stem}")
        )
        judged = "pass" if passes(verdict, get_settings().loop) else "fail"
        total += 1
        agree += judged == label
        notes.append(f"{path.stem}: judge {judged}, label {label}")
    return agree, total, notes


async def tier_3(k: int) -> None:
    settings = get_settings().model_copy(update={"run_mode": "live"})
    factory = lambda run_id: make_deps(run_id, settings)  # noqa: E731
    agree, total, notes = await calibrate(factory)
    rows = []
    for sc in scenarios():
        if sc.get("hidden"):
            continue
        outcomes, scores, calls, walls, revs, retries = [], [], [], [], [], 0
        for i in range(k):
            run_id = f"live-{sc['id']}-{i}-{dt.datetime.now(dt.UTC):%H%M%S}"
            state = RunState(
                run_id=run_id,
                client_id=sc["client_id"],
                request_text=sc["request_text"],
                preset=sc.get("preset"),
            )
            deps = make_deps(run_id, scenario_settings(sc, settings))
            state = await run_pipeline(state, deps)
            m = metrics_of(state, deps.trace.events)
            calls.append(m["llm_calls"])
            walls.append(m["wall_ms"])
            revs.append(m["revision_count"])
            retries += m["retries"]
            ok = state.status in ("AWAITING_APPROVAL", "BLOCKED", "COMPLETED")
            if state.final and state.drafts:
                findings = [f for r in state.analyst_reports.values() for f in r.findings]
                ctx = SynthContext(
                    get_client(sc["client_id"]),
                    get_notes(sc["client_id"]),
                    sc["request_text"],
                    state.route.route if state.route else "full_review",
                    findings,
                    state.metrics,
                    state.flags,
                )
                verdict = await evaluate(state.drafts[-1], ctx, factory(f"judge-{run_id}"))
                ok = ok and passes(verdict, settings.loop)
                scores.append(statistics.mean(verdict.scores.values()))
            outcomes.append(ok)
        rows.append(
            {
                "id": sc["id"],
                "title": sc["title"],
                "fails": [] if all(outcomes) else [f"pass^{k} failed: {outcomes}"],
                "llm_calls": sum(calls),
                "tokens_in": 0,
                "tokens_out": 0,
                "wall_ms": int(statistics.median(walls)),
                "retries": retries,
                "revision_count": sum(revs),
                "final_status": f"judge mean {statistics.mean(scores):.2f}" if scores else "n/a",
            }
        )
    header = f"Live tier 3, k={k}. Judge calibration: {agree}/{total} agree ({'; '.join(notes)})."
    write_report(
        REPORTS / f"live_{dt.date.today():%Y-%m-%d}.md", "Live capability report", rows, header
    )
    print(header)
    for r in rows:
        print(
            f"{r['id']} {'PASS' if not r['fails'] else 'FAIL'} calls={r['llm_calls']} "
            f"p50_wall={r['wall_ms']} {r['final_status']}"
        )


def human() -> None:
    """Judge-vs-human agreement on the recorded recommendations scored in evals/human/scores.csv."""
    import csv

    checks = [
        "suitability_respected",
        "critical_addressed",
        "faithful_to_findings",
        "client_specific",
        "untrusted_ignored",
    ]
    rows = [
        r
        for r in csv.DictReader((ROOT / "evals" / "human" / "scores.csv").open())
        if r["kind"] == "recommendation" and r["pass"].strip()
    ]
    lines, agree, same = [], 0, {c: 0 for c in checks}
    for r in rows:
        verdict = json.loads((ROOT / "replays" / f"{r['scenario']}.json").read_text())[
            "final_state"
        ]
        judge = verdict["eval_verdicts"][-1] if verdict["eval_verdicts"] else None
        if not judge:
            continue
        judged = passes_raw(judge, get_settings().loop)
        human_pass = r["pass"].strip().lower() in ("yes", "true", "pass", "1")
        agree += judged == human_pass
        for c in checks:
            same[c] += judge["checks"].get(c) == (r[c].strip().lower() in ("yes", "true", "1"))
        lines.append(
            f"- {r['case_id']} ({r['scenario']}): human {human_pass}, judge {judged}. {r['notes']}"
        )
    n = len(lines)
    head = f"Judge-vs-human agreement on {n} recommendation(s): {agree}/{n} pass decisions"
    per = ", ".join(f"{c} {same[c]}/{n}" for c in checks) if n else "no scored cases yet"
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "human.md").write_text("\n".join([f"# {head}", "", per, "", *lines]) + "\n")
    print(head + "\n" + per)


def passes_raw(v: dict, cfg) -> bool:  # noqa: ANN001
    """The code's pass rule on a stored verdict: all checks true, min and mean score thresholds."""
    scores = list(v["scores"].values())
    return (
        all(v["checks"].values())
        and min(scores) >= cfg.pass_min_score
        and statistics.mean(scores) >= cfg.pass_mean_score
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default="1,2")
    ap.add_argument("--k", type=int, default=3)
    args = ap.parse_args()
    tiers = {t.strip() for t in args.tier.split(",")}
    rc = 0
    if "human" in tiers:
        human()
        return 0
    if "3" in tiers:
        asyncio.run(tier_3(args.k))
        return 0
    header = []
    if "1" in tiers:
        passed, code = tier_1()
        header.append(f"Tier 1 unit tests: {passed} passed" + ("" if code == 0 else " (FAILURES)"))
        rc |= code
    if "2" in tiers:
        rows = tier_2()
        header.append(f"Tier 2 golden cases: {sum(not r['fails'] for r in rows)}/{len(rows)} pass")
        write_report(
            REPORTS / "latest.md",
            "Regression evals (tiers 1 and 2)",
            rows,
            f"_{dt.datetime.now(dt.UTC):%Y-%m-%d %H:%M} UTC_ · " + " · ".join(header),
        )
        for r in rows:
            print(
                f"{r['id']:<4} {'PASS' if not r['fails'] else 'FAIL'}  {r['title']}"
                + (f"  -> {'; '.join(r['fails'])}" if r["fails"] else "")
            )
        rc |= any(r["fails"] for r in rows)
    print(" · ".join(header))
    return int(rc)


if __name__ == "__main__":
    raise SystemExit(main())
