import importlib
import sys
from pathlib import Path


def test_cover_image_download_once(tmp_path, monkeypatch):
    monkeypatch.setenv("DROPBOX_ROOT", str(tmp_path))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import app
    importlib.reload(app)

    remote_content = b"test-bytes"
    tmp_hash = tmp_path / "hash.tmp"
    tmp_hash.write_bytes(remote_content)
    expected_hash = app._dropbox_content_hash(tmp_hash)

    class FakeMetadata:
        content_hash = expected_hash

    class FakeResponse:
        def __init__(self, data: bytes):
            self.content = data

    class FakeDropbox:
        def __init__(self, data: bytes):
            self.data = data
            self.downloads = 0

        def files_get_metadata(self, path: str):
            assert path == app.COVER_IMAGE_REMOTE_PATH
            return FakeMetadata()

        def files_download(self, path: str):
            self.downloads += 1
            assert path == app.COVER_IMAGE_REMOTE_PATH
            return None, FakeResponse(self.data)

    fake = FakeDropbox(remote_content)
    path = app._ensure_cover_image(fake)
    assert path == Path(tmp_path) / "cover_image" / "cover1.png"
    assert path.read_bytes() == remote_content
    assert fake.downloads == 1

    # Second call should not redownload the file
    path = app._ensure_cover_image(fake)
    assert fake.downloads == 1
    assert path.read_bytes() == remote_content
