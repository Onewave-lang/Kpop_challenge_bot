import app


def test_catalog_groups_keyboard_filters(monkeypatch):
    groups = {"g1": ["a"], "g2": ["b"]}
    monkeypatch.setattr(app, "ALL_GROUPS", groups)
    monkeypatch.setattr(app, "correct_grnames", {"g1": "G1", "g2": "G2"})
    monkeypatch.setattr(app, "DROPBOX_PHOTOS", {"a": ["/x"]})

    kb = app.catalog_groups_keyboard()
    texts = [btn.text for row in kb.inline_keyboard[:-1] for btn in row]
    assert texts == ["G1"]
