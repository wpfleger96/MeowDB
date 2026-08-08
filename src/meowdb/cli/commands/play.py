from __future__ import annotations

from pathlib import Path

import click

from meowdb.cli.helpers import build_context, die, format_duration, play_audio
from meowdb.cli.options import db_path_option
from meowdb.display import console


@click.command()
@click.argument("id", required=False)
@click.option("--random", "use_random", is_flag=True, default=False, help="Play a random sound.")
@db_path_option
def play(id: str | None, use_random: bool, db_path: str | None) -> None:
    """Play a sound by ID, or a random one."""
    ctx = build_context(db_path)

    if id is None or use_random:
        sound = ctx.db.get_random_sound()
        if sound is None:
            die(ctx, "No sounds in the library yet. Run `meowdb ingest` to add some.")
    else:
        sound = ctx.db.get_by_id(id)
        if sound is None:
            die(ctx, f"Sound not found: {id}")

    wav_path = Path(sound["wav_path"])
    if not wav_path.exists():
        die(ctx, f"Audio file missing: {wav_path}")

    # get_random_sound() no longer counts a play, so record it here for both paths
    ctx.db.increment_play_count(sound["id"])
    play_audio(wav_path)

    short_id = sound["id"][:8]
    duration = format_duration(sound["duration_ms"])
    plays = sound["play_count"]
    console.print(f"[dim]{short_id}  {duration}  played {plays}x[/dim]")

    ctx.db.close()
