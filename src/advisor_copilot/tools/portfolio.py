"""Portfolio tools: get_positions, compute_allocation, compute_drift."""

from advisor_copilot.config import get_settings
from advisor_copilot.data_access import get_client, get_targets
from advisor_copilot.models import ASSET_CLASSES, AssetClass, Client, Flag, Metric, ToolResult
from advisor_copilot.tools import common as c
from advisor_copilot.tools.common import NoArgs


def account_values(client: Client) -> dict[str, float]:
    """Market value per account type, in order of first appearance."""
    out: dict[str, float] = {}
    for p in c.positions(client):
        out[p.account_type] = out.get(p.account_type, 0.0) + p.market_value
    return out


def allocation(client: Client) -> tuple[float, dict[AssetClass, float]]:
    """Total market value and allocation % per asset class, full precision."""
    pos = c.positions(client)
    total = c.total_value(pos)
    by_class: dict[AssetClass, float] = {ac: 0.0 for ac in ASSET_CLASSES}
    for p in pos:
        by_class[p.instrument.asset_class] += p.market_value
    return total, {ac: (100.0 * v / total if total else 0.0) for ac, v in by_class.items()}


def get_positions(client_id: str, args: NoArgs | None = None) -> ToolResult:
    client = get_client(client_id)
    tool = "get_positions"
    metrics = [
        c.metric(c.k_acct(t), v, "cad", f"{t} account value", tool)
        for t, v in account_values(client).items()
    ]
    rows = [
        {
            "account_type": p.account_type,
            "ticker": p.ticker,
            "units": p.units,
            "market_value_cad": round(p.market_value, 2),
        }
        for p in c.positions(client)
    ]
    return c.tool_result(tool, metrics, data={"positions": rows})


def compute_allocation(client_id: str, args: NoArgs | None = None) -> ToolResult:
    client = get_client(client_id)
    tool = "compute_allocation"
    total, alloc = allocation(client)
    metrics: list[Metric] = [c.metric(c.K_TOTAL, total, "cad", "Total portfolio value", tool)]
    metrics += [
        c.metric(c.k_alloc(ac), v, "pct", f"{ac} allocation", tool) for ac, v in alloc.items()
    ]
    targets = get_targets(client.risk_profile) if client.risk_profile else None
    if targets:
        metrics += [
            c.metric(
                c.k_target(ac), targets[ac], "pct", f"{ac} target ({client.risk_profile})", tool
            )
            for ac in ASSET_CLASSES
        ]
    data = {
        "risk_profile": client.risk_profile,
        "allocation_pct": {ac: round(v, 2) for ac, v in alloc.items()},
        "target_pct": targets,
    }
    return c.tool_result(tool, metrics, data=data)


def compute_drift(client_id: str, args: NoArgs | None = None) -> ToolResult:
    client = get_client(client_id)
    tool = "compute_drift"
    if client.risk_profile is None:
        return c.tool_result(
            tool, data={"skipped": "no risk profile on file; drift needs a target"}
        )
    rules = get_settings().rules
    tol = rules.drift_tolerance_pp
    critical_at = tol * rules.drift_critical_multiplier
    _, alloc = allocation(client)
    targets = get_targets(client.risk_profile)
    metrics: list[Metric] = [c.metric(c.K_DRIFT_TOL, tol, "pp", "Drift tolerance", tool)]
    flags: list[Flag] = []
    for ac in ASSET_CLASSES:
        d = alloc[ac] - targets[ac]
        metrics.append(c.metric(c.k_drift(ac), d, "pp", f"{ac} drift vs target", tool))
        if abs(d) > tol:
            severity = "critical" if abs(d) > critical_at else "warning"
            flags.append(
                c.flag(
                    f"FLAG-DRIFT-{ac}",
                    "DRIFT_BEYOND_TOLERANCE",
                    severity,
                    [c.k_drift(ac), c.K_DRIFT_TOL],
                    f"{ac} is {abs(d):.1f} pp {'above' if d > 0 else 'below'} the "
                    f"{client.risk_profile} target (tolerance {tol:.1f} pp)",
                )
            )
    return c.tool_result(tool, metrics, flags, data={"breaches": [f.flag_id for f in flags]})
