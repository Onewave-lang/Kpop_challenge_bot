import pytest
import app


class DummyContext:
    def __init__(self):
        self.user_data = {}

class DummyResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status = status
    def raise_for_status(self):
        if self.status != 200:
            raise Exception("bad status")
    def json(self):
        return self._payload


def test_fetch_tf_statement_success(monkeypatch):
    def fake_get(url, timeout=5):
        assert url == app.TF_API_URL
        return DummyResponse({"statement": "Lisa is in Blackpink", "is_true": True})
    monkeypatch.setattr(app.requests, "get", fake_get)
    stmt, truth = app.fetch_tf_statement()
    assert stmt == "Lisa is in Blackpink"
    assert truth is True


def test_fetch_tf_statement_rate_limit(monkeypatch):
    times = iter([10.0, 10.0, 10.3, 10.3])
    monkeypatch.setattr(app, "_tf_last_call", 0.0)
    monkeypatch.setattr(app.time, "time", lambda: next(times))
    slept = {}
    monkeypatch.setattr(app.time, "sleep", lambda t: slept.setdefault("duration", t))
    monkeypatch.setattr(
        app.requests,
        "get",
        lambda url, timeout=5: DummyResponse({"statement": "A", "is_true": True}),
    )
    app.fetch_tf_statement()
    app.fetch_tf_statement()
    assert slept["duration"] == pytest.approx(app.TF_RATE_LIMIT_SECONDS - 0.3)


def test_start_true_false_quiz_success(monkeypatch):
    ctx = DummyContext()
    monkeypatch.setattr(app, "fetch_tf_statement", lambda: ("Fact", True))
    assert app.start_true_false_quiz(ctx)
    assert ctx.user_data["true_false"]["statement"] == "Fact"
    assert ctx.user_data["true_false"]["answer"] is True


def test_start_true_false_quiz_failure(monkeypatch):
    ctx = DummyContext()
    def boom():
        raise RuntimeError("boom")
    monkeypatch.setattr(app, "fetch_tf_statement", boom)
    assert app.start_true_false_quiz(ctx) is False
    assert "true_false" not in ctx.user_data
