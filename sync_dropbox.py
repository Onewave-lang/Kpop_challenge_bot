#!/usr/bin/env python3
"""
Sync a folder from Dropbox into the local directory defined by the
environment variable `DROPBOX_ROOT`.

The remote folder defaults to `/kpop_images` but can be overridden via
`DROPBOX_REMOTE_PATH`.

Before downloading, the existing local directory is wiped so that photos
deleted in Dropbox do not remain on disk.
"""

import logging
import os
import shutil
from pathlib import Path

import dropbox

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

APP_KEY = os.environ.get("DROPBOX_APP_KEY")
APP_SECRET = os.environ.get("DROPBOX_APP_SECRET")
REFRESH_TOKEN = os.environ.get("DROPBOX_REFRESH_TOKEN")
DROPBOX_ROOT = Path(os.environ.get("DROPBOX_ROOT", "./dropbox_sync"))
REMOTE_FOLDER = os.environ.get("DROPBOX_REMOTE_PATH", "/kpop_images")


def _download_entries(dbx: dropbox.Dropbox,
                      entries: list[dropbox.files.Metadata],
                      local_root: Path) -> None:
    for entry in entries:
        if isinstance(entry, dropbox.files.FileMetadata):
            local_path = local_root / entry.path_lower.lstrip("/")
            local_path.parent.mkdir(parents=True, exist_ok=True)
            _, res = dbx.files_download(entry.path_lower)
            with local_path.open("wb") as f:
                f.write(res.content)
            logging.info("Saved %s", local_path)


def sync_folder(dbx: dropbox.Dropbox,
                remote_folder: str,
                local_root: Path) -> None:
    """Download ``remote_folder`` into ``local_root``.

    The existing ``local_root`` directory is removed before downloading to
    ensure that any files deleted in Dropbox do not linger locally.
    """
    if local_root.exists():
        shutil.rmtree(local_root)
    local_root.mkdir(parents=True, exist_ok=True)

    result = dbx.files_list_folder(remote_folder, recursive=True)
    _download_entries(dbx, result.entries, local_root)

    while result.has_more:
        result = dbx.files_list_folder_continue(result.cursor)
        _download_entries(dbx, result.entries, local_root)


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
