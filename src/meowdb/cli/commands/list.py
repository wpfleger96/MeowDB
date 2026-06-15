from __future__ import annotations

import json

from pathlib import Path

import click

from meowdb.cli.helpers import build_context, format_duration
from meowdb.cli.options import db_path_option
from meowdb.display import console, print_info

_SORT_CHOICES = click.Choice(["newest", "oldest", "most-played", "duration"])

_SORT_MAP = {
    "newest": "newest",
    "oldest": "oldest",
    "most-played": "most_played",
    "duration": "duration_asc",
}


@click.command(name="list_meows")
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
@db_path_option
def list_meows(output_format: str, limit: int, sort: str, db_path: str | None) -> None:
    """List meows in the library."""
    ctx = build_context(Path(db_path) if db_path else None)

    sort_key = _SORT_MAP.get(sort, "newest")
    meows = ctx.db.get_all(sort=sort_key, limit=limit)
    ctx.db.close()

    if output_format == "json":
        click.echo(json.dumps(meows, indent=2))
        return

    if not meows:
        print_info("No meows in the library yet.")
        return

    _print_table(meows)


def _print_table(meows: list[dict]) -> None:  # type: ignore[type-arg]
    from rich.table import Table

    table = Table(show_header=True, header_style="bold", box=None)
    table.add_column("ID", style="dim", width=10)
    table.add_column("Duration", justify="right")
    table.add_column("Date Added", style="dim")
    table.add_column("Plays", justify="right")
    table.add_column("Labels")

    for meow in meows:
        short_id = meow["id"][:8]
        duration = format_duration(meow["duration_ms"])
        added = (meow.get("created_at") or "")[:10]
        plays = str(meow.get("play_count", 0))
        labels = ", ".join(meow.get("labels") or []) or "—"
        table.add_row(short_id, duration, added, plays, labels)

    console.print(table)
