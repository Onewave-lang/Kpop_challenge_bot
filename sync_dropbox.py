#!/usr/bin/env python3
"""
Sync a folder from Dropbox into the local directory defined by the
environment variable `DROPBOX_ROOT`.

The remote folder defaults to `/kpop_images` but can be overridden via
`DROPBOX_REMOTE_PATH`.

Only new or modified files are downloaded and any files removed from
Dropbox are also deleted locally. This avoids re-downloading unchanged
content on subsequent runs while keeping the local folder in sync with
Dropbox.
"""

import logging
import os
from pathlib import Path
import hashlib

import dropbox

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

APP_KEY = os.environ.get("DROPBOX_APP_KEY")
APP_SECRET = os.environ.get("DROPBOX_APP_SECRET")
REFRESH_TOKEN = os.environ.get("DROPBOX_REFRESH_TOKEN")
DROPBOX_ROOT = Path(os.environ.get("DROPBOX_ROOT", "./dropbox_sync"))
REMOTE_FOLDER = os.environ.get("DROPBOX_REMOTE_PATH", "/kpop_images")


CHUNK_SIZE = 4 * 1024 * 1024  # 4MB used by Dropbox for content hashes


def _dropbox_content_hash(path: Path) -> str:
    """Compute the Dropbox content hash for ``path``.

    See https://www.dropbox.com/developers/reference/content-hash
    """
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            hasher.update(hashlib.sha256(chunk).digest())
    return hasher.hexdigest()


def _download_entries(dbx: dropbox.Dropbox,
                      entries: list[dropbox.files.Metadata],
                      local_root: Path,
                      seen_files: set[str]) -> None:
    for entry in entries:
        if isinstance(entry, dropbox.files.FileMetadata):
            rel_path = entry.path_lower.lstrip("/")
            seen_files.add(rel_path)
            local_path = local_root / rel_path
            local_path.parent.mkdir(parents=True, exist_ok=True)

            if local_path.exists():
                try:
                    if _dropbox_content_hash(local_path) == entry.content_hash:
                        continue  # skip unchanged file
                except OSError:
                    pass

            _, res = dbx.files_download(entry.path_lower)
            with local_path.open("wb") as f:
                f.write(res.content)
            logging.info("Saved %s", local_path)


def sync_folder(dbx: dropbox.Dropbox,
                remote_folder: str,
                local_root: Path) -> None:
    """Download ``remote_folder`` into ``local_root``.

    Only new or modified files are fetched. Files that were removed from
    Dropbox are deleted locally.
    """
    local_root.mkdir(parents=True, exist_ok=True)

    seen_files: set[str] = set()

    result = dbx.files_list_folder(remote_folder, recursive=True)
    _download_entries(dbx, result.entries, local_root, seen_files)

    while result.has_more:
        result = dbx.files_list_folder_continue(result.cursor)
        _download_entries(dbx, result.entries, local_root, seen_files)

    # Remove local files not present in Dropbox
    for path in local_root.rglob("*"):
        if path.is_file():
            rel = str(path.relative_to(local_root)).replace("\\", "/")
            if rel not in seen_files:
                path.unlink()
                logging.info("Removed %s", path)

    # Clean up empty directories
    for path in sorted(local_root.rglob("*"), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()


def main() -> None:
    if not all([APP_KEY, APP_SECRET, REFRESH_TOKEN]):
        raise SystemExit(
            "Environment variables DROPBOX_APP_KEY, DROPBOX_APP_SECRET, "
            "and DROPBOX_REFRESH_TOKEN are required"
        )

    dbx = dropbox.Dropbox(
        app_key=APP_KEY,
        app_secret=APP_SECRET,
        oauth2_refresh_token=REFRESH_TOKEN,
    )
    sync_folder(dbx, REMOTE_FOLDER, DROPBOX_ROOT)


if __name__ == "__main__":
    main()
