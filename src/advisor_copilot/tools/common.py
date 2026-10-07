"""Metric, Flag, and ToolResult builders plus metric-key helpers shared by all tools."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from advisor_copilot.data_access import get_instrument
from advisor_copilot.models import (
    AccountType,
    AssetClass,
    Client,
    Flag,
    Instrument,
    Metric,
    Severity,
    ToolResult,
    Unit,
)


class NoArgs(BaseModel):
    """Tool takes no model-visible parameters; `client_id` is bound by the harness."""


@dataclass(frozen=True)
class Position:
    account_type: AccountType
    ticker: str
    units: float
    instrument: Instrument

    @property
    def market_value(self) -> float:
        return self.units * self.instrument.price_cad


def positions(client: Client) -> list[Position]:
    """Every holding across the client's accounts, with its instrument attached."""
    return [
        Position(acct.type, h.ticker, h.units, get_instrument(h.ticker))
        for acct in client.accounts
        for h in acct.holdings
    ]


def total_value(pos: Iterable[Position]) -> float:
    return sum(p.market_value for p in pos)


def asset_classes_held(client: Client) -> list[AssetClass]:
    return sorted({p.instrument.asset_class for p in positions(client)})


def metric(key: str, value: float, unit: Unit, label: str, source_tool: str) -> Metric:
    """Metric with the value rounded to 2 decimals (03 §6 storage rule)."""
    return Metric(
        key=key, value=round(float(value), 2), unit=unit, label=label, source_tool=source_tool
    )


def flag(flag_id: str, rule: str, severity: Severity, metric_refs: list[str], message: str) -> Flag:
    return Flag(
        flag_id=flag_id, rule=rule, severity=severity, metric_refs=metric_refs, message=message
    )


def tool_result(
    tool: str,
    metrics: Iterable[Metric] = (),
    flags: Iterable[Flag] = (),
    data: dict[str, Any] | None = None,
) -> ToolResult:
    return ToolResult(tool=tool, metrics=list(metrics), flags=list(flags), data=data or {})


# ---- metric keys (03 §6) ----
K_TOTAL = "total.value.cad"
K_DRIFT_TOL = "cfg.drift_tolerance.pp"
K_RISK_VOL = "risk.vol.pct"
K_RISK_BAND = "risk.vol_band_max.pct"
K_RISK_TARGET_VOL = "risk.target_vol.pct"
K_RISK_RETURN = "risk.exp_return.pct"
K_CONC_LIMIT = "conc.limit.pct"
K_TFSA_ROOM = "tax.tfsa_room.cad"
K_RRSP_ROOM = "tax.rrsp_room.cad"
K_NONREG_INTEREST = "tax.nonreg_interest.cad"
K_CLIENT_AGE = "client.age.years"
K_CLIENT_HORIZON = "client.horizon.years"


def k_acct(account_type: str) -> str:
    return f"acct.{account_type}.value.cad"


def k_alloc(asset_class: str) -> str:
    return f"alloc.{asset_class}.pct"


def k_target(asset_class: str) -> str:
    return f"target.{asset_class}.pct"


def k_drift(asset_class: str) -> str:
    return f"drift.{asset_class}.pp"


def k_stress(scenario: str, unit: str) -> str:
    return f"stress.{scenario}.{unit}"


def k_conc(ticker: str) -> str:
    return f"conc.{ticker}.pct"


def k_l1(ticker: str) -> str:
    return f"tax.l1.{ticker}.cad"


def k_mkt(indicator: str) -> str:
    return f"mkt.{indicator}.pct"
