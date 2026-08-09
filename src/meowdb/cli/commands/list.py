from __future__ import annotations

import json

import click

from meowdb.cli.helpers import build_context, format_duration, resolve_animal
from meowdb.cli.options import db_path_option
from meowdb.display import console, print_info

_SORT_CHOICES = click.Choice(["newest", "oldest", "most-played", "duration"])

_SORT_MAP = {
    "newest": "newest",
    "oldest": "oldest",
    "most-played": "most_played",
    "duration": "duration_asc",
}


@click.command(name="list_sounds")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json"]),
    default="table",
    show_default=True,
    help="Output format.",
)
@click.option(
    "--limit",
    default=20,
    show_default=True,
    type=int,
    help="Maximum number of results.",
)
@click.option(
    "--sort",
    type=_SORT_CHOICES,
    default="newest",
    show_default=True,
    help="Sort order.",
)
@click.option(
    "--animal",
    "animal_name_or_id",
    default=None,
    help="Filter by animal name or ID.",
)
@db_path_option
def list_sounds(
    output_format: str,
    limit: int,
    sort: str,
    animal_name_or_id: str | None,
    db_path: str | None,
) -> None:
    """List sounds in the library."""
    ctx = build_context(db_path)

    animal_id = None
    if animal_name_or_id:
        animal_id = resolve_animal(ctx, animal_name_or_id)["id"]

    # Build id→name map for display
    animals = ctx.db.get_animals()
    animal_name_map = {a["id"]: a["name"] for a in animals}

    sort_key = _SORT_MAP.get(sort, "newest")
    sounds = ctx.db.get_all(sort=sort_key, limit=limit, animal_id=animal_id)
    total = ctx.db.get_count(animal_id=animal_id)
    ctx.db.close()

    if output_format == "json":
        click.echo(json.dumps(sounds, indent=2))
        return

    if not sounds:
        print_info("No sounds in the library yet.")
        return

    _print_table(sounds, animal_name_map)
    if len(sounds) < total:
        print_info(f"Showing {len(sounds)} of {total} sounds (use --limit to see more)")


def _print_table(sounds: list[dict], animal_name_map: dict[str, str]) -> None:  # type: ignore[type-arg]
    from rich.table import Table

    table = Table(show_header=True, header_style="bold", box=None)
    table.add_column("ID", style="dim", width=10)
    table.add_column("Animal")
    table.add_column("Duration", justify="right")
    table.add_column("Date Added", style="dim")
    table.add_column("Plays", justify="right")
    table.add_column("Labels")

    for sound in sounds:
        short_id = sound["id"][:8]
        animal_name = animal_name_map.get(sound["animal_id"], sound["animal_id"][:8])
        duration = format_duration(sound["duration_ms"])
        added = (sound.get("created_at") or "")[:10]
        plays = str(sound.get("play_count", 0))
        labels = ", ".join(sound.get("labels") or []) or "—"
        table.add_row(short_id, animal_name, duration, added, plays, labels)

    console.print(table)
