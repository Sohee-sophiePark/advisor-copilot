"""Market snapshot filters indicators and headlines by asset class."""

from helpers import metrics

from advisor_copilot.tools import market as mk


def test_single_asset_class() -> None:
    result = mk.get_market_snapshot("C001", mk.MarketArgs(asset_classes=["US_EQUITY"]))
    assert set(metrics(result)) == {"mkt.us_10y_yield.pct", "mkt.usd_cad.ratio"}
    assert result.data["headlines"] == []  # Bank of Canada releases are tagged to bonds and cash


def test_union_across_classes() -> None:
    result = mk.get_market_snapshot("C002", mk.MarketArgs(asset_classes=["CA_BONDS", "CASH"]))
    assert set(metrics(result)) == {
        "mkt.ca_policy_rate.pct",
        "mkt.ca_10y_yield.pct",
        "mkt.ca_curve.pp",
    }
    assert all(h["id"].startswith("BOC-") for h in result.data["headlines"])


def test_empty_request_returns_nothing() -> None:
    result = mk.get_market_snapshot("C001", mk.MarketArgs(asset_classes=[]))
    assert result.metrics == [] and result.data["headlines"] == []
