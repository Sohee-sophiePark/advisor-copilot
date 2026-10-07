"""Fixtures load, validate, and cross-reference correctly."""

import pytest

from advisor_copilot import data_access as da


def test_fixtures_load() -> None:
    fx = da.load_fixtures()
    assert len(fx.clients) == 4
    assert len(fx.instruments) == 7
    assert len(fx.notes) == 7


def test_client_lookup() -> None:
    assert da.get_client("C002").name == "Margaret Leblanc"
    with pytest.raises(KeyError):
        da.get_client("C999")


def test_notes_are_per_client() -> None:
    assert [n.note_id for n in da.get_notes("C003")] == ["N-301", "N-302"]
    assert da.get_notes("C999") == []


def test_targets_sum_to_100() -> None:
    for profile in ("conservative", "balanced", "growth"):
        assert sum(da.get_targets(profile).values()) == 100


def test_kyc_missing() -> None:
    assert da.get_client("C001").kyc_missing() == []
    assert da.get_client("C004").kyc_missing() == [
        "risk_profile",
        "time_horizon_years",
        "objectives",
    ]
