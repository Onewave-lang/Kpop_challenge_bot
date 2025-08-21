#!/usr/bin/env python3
"""
Sync the folder `/kpop_images` from Dropbox into the local directory defined by
the environment variable `DROPBOX_ROOT`.

Requirements:
  pip install dropbox
  (Add “dropbox” to requirements.txt when deploying.)
"""

import logging
import os
from pathlib import Path

import dropbox

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

DROPBOX_TOKEN = os.environ.get("DROPBOX_TOKEN")
DROPBOX_ROOT = Path(os.environ.get("DROPBOX_ROOT", "./dropbox_sync"))
REMOTE_FOLDER = "/kpop_images"   # change if your Dropbox structure differs


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
    local_root.mkdir(parents=True, exist_ok=True)

    result = dbx.files_list_folder(remote_folder, recursive=True)
    _download_entries(dbx, result.entries, local_root)

    while result.has_more:
        result = dbx.files_list_folder_continue(result.cursor)
        _download_entries(dbx, result.entries, local_root)


def main() -> None:
    if not DROPBOX_TOKEN:
        raise SystemExit("Environment variable DROPBOX_TOKEN is missing")

    dbx = dropbox.Dropbox(DROPBOX_TOKEN)
    sync_folder(dbx, REMOTE_FOLDER, DROPBOX_ROOT)


if __name__ == "__main__":
    main()
