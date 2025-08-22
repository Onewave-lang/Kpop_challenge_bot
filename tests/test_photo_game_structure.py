import app


class DummyContext:
    def __init__(self):
        self.user_data = {}


def test_start_photo_game_dropbox(monkeypatch):
    # Подготовим тестовые данные: у двух айдолов есть изображения, у одного нет
    groups = {"g": ["idol one", "idol two", "idol three"]}
    monkeypatch.setattr(app, "ALL_GROUPS", groups)
    monkeypatch.setattr(app, "PHOTO_GAME_QUESTIONS", 3)

    def fake_fetch(name):
        if name == "idol one":
            return [b"img1", b"img2"]
        if name == "idol two":
            return [b"img3"]
        return []

    monkeypatch.setattr(app, "fetch_dropbox_images", fake_fetch)

    ctx = DummyContext()
    assert app.start_photo_game(ctx)
    items = ctx.user_data["game"]["items"]
    assert len(items) == 3
    names = [item["name"] for item in items]
    assert names.count("idol one") == 2
    assert names.count("idol two") == 1


def test_photo_game_picks_unique_images(monkeypatch):
    # подготовим 30 уникальных фото и убедимся, что берётся ровно 20 без повторов
    groups = {"g": [f"idol {i}" for i in range(30)]}
    monkeypatch.setattr(app, "ALL_GROUPS", groups)
    monkeypatch.setattr(app, "PHOTO_GAME_QUESTIONS", 20)

    def fake_fetch(name):
        idx = int(name.split()[1])
        # каждая участница имеет одно уникальное изображение
        return [bytes([idx])]

    monkeypatch.setattr(app, "fetch_dropbox_images", fake_fetch)

    ctx = DummyContext()
    assert app.start_photo_game(ctx)
    items = ctx.user_data["game"]["items"]
    assert len(items) == 20
    images = [item["image"] for item in items]
    assert len(set(images)) == 20
