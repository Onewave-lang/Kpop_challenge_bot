import app
from pathlib import Path


def test_next_member_filename_no_regex_error(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "DROPBOX_ROOT", tmp_path)
    member = "idol+"  # contains regex special char
    group_key = "g"
    suffix = ".jpg"
    member_dir = Path(tmp_path) / "kpop_images" / group_key / member
    member_dir.mkdir(parents=True)
    # create existing file to trigger regex evaluation
    (member_dir / f"{member}__01{suffix}").touch()

    filename = app._next_member_filename(group_key, member, suffix)
    assert filename == f"{member}__02{suffix}"


def test_next_member_filename_fills_gaps(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "DROPBOX_ROOT", tmp_path)
    member = "idol"
    group_key = "g"
    suffix = ".jpg"
    member_dir = Path(tmp_path) / "kpop_images" / group_key / member
    member_dir.mkdir(parents=True)
    (member_dir / f"{member}__01{suffix}").touch()
    (member_dir / f"{member}__03{suffix}").touch()
    filename = app._next_member_filename(group_key, member, suffix)
    assert filename == f"{member}__02{suffix}"
