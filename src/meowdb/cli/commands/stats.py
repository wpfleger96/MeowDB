from __future__ import annotations

import click

from meowdb.cli.helpers import build_context, format_duration
from meowdb.cli.options import db_path_option
from meowdb.display import console, print_info


@click.command()
@db_path_option
def stats(db_path: str | None) -> None:
    """Show library statistics."""
    ctx = build_context(db_path)
    data = ctx.db.get_stats()
    ctx.db.close()

    total = data["total_sounds"]
    if total == 0:
        print_info("No sounds in the library yet.")
        return

    console.print()
    console.print(f"  [bold]Total sounds:[/bold]   {total}")
    console.print(
        f"  [bold]Total duration:[/bold] {format_duration(int(data['total_duration_ms']))}"
    )
    console.print(f"  [bold]Avg duration:[/bold]   {format_duration(int(data['avg_duration_ms']))}")

    species_counts = data.get("species_counts") or {}
    if species_counts:
        console.print()
        console.print("  [bold]By species:[/bold]")
        for species, count in sorted(species_counts.items()):
            console.print(f"    {species}: {count}")

    most_played = data.get("most_played") or []
    if most_played:
        console.print()
        console.print("  [bold]Most played:[/bold]")
        for sound in most_played[:5]:
            short_id = sound["id"][:8]
            plays = sound.get("play_count", 0)
            duration = format_duration(sound["duration_ms"])
            console.print(f"    {short_id}  {duration}  {plays}x")

    recent = data.get("recent") or []
    if recent:
        first_date = recent[-1].get("created_at", "")[:10]
        last_date = recent[0].get("created_at", "")[:10]
        if first_date and last_date and first_date != last_date:
            console.print()
            console.print(f"  [bold]Date range:[/bold]     {first_date} – {last_date}")

    console.print()
