from __future__ import annotations

from pathlib import Path

import click

from meowdb.cli.helpers import build_context, format_duration
from meowdb.cli.options import db_path_option
from meowdb.display import console, print_info


@click.command()
@db_path_option
def stats(db_path: str | None) -> None:
    """Show library statistics."""
    ctx = build_context(Path(db_path) if db_path else None)
    data = ctx.db.get_stats()
    ctx.db.close()

    total = data["total_meows"]
    if total == 0:
        print_info("No meows in the library yet.")
        return

    console.print()
    console.print(f"  [bold]Total meows:[/bold]    {total}")
    console.print(
        f"  [bold]Total duration:[/bold] {format_duration(int(data['total_duration_ms']))}"
    )
    console.print(f"  [bold]Avg duration:[/bold]   {format_duration(int(data['avg_duration_ms']))}")

    most_played = data.get("most_played") or []
    if most_played:
        console.print()
        console.print("  [bold]Most played:[/bold]")
        for meow in most_played[:5]:
            short_id = meow["id"][:8]
            plays = meow.get("play_count", 0)
            duration = format_duration(meow["duration_ms"])
            console.print(f"    {short_id}  {duration}  {plays}x")

    recent = data.get("recent") or []
    if recent:
        first_date = recent[-1].get("created_at", "")[:10]
        last_date = recent[0].get("created_at", "")[:10]
        if first_date and last_date and first_date != last_date:
            console.print()
            console.print(f"  [bold]Date range:[/bold]     {first_date} – {last_date}")

    console.print()
