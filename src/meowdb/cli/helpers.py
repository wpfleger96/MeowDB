from __future__ import annotations

import subprocess
import sys

from pathlib import Path
from typing import Never

from meowdb.cli.context import Context
from meowdb.config import DB_PATH
from meowdb.db import MeowDB
from meowdb.display import print_error
from meowdb.processor import MeowProcessor


def build_context(db_path: str | Path | None = None) -> Context:
    db = MeowDB(Path(db_path) if db_path else DB_PATH)
    processor = MeowProcessor()
    return Context(db=db, processor=processor)


def die(ctx: Context, message: str) -> Never:
    print_error(message)
    ctx.db.close()
    sys.exit(1)


def play_audio(path: Path) -> None:
    subprocess.run(
        ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)],
        check=False,
    )


def format_duration(ms: int) -> str:
    seconds = ms / 1000
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    remaining = int(seconds % 60)
    return f"{minutes}m {remaining:02d}s"
