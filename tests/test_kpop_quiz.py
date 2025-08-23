import os
import sys
import asyncio
from types import SimpleNamespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "dummy")
os.environ.setdefault("PUBLIC_URL", "https://example.com")

import app


class DummyContext:
    def __init__(self):
        self.user_data = {}


class DummyMessage:
    def __init__(self, messages):
        self.messages = messages

    async def reply_text(self, text, **kwargs):
        self.messages.append(text)

    async def reply_photo(self, _photo, caption="", **kwargs):
        self.messages.append(caption)


def test_start_quiz_picks_ten(monkeypatch):
    questions = [{"question": f"Q{i}", "answer": "a"} for i in range(15)]
    monkeypatch.setattr(app, "QUIZ_POOL", questions)
    ctx = DummyContext()
    assert app.start_quiz(ctx)
    qdata = ctx.user_data["quiz"]
    assert len(qdata["questions"]) == 10
    texts = [q["question"] for q in qdata["questions"]]
    assert len(set(texts)) == len(texts)


def test_quiz_flow_with_incorrect(monkeypatch):
    questions = [
        {"question": "Q1", "answer": "A1"},
        {"question": "Q2", "answer": "A2"},
    ]
    monkeypatch.setattr(app, "QUIZ_POOL", questions)
    monkeypatch.setattr(app.random, "sample", lambda seq, n: seq[:n])
    ctx = DummyContext()
    assert app.start_quiz(ctx)
    app.next_quiz_question(ctx)
    messages = []
    msg = DummyMessage(messages)
    update1 = SimpleNamespace(message=SimpleNamespace(text="wrong", reply_text=msg.reply_text, reply_photo=msg.reply_photo))
    asyncio.run(app.on_text(update1, ctx))
    update2 = SimpleNamespace(message=SimpleNamespace(text="A2", reply_text=msg.reply_text, reply_photo=msg.reply_photo))
    asyncio.run(app.on_text(update2, ctx))
    assert any("Квиз завершён" in m for m in messages)
    assert any("Попробуй запросить у ChatGPT" in m for m in messages)
