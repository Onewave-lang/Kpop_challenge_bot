import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "dummy")
os.environ.setdefault("PUBLIC_URL", "https://example.com")

import app


def test_pretty_map_accepts_spaceless_names():
    groups = {"red velvet": ["A", "B"]}
    names_map = {"red velvet": "Red Velvet"}
    mapping = app.build_pretty_map(groups, names_map)
    assert mapping["redvelvet"] == "red velvet"
