import os
import sys
from pathlib import Path
from types import SimpleNamespace
import asyncio

# Ensure environment variables for importing app
ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "dummy")
os.environ.setdefault("PUBLIC_URL", "https://example.com")

import app


def test_duplicate_member_accepts_any_group():
    groups = {"a": ["Sam"], "b": ["Sam"]}
    ctx = SimpleNamespace(user_data={})
    app._init_game(ctx, groups)
    ctx.user_data["mode"] = "game"
    g = ctx.user_data["game"]
    g["members"] = ["Sam"]
    g["total"] = 1
    g["index"] = 0
    g["current_member"] = "Sam"
    ctx.user_data["game"] = g

    captured = {}

    class DummyMsg:
        def __init__(self, text):
            self.text = text

        async def reply_text(self, *args, **kwargs):
            captured["text"] = args[0]

    update = SimpleNamespace(message=DummyMsg("b"))

    asyncio.run(app.on_text(update, ctx))
    assert captured["text"].startswith("Верно!")
