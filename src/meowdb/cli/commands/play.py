from __future__ import annotations

import sys

from pathlib import Path

import click

from meowdb.cli.helpers import build_context, format_duration, play_audio
from meowdb.cli.options import db_path_option
from meowdb.display import console, print_error


@click.command()
@click.argument("id", required=False)
@click.option("--random", "use_random", is_flag=True, default=False, help="Play a random meow.")
@db_path_option
def play(id: str | None, use_random: bool, db_path: str | None) -> None:
    """Play a meow by ID, or a random one."""
    ctx = build_context(Path(db_path) if db_path else None)

    if id is None or use_random:
        meow = ctx.db.get_random()
        if meow is None:
            print_error("No meows in the library yet. Run `meowdb ingest` to add some.")
            ctx.db.close()
            sys.exit(1)
    else:
        meow = ctx.db.get_by_id(id)
        if meow is None:
            print_error(f"Meow not found: {id}")
            ctx.db.close()
            sys.exit(1)

    wav_path = Path(meow["wav_path"])
    if not wav_path.exists():
        print_error(f"Audio file missing: {wav_path}")
        ctx.db.close()
        sys.exit(1)

    # get_random() no longer counts a play, so record it here for both paths
    ctx.db.increment_play_count(meow["id"])
    play_audio(wav_path)

    short_id = meow["id"][:8]
    duration = format_duration(meow["duration_ms"])
    plays = meow["play_count"]
    console.print(f"[dim]{short_id}  {duration}  played {plays}x[/dim]")

    ctx.db.close()
