"""Risk tools: compute_risk_metrics, run_stress_test, check_concentration."""

from typing import Literal

import numpy as np
from pydantic import BaseModel, Field

from advisor_copilot.config import get_settings
from advisor_copilot.data_access import get_client, get_cma, get_targets, get_vol_band_max
from advisor_copilot.models import (
    RISK_BUCKETS,
    Client,
    Flag,
    Metric,
    RiskBucket,
    RiskProfile,
    ToolResult,
)
from advisor_copilot.tools import common as c
from advisor_copilot.tools.common import NoArgs


class StressArgs(BaseModel):
    scenario: Literal["equity_bear"] = Field("equity_bear", description="Stress scenario to apply")


def bucket_weights(client: Client) -> dict[RiskBucket, float]:
    """Portfolio weight (fraction of total) per risk bucket."""
    pos = c.positions(client)
    total = c.total_value(pos)
    w: dict[RiskBucket, float] = {b: 0.0 for b in RISK_BUCKETS}
    for p in pos:
        w[p.instrument.risk_bucket] += p.market_value
    return {b: (v / total if total else 0.0) for b, v in w.items()}


def target_weights(profile: RiskProfile) -> dict[RiskBucket, float]:
    """Model-portfolio weights per risk bucket (single stocks have no target)."""
    targets = get_targets(profile)
    return {b: targets.get(b, 0.0) / 100.0 for b in RISK_BUCKETS}  # type: ignore[call-overload]


def correlation_matrix() -> np.ndarray:
    """ρ over RISK_BUCKETS; pairs absent from the fixture (all CASH pairs) are 0."""
    idx = {b: i for i, b in enumerate(RISK_BUCKETS)}
    rho = np.eye(len(RISK_BUCKETS))
    for corr in get_cma().correlations:
        rho[idx[corr.a], idx[corr.b]] = rho[idx[corr.b], idx[corr.a]] = corr.rho
    return rho


def covariance() -> np.ndarray:
    """Σ = diag(σ)·ρ·diag(σ) with σ as decimals."""
    cma = get_cma()
    sigma = np.diag([cma.buckets[b].volatility_pct / 100.0 for b in RISK_BUCKETS])
    return sigma @ correlation_matrix() @ sigma


def portfolio_volatility(weights: dict[RiskBucket, float]) -> float:
    """Annualised volatility in %, sqrt(wᵀΣw)."""
    w = np.array([weights[b] for b in RISK_BUCKETS])
    return float(np.sqrt(w @ covariance() @ w) * 100.0)


def expected_return(weights: dict[RiskBucket, float]) -> float:
    cma = get_cma()
    return sum(weights[b] * cma.buckets[b].expected_return_pct for b in RISK_BUCKETS)


def compute_risk_metrics(client_id: str, args: NoArgs | None = None) -> ToolResult:
    client = get_client(client_id)
    tool = "compute_risk_metrics"
    w = bucket_weights(client)
    vol = portfolio_volatility(w)
    metrics: list[Metric] = [
        c.metric(c.K_RISK_VOL, vol, "pct", "Portfolio volatility (annualised, illustrative)", tool),
        c.metric(
            c.K_RISK_RETURN, expected_return(w), "pct", "Expected return (illustrative)", tool
        ),
    ]
    flags: list[Flag] = []
    if client.risk_profile:
        band = get_vol_band_max(client.risk_profile)
        target_vol = portfolio_volatility(target_weights(client.risk_profile))
        metrics += [
            c.metric(c.K_RISK_BAND, band, "pct", f"Max volatility for {client.risk_profile}", tool),
            c.metric(c.K_RISK_TARGET_VOL, target_vol, "pct", "Model-portfolio volatility", tool),
        ]
        if vol > band:
            flags.append(
                c.flag(
                    "FLAG-SUIT-VOL",
                    "VOL_ABOVE_PROFILE_BAND",
                    "critical",
                    [c.K_RISK_VOL, c.K_RISK_BAND],
                    f"Portfolio volatility {vol:.1f}% exceeds the {client.risk_profile} "
                    f"band maximum of {band:.1f}%",
                )
            )
    data = {
        "risk_profile": client.risk_profile,
        "bucket_weights_pct": {b: round(100.0 * v, 2) for b, v in w.items() if v},
    }
    return c.tool_result(tool, metrics, flags, data)


def run_stress_test(client_id: str, args: StressArgs | None = None) -> ToolResult:
    args = args or StressArgs()
    client = get_client(client_id)
    tool = "run_stress_test"
    scenario = get_cma().stress_scenarios[args.scenario]
    pos = c.positions(client)
    total = c.total_value(pos)
    pnl = sum(p.market_value * scenario.shock_pct[p.instrument.risk_bucket] / 100.0 for p in pos)
    pct = 100.0 * pnl / total if total else 0.0
    metrics = [
        c.metric(c.k_stress(args.scenario, "cad"), pnl, "cad", f"{scenario.label}: P&L", tool),
        c.metric(
            c.k_stress(args.scenario, "pct"), pct, "pct", f"{scenario.label}: % of portfolio", tool
        ),
    ]
    data = {
        "scenario": args.scenario,
        "label": scenario.label,
        "shock_pct": dict(scenario.shock_pct),
    }
    return c.tool_result(tool, metrics, data=data)


def check_concentration(client_id: str, args: NoArgs | None = None) -> ToolResult:
    client = get_client(client_id)
    tool = "check_concentration"
    limit = get_settings().rules.single_security_max_pct
    pos = c.positions(client)
    total = c.total_value(pos)
    by_ticker: dict[str, float] = {}
    for p in pos:
        if p.instrument.single_security:
            by_ticker[p.ticker] = by_ticker.get(p.ticker, 0.0) + p.market_value
    metrics = [c.metric(c.K_CONC_LIMIT, limit, "pct", "Single-security concentration limit", tool)]
    flags: list[Flag] = []
    for ticker, mv in by_ticker.items():
        pct = 100.0 * mv / total if total else 0.0
        metrics.append(c.metric(c.k_conc(ticker), pct, "pct", f"{ticker} share of portfolio", tool))
        if pct > limit:
            flags.append(
                c.flag(
                    f"FLAG-CONC-{ticker}",
                    "SINGLE_SECURITY_ABOVE_LIMIT",
                    "critical",
                    [c.k_conc(ticker), c.K_CONC_LIMIT],
                    f"{ticker} is {pct:.1f}% of the portfolio, above the {limit:.1f}% "
                    "single-security limit",
                )
            )
    return c.tool_result(tool, metrics, flags, data={"single_securities": sorted(by_ticker)})
