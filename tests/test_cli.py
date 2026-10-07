"""CLI parser exposes every planned command; `tools` runs without any LLM."""

import pytest

from advisor_copilot.cli import COMMANDS, build_parser, main

SAMPLE_ARGS = {
    "tools": ["C001"],
    "run": ["C001"],
    "approve": ["r1"],
    "resume": ["r1"],
    "replay": ["S1"],
    "export": ["out.json"],
}


def test_help_lists_all_commands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for name in ("run", "record", "replay", "eval", "resume", "approve", "tools"):
        assert name in out


def test_parser_accepts_each_command() -> None:
    parser = build_parser()
    for name in COMMANDS:
        assert parser.parse_args([name, *SAMPLE_ARGS.get(name, [])]).command == name


def test_tools_command_prints_metrics_and_flags(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["tools", "C002"]) == 0
    out = capsys.readouterr().out
    assert "conc.NRTH.pct" in out and "FLAG-CONC-NRTH" in out and "critical" in out
