from __future__ import annotations

import os

from pathlib import Path

_data_dir = Path(os.environ.get("MEOWDB_DATA_DIR", Path.home() / ".local" / "share" / "meowdb"))

DATA_DIR: Path = _data_dir
DB_PATH: Path = _data_dir / "meowdb.sqlite"
WAV_DIR: Path = _data_dir / "audio" / "wav"
MP3_DIR: Path = _data_dir / "audio" / "mp3"
STAGING_DIR: Path = _data_dir / "staging"
ORIGINALS_DIR: Path = _data_dir / "originals"
PHOTOS_DIR: Path = _data_dir / "photos"

HOST: str = os.environ.get("MEOWDB_HOST", "127.0.0.1")
PORT: int = int(os.environ.get("MEOWDB_PORT", "8000"))

_default_origins = "http://localhost:8000,http://127.0.0.1:8000"
CORS_ORIGINS: list[str] = [
    o.strip()
    for o in os.environ.get("MEOWDB_CORS_ORIGINS", _default_origins).split(",")
    if o.strip()
]

PASSWORD_HASH: str = os.environ.get("MEOWDB_PASSWORD_HASH", "")
_DEFAULT_SESSION_SECRET = "local-dev-secret-not-for-production"
SESSION_SECRET: str = os.environ.get("MEOWDB_SESSION_SECRET", _DEFAULT_SESSION_SECRET)
IS_LOCALHOST: bool = HOST in ("127.0.0.1", "localhost")

# Upload formats accepted by the web picker, the /ingest API, and the CLI.
# Video files have their audio track extracted; everything else is treated as audio.
AUDIO_SUFFIXES = {".m4a", ".mp3", ".wav", ".ogg", ".flac", ".aac", ".webm"}
VIDEO_SUFFIXES = {".mov", ".mp4", ".avi", ".mkv", ".3gp"}
ALLOWED_MEDIA_SUFFIXES = AUDIO_SUFFIXES | VIDEO_SUFFIXES
# Comma-joined form the server injects into the upload picker's `accept` attribute.
UPLOAD_ACCEPT = ",".join(sorted(ALLOWED_MEDIA_SUFFIXES))

# S3 media storage — set MEOWDB_S3_BUCKET to activate S3 mode; unset means local filesystem.
S3_BUCKET: str | None = os.environ.get("MEOWDB_S3_BUCKET")
S3_REGION: str = os.environ.get("MEOWDB_S3_REGION", "us-west-2")
S3_ACCESS_KEY_ID: str | None = os.environ.get("MEOWDB_S3_ACCESS_KEY_ID")
S3_SECRET_ACCESS_KEY: str | None = os.environ.get("MEOWDB_S3_SECRET_ACCESS_KEY")
S3_ENDPOINT_URL: str | None = os.environ.get("MEOWDB_S3_ENDPOINT_URL")
