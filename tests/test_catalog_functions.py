import app


def test_build_catalog_for_group(monkeypatch):
    groups = {"g1": ["a", "b"], "g2": ["c"]}
    monkeypatch.setattr(app, "ALL_GROUPS", groups)

    def fake_fetch(name):
        return b"img" if name in {"a", "c"} else None

    monkeypatch.setattr(app, "fetch_dropbox_image", fake_fetch)

    items = app.build_catalog_for_group("g1")
    assert items == [{"image": b"img", "name": "a", "group": "g1"}]


def test_build_catalog_random(monkeypatch):
    groups = {"g1": ["a"], "g2": ["c", "d"]}
    monkeypatch.setattr(app, "ALL_GROUPS", groups)

    def fake_fetch(name):
        return b"img" if name != "d" else None

    monkeypatch.setattr(app, "fetch_dropbox_image", fake_fetch)

    items = app.build_catalog_random()
    names = {(i["name"], i["group"]) for i in items}
    assert names == {("a", "g1"), ("c", "g2")}
