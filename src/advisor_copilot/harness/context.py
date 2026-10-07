"""Brief builders, per-agent client slices, and untrusted-data wrapping (03 §8)."""

import json
from dataclasses import dataclass

from advisor_copilot.config import Settings
from advisor_copilot.harness.injection import wrap
from advisor_copilot.models import Client, CrmNote, Finding, Flag, Metric, ToolResult
from advisor_copilot.tools.common import asset_classes_held

SLICES: dict[str, tuple[str, ...]] = {
    "portfolio": ("risk_profile", "time_horizon_years", "objectives"),
    "risk": ("risk_profile", "age", "time_horizon_years", "liquidity_needs"),
    "tax": ("tfsa_room_cad", "rrsp_room_cad", "objectives"),
    "market": (),
}
SEES_NOTES = {"portfolio", "tax", "synthesizer", "evaluator"}


@dataclass(frozen=True)
class AgentContext:
    client: Client
    notes: list[CrmNote]
    request_text: str


@dataclass(frozen=True)
class SynthContext:
    client: Client
    notes: list[CrmNote]
    request_text: str
    route: str
    findings: list[Finding]
    metrics: dict[str, Metric]
    flags: dict[str, Flag]

    @property
    def must_address(self) -> list[str]:
        return [f.finding_id for f in self.findings if f.severity != "info"]


@dataclass(frozen=True)
class Feedback:
    source: str
    items: list[str]
    draft: dict


def client_slice(client: Client, agent: str) -> dict:
    out = {f: getattr(client, f) for f in SLICES.get(agent, ())}
    if agent == "tax":
        out["account_types"] = [a.type for a in client.accounts]
    if agent == "market":
        out["asset_classes_held"] = asset_classes_held(client)
    return out


def notes_block(notes: list[CrmNote]) -> str:
    inner = "\n".join(wrap(n.text, "crm_note", n.note_id, n.date.isoformat()) for n in notes)
    return f"<crm_notes>\n{inner}\n</crm_notes>"


def build_brief(agent: str, ctx: AgentContext) -> str:
    parts = [f"<client_profile>\n{json.dumps(client_slice(ctx.client, agent))}\n</client_profile>"]
    if agent in SEES_NOTES:
        parts.append(notes_block(ctx.notes))
    parts.append(wrap(ctx.request_text, "advisor_request", "request"))
    return "\n".join(parts)


def compact_result(r: ToolResult) -> dict:
    """Tool result as the model sees it: metrics with values, flags without prose."""
    return {
        "metrics": [
            {"key": m.key, "value": m.value, "unit": m.unit, "label": m.label} for m in r.metrics
        ],
        "flags": [
            {
                "flag_id": f.flag_id,
                "severity": f.severity,
                "rule": f.rule,
                "metric_refs": f.metric_refs,
            }
            for f in r.flags
        ],
        "data": r.data,
    }


def render_tool_results(results: dict[str, ToolResult]) -> str:
    body = json.dumps({name: compact_result(r) for name, r in results.items()})
    return f"<tool_results>\n{body}\n</tool_results>"


def load_prompt(name: str, settings: Settings) -> str:
    return (settings.path("prompts") / name).read_text(encoding="utf-8")


def profile_summary(client: Client) -> dict:
    out = client.model_dump(mode="json", exclude={"accounts"})
    out["account_types"] = [a.type for a in client.accounts]
    return out


def synth_inputs(ctx: SynthContext) -> list[str]:
    """Blocks shared by the synthesizer and evaluator prompts (03 §8.3, §8.4)."""
    metrics = {
        k: {"label": m.label, "value": m.value, "unit": m.unit} for k, m in ctx.metrics.items()
    }
    return [
        f"<client_profile>\n{json.dumps(profile_summary(ctx.client))}\n</client_profile>",
        f"<route>{ctx.route}</route>",
        wrap(ctx.request_text, "advisor_request", "request"),
        notes_block(ctx.notes),
        f"<findings>\n{json.dumps([f.model_dump() for f in ctx.findings])}\n</findings>",
        f"<metric_dictionary>\n{json.dumps(metrics)}\n</metric_dictionary>",
        f"<must_address>{json.dumps(ctx.must_address)}</must_address>",
    ]
