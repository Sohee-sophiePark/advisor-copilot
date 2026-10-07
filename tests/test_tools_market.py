"""Market snapshot filters indicators and headlines by asset class."""

from helpers import metrics

from advisor_copilot.tools import market as mk


def test_single_asset_class() -> None:
    result = mk.get_market_snapshot("C001", mk.MarketArgs(asset_classes=["US_EQUITY"]))
    assert metrics(result) == {"mkt.us_equity_ytd.pct": 18.0}
    assert [h["id"] for h in result.data["headlines"]] == ["H-1"]


def test_union_across_classes() -> None:
    result = mk.get_market_snapshot("C002", mk.MarketArgs(asset_classes=["CA_BONDS", "CASH"]))
    assert set(metrics(result)) == {"mkt.ca_bond_ytd.pct", "mkt.ca_10y_yield.pct"}
    assert [h["id"] for h in result.data["headlines"]] == ["H-3"]


def test_empty_request_returns_nothing() -> None:
    result = mk.get_market_snapshot("C001", mk.MarketArgs(asset_classes=[]))
    assert result.metrics == [] and result.data["headlines"] == []
