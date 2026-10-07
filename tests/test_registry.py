"""Registry: golden flags reproduced end-to-end, allowlists, declarations, key conventions."""

import json
import re

import pytest

from advisor_copilot.harness.agent_loop import SUBMIT_DECL
from advisor_copilot.tools import registry as reg

KEY_RE = re.compile(
    r"^(total\.value\.cad|acct\.[A-Z_]+\.value\.cad|(alloc|target)\.[A-Z_]+\.pct"
    r"|drift\.[A-Z_]+\.pp|cfg\.drift_tolerance\.pp"
    r"|risk\.(vol|vol_band_max|target_vol|exp_return)\.pct|stress\.equity_bear\.(pct|cad)"
    r"|conc\.[A-Z]+\.pct|conc\.limit\.pct|tax\.(tfsa_room|rrsp_room|nonreg_interest)\.cad"
    r"|tax\.l1\.[A-Z]+\.cad|mkt\.[a-z0-9_]+\.pct)$"
)


@pytest.mark.parametrize("cid", ["C001", "C002", "C003"])
def test_all_expected_flags_reproduced(cid: str, expected: dict) -> None:
    got = {f.flag_id: f.severity for f in reg.flags_for_client(cid)}
    want = {f["flag_id"]: f["severity"] for f in expected[cid]["expected_flags"]}
    assert got == want


def test_allowlists_match_spec() -> None:
    want = {
        "portfolio": ["get_positions", "compute_allocation", "compute_drift"],
        "risk": ["compute_risk_metrics", "run_stress_test", "check_concentration"],
        "tax": ["get_positions", "check_asset_location", "get_contribution_room"],
        "market": ["get_market_snapshot"],
    }
    for agent, names in want.items():
        assert [t.name for t in reg.tools_for(agent)] == names


def test_declarations_are_plain_json_schema() -> None:
    for spec in reg.TOOLS.values():
        decl = spec.declaration()
        assert set(decl) == {"name", "description", "parameters"}
        assert decl["parameters"]["type"] == "object"
        assert "$ref" not in json.dumps(decl) and '"title"' not in json.dumps(decl)
    market = reg.TOOLS["get_market_snapshot"].declaration()["parameters"]
    assert market["required"] == ["asset_classes"]
    assert "CA_EQUITY" in market["properties"]["asset_classes"]["items"]["enum"]


def test_unknown_tool_and_bad_args() -> None:
    with pytest.raises(reg.UnknownToolError):
        reg.get_tool("sell_everything")
    with pytest.raises(reg.ToolArgsError):
        reg.run_tool("run_stress_test", "C001", {"scenario": "zombie_apocalypse"})
    with pytest.raises(reg.ToolArgsError):
        reg.run_tool("get_market_snapshot", "C001", {})


@pytest.mark.parametrize("cid", ["C001", "C002", "C003", "C004"])
def test_metric_keys_follow_conventions(cid: str) -> None:
    for result in reg.run_all_for_client(cid):
        for m in result.metrics:
            assert KEY_RE.match(m.key), m.key
            assert m.key.endswith("." + m.unit)
            assert m.source_tool == result.tool
            assert m.value == round(m.value, 2)


def test_submit_schema_is_inlined_for_gemini() -> None:
    dumped = json.dumps(SUBMIT_DECL.parameters)
    assert "$ref" not in dumped and "$defs" not in dumped and '"default"' not in dumped
    item = SUBMIT_DECL.parameters["properties"]["findings"]["items"]
    assert "title" in item["properties"] and item["properties"]["severity"]["enum"] == [
        "critical",
        "warning",
        "info",
    ]
