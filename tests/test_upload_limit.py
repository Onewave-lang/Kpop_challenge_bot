import app
from datetime import date, timedelta


def test_upload_limit_resets_each_day(monkeypatch):
    user_id = 42
    app.USER_UPLOADS.clear()
    for _ in range(app.UPLOAD_LIMIT_PER_DAY):
        assert not app.has_reached_upload_limit(user_id)
        app.register_user_upload(user_id)
    assert app.has_reached_upload_limit(user_id)

    today = date.today()

    class FakeDate:
        @classmethod
        def today(cls):
            return today + timedelta(days=1)

    monkeypatch.setattr(app, "date", FakeDate)
    assert not app.has_reached_upload_limit(user_id)
