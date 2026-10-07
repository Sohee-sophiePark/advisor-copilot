"""Volatility, expected return, stress, concentration, and suitability flags vs docs/05 §6."""

import numpy as np
import pytest
from helpers import flags, metrics

from advisor_copilot.tools import risk as rk

CLIENTS = ["C001", "C002", "C003"]


@pytest.mark.parametrize("cid", CLIENTS)
def test_risk_metrics(cid: str, expected: dict) -> None:
    result = rk.compute_risk_metrics(cid)
    m, e = metrics(result), expected[cid]
    assert m["risk.vol.pct"] == pytest.approx(e["portfolio_vol_pct"], abs=0.01)
    assert m["risk.exp_return.pct"] == pytest.approx(e["expected_return_pct"], abs=0.01)
    assert m["risk.vol_band_max.pct"] == pytest.approx(e["vol_band_max_pct"], abs=0.01)
    assert m["risk.target_vol.pct"] == pytest.approx(e["target_portfolio_vol_pct"], abs=0.01)
    assert ("FLAG-SUIT-VOL" in flags(result)) == e["suitability_vol_breach"]
    if e["suitability_vol_breach"]:
        assert flags(result)["FLAG-SUIT-VOL"] == "critical"


@pytest.mark.parametrize("cid", CLIENTS)
def test_stress_test(cid: str, expected: dict) -> None:
    m, e = metrics(rk.run_stress_test(cid, rk.StressArgs())), expected[cid]
    assert m["stress.equity_bear.cad"] == pytest.approx(e["stress_equity_bear_pnl"], abs=0.01)
    assert m["stress.equity_bear.pct"] == pytest.approx(e["stress_equity_bear_pct"], abs=0.01)


@pytest.mark.parametrize("cid", CLIENTS)
def test_concentration(cid: str, expected: dict) -> None:
    result = rk.check_concentration(cid)
    m, e = metrics(result), expected[cid]
    assert m["conc.limit.pct"] == 10.0
    for ticker, pct in e["single_security_pct"].items():
        assert m[f"conc.{ticker}.pct"] == pytest.approx(pct, abs=0.01)
    assert flags(result) == {f"FLAG-CONC-{t}": "critical" for t in e["concentration_breaches"]}


def test_correlation_matrix_matches_spec() -> None:
    rho = rk.correlation_matrix()
    assert np.allclose(rho, rho.T)
    assert np.allclose(np.diag(rho), 1.0)
    assert np.allclose(rho[0, 1:], 0.0)  # CASH uncorrelated with everything
    assert np.linalg.eigvalsh(rho).min() == pytest.approx(0.16, abs=0.01)


def test_kyc_incomplete_client_still_computes_without_band() -> None:
    result = rk.compute_risk_metrics("C004")
    assert "risk.vol.pct" in metrics(result) and "risk.vol_band_max.pct" not in metrics(result)
    assert result.flags == []
