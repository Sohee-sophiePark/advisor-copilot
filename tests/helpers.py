"""Small helpers shared by tests."""

from advisor_copilot.data_access import get_client, get_notes
from advisor_copilot.harness.context import SynthContext
from advisor_copilot.models import Finding, ToolResult
from advisor_copilot.tools.registry import run_all_for_client


def metrics(result: ToolResult) -> dict[str, float]:
    return {m.key: m.value for m in result.metrics}


def flags(result: ToolResult) -> dict[str, str]:
    return {f.flag_id: f.severity for f in result.flags}


def synth_ctx(client_id: str, findings: list[Finding], route: str = "full_review") -> SynthContext:
    """Context with real metrics/flags from the tools and caller-supplied findings."""
    results = run_all_for_client(client_id)
    return SynthContext(
        get_client(client_id),
        get_notes(client_id),
        "Prepare annual review",
        route,
        findings,
        {m.key: m for r in results for m in r.metrics},
        {f.flag_id: f for r in results for f in r.flags},
    )
