"""What-if tool: simulate one trade inside the same accounts; compare risk before and after."""

from pydantic import BaseModel, Field, model_validator

from advisor_copilot.data_access import get_instrument, load_fixtures
from advisor_copilot.models import Client, Holding, ToolResult
from advisor_copilot.tools import common as c
from advisor_copilot.tools.portfolio import compute_drift
from advisor_copilot.tools.risk import check_concentration, compute_risk_metrics, run_stress_test

CHECKS = (compute_drift, compute_risk_metrics, check_concentration, run_stress_test)


class TradeArgs(BaseModel):
    sell_ticker: str = Field(..., description="Ticker the client holds, to sell, e.g. NRTH")
    sell_fraction: float = Field(
        0, ge=0, le=1, description="Share of the holding to sell, 0 to 1; 0 if an amount is given"
    )
    sell_amount_cad: float = Field(0, ge=0, description="Dollars to sell; 0 if a fraction is given")
    buy_ticker: str = Field(
        "CASHX", description="Ticker that receives the proceeds, e.g. CBND for bonds"
    )

    @model_validator(mode="after")
    def _check(self) -> "TradeArgs":
        if (self.sell_fraction > 0) == (self.sell_amount_cad > 0):
            raise ValueError("give exactly one of sell_fraction or sell_amount_cad")
        known = sorted(load_fixtures().instruments)
        for t in (self.sell_ticker, self.buy_ticker):
            if t not in known:
                raise ValueError(f"unknown ticker {t}; use one of {known}")
        if self.sell_ticker == self.buy_ticker:
            raise ValueError("sell and buy tickers must differ")
        return self


def apply_trade(client: Client, args: TradeArgs) -> tuple[Client, float]:
    """The client after the trade (proceeds stay in each account) and the dollar amount sold."""
    held = sum(p.market_value for p in c.positions(client) if p.ticker == args.sell_ticker)
    if held <= 0:
        raise c.ToolArgsError(f"{args.sell_ticker} is not held by this client")
    sold = held * args.sell_fraction if args.sell_fraction else min(args.sell_amount_cad, held)
    keep, sell_px, buy_px = (
        1 - sold / held,
        get_instrument(args.sell_ticker).price_cad,
        get_instrument(args.buy_ticker).price_cad,
    )
    accounts = []
    for a in client.accounts:
        moved = (
            sum(h.units for h in a.holdings if h.ticker == args.sell_ticker) * sell_px * (1 - keep)
        )
        hs = [
            h.model_copy(update={"units": h.units * keep}) if h.ticker == args.sell_ticker else h
            for h in a.holdings
        ]
        if moved and any(h.ticker == args.buy_ticker for h in hs):
            hs = [
                h.model_copy(update={"units": h.units + moved / buy_px})
                if h.ticker == args.buy_ticker
                else h
                for h in hs
            ]
        elif moved:
            hs.append(Holding(ticker=args.buy_ticker, units=moved / buy_px))
        accounts.append(a.model_copy(update={"holdings": hs}))
    return client.model_copy(update={"accounts": accounts}), sold


def simulate_trade(client_id: str, args: TradeArgs) -> ToolResult:
    tool = "simulate_trade"
    before = c.resolve(client_id)
    after, sold = apply_trade(before, args)
    res_b, res_a = [f(before, None) for f in CHECKS], [f(after, None) for f in CHECKS]
    metrics = [m for r in res_b for m in r.metrics]
    metrics += [
        m.model_copy(
            update={
                "key": f"whatif.{m.key}",
                "label": f"After the trade: {m.label}",
                "source_tool": tool,
            }
        )
        for r in res_a
        for m in r.metrics
    ]
    metrics.append(
        c.metric(
            "whatif.trade.cad", sold, "cad", f"{args.sell_ticker} sold into {args.buy_ticker}", tool
        )
    )
    fb, fa = (
        {f.flag_id for r in res_b for f in r.flags},
        {f.flag_id for r in res_a for f in r.flags},
    )
    data = {
        "trade": {**args.model_dump(), "amount_cad": round(sold, 2)},
        "resolved": sorted(fb - fa),
        "remaining": sorted(fb & fa),
        "new": sorted(fa - fb),
        "note": "Simulation only: proceeds stay in the same accounts; no taxes or trading costs.",
    }
    return c.tool_result(tool, metrics, data=data)
