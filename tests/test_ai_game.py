import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

# Avoid runtime errors when importing app
ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "dummy")
os.environ.setdefault("PUBLIC_URL", "https://example.com")

import app

DUMMY_DATA = {
    "group_a": ["a1", "a2", "a3", "a4"],
    "group_b": ["b1", "b2", "b3", "b4"],
    "group_c": ["c1", "c2", "c3", "c4"],
}


def test_load_ai_kpop_groups(tmp_path):
    data_file = tmp_path / "top50_groups.json"
    data_file.write_text(json.dumps(DUMMY_DATA), encoding="utf-8")
    loaded = app.load_ai_kpop_groups(data_file)
    assert loaded == DUMMY_DATA


def test_start_ai_game(monkeypatch):
    ctx = SimpleNamespace(user_data={})
    monkeypatch.setattr(app, "ai_kpop_groups", DUMMY_DATA)
    monkeypatch.setattr(app, "ai_correct_grnames", {k: k for k in DUMMY_DATA})
    assert app.start_ai_game(ctx)
    assert ctx.user_data["mode"] == "ai_game"
    assert len(ctx.user_data["game"]["members"]) == 10
