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


def resolve_animal(ctx: Context, name_or_id: str | None) -> dict:  # type: ignore[type-arg]
    """Resolve an --animal name/ID to an animal dict.

    None → first animal (by created_at). Exits with an error if the database
    has no animals. Otherwise matches by exact id first, then case-insensitive name.
    """
    animals = ctx.db.get_animals()
    if not animals:
        die(ctx, "No animals in the database. Run `meowdb db init` to set one up.")

    if name_or_id is None:
        return animals[0]

    for animal in animals:
        if animal["id"] == name_or_id:
            return animal
    for animal in animals:
        if animal["name"].lower() == name_or_id.lower():
            return animal

    die(ctx, f"Animal not found: {name_or_id!r}")


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
