"""Settings load from YAML and honour the RUN_MODE environment override."""

from advisor_copilot.config import ROOT, SETTINGS_FILE, Settings, load_settings


def test_settings_file_lives_under_repo_root() -> None:
    assert SETTINGS_FILE == ROOT / "config" / "settings.yaml"
    assert SETTINGS_FILE.is_file()


def test_defaults_match_spec() -> None:
    s = load_settings(env={})
    assert isinstance(s, Settings)
    assert s.run_mode == "replay"
    assert s.budget.max_llm_calls == 20
    assert s.loop.max_revisions == 2
    assert s.rules.drift_tolerance_pp == 5.0
    assert s.rate_limits.rpm_for(s.models.router) > 0


def test_run_mode_env_override() -> None:
    assert load_settings(env={"RUN_MODE": "live"}).run_mode == "live"
    assert load_settings(env={"RUN_MODE": ""}).run_mode == "replay"


def test_paths_resolve_under_root() -> None:
    s = load_settings(env={})
    assert s.path("data") == ROOT / "data" / "synthetic"
    assert s.path("data").is_dir()
