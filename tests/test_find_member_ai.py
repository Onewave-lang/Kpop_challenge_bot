import os
import sys
from pathlib import Path
from types import SimpleNamespace
import asyncio

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "dummy")
os.environ.setdefault("PUBLIC_URL", "https://example.com")

import app


def test_find_member_from_ai_group():
    messages = []

    async def fake_reply_text(text, **kwargs):
        messages.append(text)

    update = SimpleNamespace(
        message=SimpleNamespace(text="Jin", reply_text=fake_reply_text)
    )
    ctx = SimpleNamespace(user_data={"mode": "find"})
    asyncio.run(app.on_text(update, ctx))
    assert any("BTS" in m for m in messages)
