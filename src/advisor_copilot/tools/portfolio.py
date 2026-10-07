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
                c.k_target(ac),
                targets[ac],
                "pct",
                f"{c.ASSET_LABEL[ac]} target ({client.risk_profile})",
                tool,
            )
            for ac in ASSET_CLASSES
        ]
    data = {
        "risk_profile": client.risk_profile,
        "allocation_pct": {ac: round(v, 2) for ac, v in alloc.items()},
        "target_pct": targets,
    }
    return c.tool_result(tool, metrics, data=data)


def compute_drift(client_id: "str | Client", args: NoArgs | None = None) -> ToolResult:
    client = c.resolve(client_id)
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
        metrics.append(c.metric(c.k_drift(ac), d, "pp", f"{c.ASSET_LABEL[ac]} vs target", tool))
        if abs(d) > tol:
            severity = "critical" if abs(d) > critical_at else "warning"
            flags.append(
                c.flag(
                    f"FLAG-DRIFT-{ac}",
                    "DRIFT_BEYOND_TOLERANCE",
                    severity,
                    [c.k_drift(ac), c.K_DRIFT_TOL],
                    f"{c.ASSET_LABEL[ac]} is {abs(d):.1f} points {'above' if d > 0 else 'below'} "
                    f"target (tolerance {tol:.0f})",
                )
            )
    return c.tool_result(tool, metrics, flags, data={"breaches": [f.flag_id for f in flags]})


def check_goals(client_id: str, args: NoArgs | None = None) -> ToolResult:
    """Required annual return per survey goal vs the model expected return; no contributions."""
    from advisor_copilot.tools.risk import expected_return, target_weights

    client = get_client(client_id)
    tool = "check_goals"
    if client.risk_profile is None or not client.goals:
        return c.tool_result(tool, data={"skipped": "no risk profile or no goals on file"})
    as_of = get_settings().rules.as_of
    total, _ = allocation(client)
    model = expected_return(target_weights(client.risk_profile))
    metrics: list[Metric] = [
        c.metric(c.K_GOAL_MODEL_RETURN, model, "pct", "Model-portfolio expected return", tool)
    ]
    flags: list[Flag] = []
    for g in client.goals:
        years = g.target_year - as_of.year
        if years <= 0 or total <= 0:
            continue
        required = 100 * ((g.target_cad / total) ** (1 / years) - 1)
        metrics.append(
            c.metric(c.k_goal(g.goal_id), required, "pct", f"Return needed for {g.name}", tool)
        )
        if required > model:
            flags.append(
                c.flag(
                    f"FLAG-GOAL-{g.goal_id}",
                    "GOAL_NEEDS_MORE_RETURN_THAN_PROFILE",
                    "warning",
                    [c.k_goal(g.goal_id), c.K_GOAL_MODEL_RETURN],
                    f"{g.name} needs {required:.1f}% a year; "
                    f"the {client.risk_profile} model expects {model:.1f}%",
                )
            )
    goals = [g.model_dump() for g in client.goals]
    return c.tool_result(tool, metrics, flags, data={"goals": goals, "as_of": as_of.isoformat()})
