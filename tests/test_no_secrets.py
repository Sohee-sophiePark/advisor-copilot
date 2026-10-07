"""No API key or key-shaped string in any tracked or unignored file."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent
KEY = re.compile(r"AIza[0-9A-Za-z_\-]{30,}|GEMINI_API_KEY\s*=\s*\S{8,}")


def test_no_key_material_in_repo() -> None:
    cmd = ["git", "ls-files", "--cached", "--others", "--exclude-standard"]
    files = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    hits = [
        f
        for f in files
        if (ROOT / f).is_file() and KEY.search((ROOT / f).read_text(errors="ignore"))
    ]
    assert hits == []


def test_env_is_ignored() -> None:
    assert subprocess.run(["git", "check-ignore", "-q", ".env"], cwd=ROOT).returncode == 0
