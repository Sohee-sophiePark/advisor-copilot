"""Allocation and drift for C001–C003 equal docs/05 §6 within 0.01."""

import pytest
from helpers import flags, metrics

from advisor_copilot.tools import portfolio as pt

CLIENTS = ["C001", "C002", "C003"]


@pytest.mark.parametrize("cid", CLIENTS)
def test_positions_account_values(cid: str, expected: dict) -> None:
    m = metrics(pt.get_positions(cid))
    for acct, value in expected[cid]["account_values"].items():
        assert m[f"acct.{acct}.value.cad"] == pytest.approx(value, abs=0.01)


@pytest.mark.parametrize("cid", [*CLIENTS, "C004"])
def test_allocation(cid: str, expected: dict) -> None:
    m = metrics(pt.compute_allocation(cid))
    assert m["total.value.cad"] == pytest.approx(expected[cid]["total_market_value"], abs=0.01)
    for ac, value in expected[cid]["allocation_pct"].items():
        assert m[f"alloc.{ac}.pct"] == pytest.approx(value, abs=0.01)


@pytest.mark.parametrize("cid", CLIENTS)
def test_targets_present_for_profiled_clients(cid: str) -> None:
    m = metrics(pt.compute_allocation(cid))
    assert sum(v for k, v in m.items() if k.startswith("target.")) == pytest.approx(100.0)


@pytest.mark.parametrize("cid", CLIENTS)
def test_drift_values_and_flags(cid: str, expected: dict) -> None:
    result = pt.compute_drift(cid)
    m = metrics(result)
    assert m["cfg.drift_tolerance.pp"] == 5.0
    for ac, value in expected[cid]["drift_pp"].items():
        assert m[f"drift.{ac}.pp"] == pytest.approx(value, abs=0.01)
    want = {
        f["flag_id"]: f["severity"]
        for f in expected[cid]["expected_flags"]
        if f["flag_id"].startswith("FLAG-DRIFT-")
    }
    assert flags(result) == want


def test_drift_skipped_without_risk_profile() -> None:
    result = pt.compute_drift("C004")
    assert result.metrics == [] and result.flags == [] and "skipped" in result.data
