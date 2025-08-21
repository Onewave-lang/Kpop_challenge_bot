#!/usr/bin/env bash
python sync_dropbox.py          # обновляем фото из Dropbox
uvicorn app:app --host 0.0.0.0 --port $PORT
