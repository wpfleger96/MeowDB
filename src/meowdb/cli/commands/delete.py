from __future__ import annotations

import sys

from pathlib import Path

import click

from meowdb.cli.helpers import build_context
from meowdb.cli.options import db_path_option
from meowdb.display import print_error, print_success


@click.command()
@click.argument("id")
@click.option("--force", is_flag=True, default=False, help="Skip confirmation prompt.")
@db_path_option
def delete(id: str, force: bool, db_path: str | None) -> None:
    """Delete a meow from the library."""
    ctx = build_context(Path(db_path) if db_path else None)

    meow = ctx.db.get_by_id(id)
    if meow is None:
        print_error(f"Meow not found: {id}")
        ctx.db.close()
        sys.exit(1)

    if not force:
        confirmed = click.confirm(f"Delete meow {id[:8]}?", default=False)
        if not confirmed:
            ctx.db.close()
            return

    # Remove audio files before deleting the db record
    for field in ("wav_path", "mp3_path"):
        file_path = meow.get(field)
        if file_path:
            p = Path(file_path)
            if p.exists():
                p.unlink()

    deleted = ctx.db.delete(id)
    ctx.db.close()

    if deleted:
        print_success(f"Deleted {id[:8]}")
    else:
        print_error(f"Failed to delete {id[:8]}")
        sys.exit(1)
