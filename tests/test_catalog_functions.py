import app


def test_build_catalog_for_group(monkeypatch):
    groups = {"g1": ["a", "b"], "g2": ["c"]}
    monkeypatch.setattr(app, "ALL_GROUPS", groups)

    def fake_fetch(name):
        if name == "a":
            return [b"img1", b"img2"]
        if name == "c":
            return [b"img3"]
        return []

    monkeypatch.setattr(app, "fetch_dropbox_images", fake_fetch)

    # Ensure items are shuffled by reversing the list
    def fake_shuffle(lst):
        lst.reverse()

    monkeypatch.setattr(app.random, "shuffle", fake_shuffle)

    items = app.build_catalog_for_group("g1", app.ALL_GROUPS)
    assert items == [
        {"image": b"img2", "name": "a", "group": "g1"},
        {"image": b"img1", "name": "a", "group": "g1"},
    ]


def test_build_catalog_random(monkeypatch):
    groups = {"g1": ["a"], "g2": ["c", "d"]}
    monkeypatch.setattr(app, "ALL_GROUPS", groups)

    def fake_fetch(name):
        if name == "a":
            return [b"img1", b"img2"]
        if name == "c":
            return [b"img3"]
        return []

    monkeypatch.setattr(app, "fetch_dropbox_images", fake_fetch)

    items = app.build_catalog_random(app.ALL_GROUPS)
    names = [(i["name"], i["group"]) for i in items]
    assert names.count(("a", "g1")) == 2
    assert names.count(("c", "g2")) == 1
