"""E01–E15: one household per rule boundary; expectations from docs/REDESIGN_PLAN.md §5 (no LLM)."""

import pytest
from helpers import flags

from advisor_copilot.config import get_settings
from advisor_copilot.data_access import get_client, get_notes
from advisor_copilot.harness.gates import kyc_gate
from advisor_copilot.harness.injection import detect
from advisor_copilot.tools import portfolio as pt
from advisor_copilot.tools import risk as rk
from advisor_copilot.tools import tax as tx
from advisor_copilot.tools.registry import flags_for_client

RULES = get_settings().rules


def all_flags(cid: str) -> dict[str, str]:
    return {f.flag_id: f.severity for f in flags_for_client(cid)}


def test_e01_kyc_expired_blocks() -> None:
    g = kyc_gate(get_client("C101"), RULES)
    assert not g.passed and "over 12 months" in g.violations[0]


@pytest.mark.parametrize(("cid", "flagged"), [("C102", False), ("C103", True)])
def test_e02_e03_concentration_boundary(cid: str, flagged: bool) -> None:
    assert flags(rk.check_concentration(cid)) == ({"FLAG-CONC-NRTH": "critical"} if flagged else {})


def test_e04_drift_exactly_at_tolerance_is_not_flagged() -> None:
    assert flags(pt.compute_drift("C104")) == {}


def test_e05_drift_beyond_twice_tolerance_is_critical() -> None:
    assert flags(pt.compute_drift("C105")) == {
        "FLAG-DRIFT-CA_BONDS": "critical",
        "FLAG-DRIFT-US_EQUITY": "critical",
    }


def test_e06_all_cash() -> None:
    f = flags(pt.compute_drift("C106"))
    assert {k for k, v in f.items() if v == "critical"} == {
        "FLAG-DRIFT-CASH",
        "FLAG-DRIFT-CA_BONDS",
        "FLAG-DRIFT-CA_EQUITY",
        "FLAG-DRIFT-US_EQUITY",
        "FLAG-DRIFT-INTL_EQUITY",
    }


@pytest.mark.parametrize(("cid", "total"), [("C107", 3_000), ("C108", 8_000_000)])
def test_e07_e08_tiny_and_large_accounts(cid: str, total: float) -> None:
    value, alloc = pt.allocation(get_client(cid))
    assert value == pytest.approx(total, abs=1) and sum(alloc.values()) == pytest.approx(100)


def test_e09_retiree_above_band() -> None:
    assert flags(rk.compute_risk_metrics("C109")) == {"FLAG-SUIT-VOL": "critical"}
    assert get_client("C109").preferences.income_need_cad_month > 0


def test_e10_goal_conflict() -> None:
    assert flags(pt.check_goals("C110")) == {"FLAG-GOAL-G1": "warning"}


def test_e11_no_room_interest_info_only() -> None:
    assert flags(tx.check_asset_location("C111")) == {"FLAG-L2": "info"}


def test_e12_small_us_fund_in_tfsa() -> None:
    assert flags(tx.check_asset_location("C112")) == {"FLAG-L1-USEQ": "warning"}


def test_e13_reworded_injection_is_detected() -> None:
    assert len(detect(get_notes("C113")[0].text)) >= 2
    assert all_flags("C113") == {}


def test_e14_missing_data_still_computes() -> None:
    c = get_client("C114")
    assert c.liquidity_needs is None and get_notes("C114") == [] and kyc_gate(c, RULES).passed
    assert all_flags("C114") == {}


def test_e15_review_overdue_otherwise_clean() -> None:
    c = get_client("C115")
    assert c.review_due < RULES.as_of and all_flags("C115") == {} and kyc_gate(c, RULES).passed


@pytest.mark.parametrize("cid", ["C001", "C002", "C003", "C110"])
def test_base_clients_goals_only_flag_the_conflict_case(cid: str) -> None:
    assert bool(flags(pt.check_goals(cid))) == (cid == "C110")
