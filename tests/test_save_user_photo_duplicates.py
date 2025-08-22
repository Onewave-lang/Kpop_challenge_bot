import app
import pytest
from pathlib import Path


def test_save_user_photo_prevents_duplicates(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "DROPBOX_ROOT", tmp_path)
    monkeypatch.setattr(app, "DROPBOX_PHOTOS", {})
    data = b"imgdata"
    assert app.save_user_photo("g", "idol", data, ".jpg")
    member_dir = Path(tmp_path) / "kpop_images" / "g" / "idol"
    assert len(list(member_dir.glob("*"))) == 1
    with pytest.raises(FileExistsError):
        app.save_user_photo("g", "idol", data, ".jpg")
    # Ensure file not duplicated
    assert len(list(member_dir.glob("*"))) == 1
    assert len(app.DROPBOX_PHOTOS.get("idol", [])) == 1
