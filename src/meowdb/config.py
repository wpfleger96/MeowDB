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

HOST: str = os.environ.get("MEOWDB_HOST", "127.0.0.1")
PORT: int = int(os.environ.get("MEOWDB_PORT", "8000"))

_default_origins = "http://localhost:8000,http://127.0.0.1:8000"
CORS_ORIGINS: list[str] = [
    o.strip()
    for o in os.environ.get("MEOWDB_CORS_ORIGINS", _default_origins).split(",")
    if o.strip()
]
