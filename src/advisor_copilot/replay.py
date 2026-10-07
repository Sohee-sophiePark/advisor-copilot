"""Scenario registry and recorded-run files: `replays/<scenario>.json` (03 §14)."""

import datetime as dt
import json
from pathlib import Path

import yaml

from advisor_copilot.config import ROOT, Settings
from advisor_copilot.harness.state import RunState
from advisor_copilot.harness.trace import TraceEvent

SCENARIOS_FILE = ROOT / "evals" / "scenarios.yaml"


def scenarios() -> list[dict]:
    return yaml.safe_load(SCENARIOS_FILE.read_text(encoding="utf-8"))


def scenario_settings(sc: dict, settings: Settings) -> Settings:
    """Settings with the scenario's `settings` overrides merged in (one level deep per section)."""
    raw = settings.model_dump()
    for section, values in sc.get("settings", {}).items():
        raw[section] = {**raw[section], **values}
    return Settings.model_validate(raw)


def scenario_for(client_id: str, request_text: str, preset: str | None) -> dict | None:
    for sc in scenarios():
        if (
            sc["client_id"] == client_id
            and sc.get("preset") == preset
            and sc["request_text"] == request_text
        ):
            return sc
    return None


def write_replay(sc: dict, state: RunState, events: list[TraceEvent], settings: Settings) -> Path:
    path = settings.path("replays") / f"{sc['id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    outbox = settings.path("runs") / state.run_id / "crm_outbox.json"
    doc = {
        "scenario_id": sc["id"],
        "title": sc["title"],
        "client_id": sc["client_id"],
        "request_text": sc["request_text"],
        "preset": sc.get("preset"),
        "recorded_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "model_ids": settings.models.model_dump(),
        "events": [e.model_dump(mode="json") for e in events],
        "final_state": state.model_dump(mode="json"),
        "outbox": json.loads(outbox.read_text()) if outbox.exists() else None,
    }
    path.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    return path


def load_replay(scenario_id: str, settings: Settings) -> dict:
    return json.loads(
        (settings.path("replays") / f"{scenario_id}.json").read_text(encoding="utf-8")
    )
