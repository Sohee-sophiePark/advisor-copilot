"""Tax-location tools: check_asset_location, get_contribution_room."""

from advisor_copilot.config import get_settings
from advisor_copilot.data_access import get_client
from advisor_copilot.models import Flag, Metric, ToolResult
from advisor_copilot.tools import common as c
from advisor_copilot.tools.common import NoArgs


def check_asset_location(client_id: str, args: NoArgs | None = None) -> ToolResult:
    client = get_client(client_id)
    tool = "check_asset_location"
    rules = get_settings().rules
    l1: dict[str, float] = {}
    nonreg_interest = 0.0
    for p in c.positions(client):
        inst = p.instrument
        if (
            p.account_type == "TFSA"
            and inst.listing == "US"
            and inst.income_type == "foreign_dividend"
        ):
            l1[p.ticker] = l1.get(p.ticker, 0.0) + p.market_value
        if p.account_type == "NON_REG" and inst.income_type == "interest":
            nonreg_interest += p.market_value
    metrics: list[Metric] = [
        c.metric(
            c.K_NONREG_INTEREST, nonreg_interest, "cad", "Interest-income holdings in NON_REG", tool
        ),
        c.metric(c.K_TFSA_ROOM, client.tfsa_room_cad, "cad", "Unused TFSA contribution room", tool),
    ]
    flags: list[Flag] = []
    for ticker, mv in l1.items():
        metrics.append(
            c.metric(c.k_l1(ticker), mv, "cad", f"{ticker} (US-listed) held in TFSA", tool)
        )
        flags.append(
            c.flag(
                f"FLAG-L1-{ticker}",
                "L1_US_LISTED_IN_TFSA",
                "warning",
                [c.k_l1(ticker)],
                f"US fund {ticker} in the TFSA loses part of its dividends to US tax; "
                "an RRSP would avoid it",
            )
        )
    if nonreg_interest >= rules.interest_in_nonreg_min_cad:
        flags.append(
            c.flag(
                "FLAG-L2",
                "L2_INTEREST_IN_NON_REG",
                "info",
                [c.K_NONREG_INTEREST],
                "Interest income in the taxable account is taxed every year",
            )
        )
    if client.tfsa_room_cad > 0 and nonreg_interest > 0:
        flags.append(
            c.flag(
                "FLAG-L3",
                "L3_UNUSED_TFSA_ROOM",
                "warning",
                [c.K_TFSA_ROOM, c.K_NONREG_INTEREST],
                "Unused TFSA room while interest-earning cash sits in a taxable account",
            )
        )
    return c.tool_result(tool, metrics, flags, data={"l1_tickers": sorted(l1)})


def get_contribution_room(client_id: str, args: NoArgs | None = None) -> ToolResult:
    client = get_client(client_id)
    tool = "get_contribution_room"
    metrics = [
        c.metric(c.K_TFSA_ROOM, client.tfsa_room_cad, "cad", "Unused TFSA contribution room", tool),
        c.metric(c.K_RRSP_ROOM, client.rrsp_room_cad, "cad", "Unused RRSP contribution room", tool),
    ]
    return c.tool_result(tool, metrics)
