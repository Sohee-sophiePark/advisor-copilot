"""SQLite round trip: seeding then loading returns exactly what the JSON holds."""

from pathlib import Path

from advisor_copilot import db
from advisor_copilot.config import get_settings
from advisor_copilot.data_access import load_fixtures, read_json


def test_seed_then_load_matches_json(tmp_path: Path) -> None:
    d = get_settings().path("data")
    path = tmp_path / "t.db"
    db.seed(read_json(d), d, path)
    assert db.stored_hash(path) == db.source_hash(d)
    from_db = load_fixtures(d, path)
    from_json = load_fixtures(d, tmp_path / "missing.db")
    assert from_db == from_json and len(from_db.clients) == 100
