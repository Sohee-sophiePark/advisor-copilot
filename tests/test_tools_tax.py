"""Tax-location rules L1/L2/L3 and contribution room vs docs/05 §6."""

import pytest
from helpers import flags, metrics

from advisor_copilot.tools import tax as tx


def test_c001_location_flags_and_amounts() -> None:
    result = tx.check_asset_location("C001")
    assert flags(result) == {"FLAG-L1-VTI": "warning", "FLAG-L2": "info", "FLAG-L3": "warning"}
    m = metrics(result)
    assert m["tax.l1.VTI.cad"] == 27000.0
    assert m["tax.nonreg_interest.cad"] == 15000.0
    assert m["tax.tfsa_room.cad"] == 14000.0


@pytest.mark.parametrize("cid", ["C002", "C003"])
def test_clean_clients_have_no_location_flags(cid: str) -> None:
    assert tx.check_asset_location(cid).flags == []


def test_flag_rules_match_golden_fixture(expected: dict) -> None:
    rules = {f.rule for f in tx.check_asset_location("C001").flags}
    assert rules == {lf["rule"] for lf in expected["C001"]["location_flags"]}


@pytest.mark.parametrize(
    ("cid", "tfsa", "rrsp"), [("C001", 14000.0, 9000.0), ("C003", 0.0, 11500.0)]
)
def test_contribution_room(cid: str, tfsa: float, rrsp: float) -> None:
    m = metrics(tx.get_contribution_room(cid))
    assert (m["tax.tfsa_room.cad"], m["tax.rrsp_room.cad"]) == (tfsa, rrsp)
