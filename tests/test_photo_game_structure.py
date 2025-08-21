import app


class DummyContext:
    def __init__(self):
        self.user_data = {}


def test_start_photo_game_dropbox(monkeypatch):
    # Подготовим тестовые данные: у двух айдолов есть изображения, у одного нет
    groups = {"g": ["idol one", "idol two", "idol three"]}
    monkeypatch.setattr(app, "ALL_GROUPS", groups)
    monkeypatch.setattr(app, "PHOTO_GAME_QUESTIONS", 2)

    def fake_fetch(name):
        return b"img" if name in {"idol one", "idol two"} else None

    monkeypatch.setattr(app, "fetch_dropbox_image", fake_fetch)

    ctx = DummyContext()
    assert app.start_photo_game(ctx)
    items = ctx.user_data["game"]["items"]
    assert len(items) == 2
    names = {item["name"] for item in items}
    assert names == {"idol one", "idol two"}
