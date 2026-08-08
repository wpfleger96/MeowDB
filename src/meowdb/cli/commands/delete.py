from __future__ import annotations

import sys

from pathlib import Path

import click

from meowdb.cli.helpers import build_context, die
from meowdb.cli.options import db_path_option
from meowdb.display import print_error, print_success


@click.command()
@click.argument("id")
@click.option("--force", is_flag=True, default=False, help="Skip confirmation prompt.")
@db_path_option
def delete(id: str, force: bool, db_path: str | None) -> None:
    """Delete a meow from the library."""
    ctx = build_context(db_path)

    meow = ctx.db.get_by_id(id)
    if meow is None:
        die(ctx, f"Meow not found: {id}")

    if not force:
        confirmed = click.confirm(f"Delete meow {id[:8]}?", default=False)
        if not confirmed:
            ctx.db.close()
            return

    # Remove audio files before deleting the db record
    from meowdb.storage import delete_from_s3_sync, is_s3_enabled

    for field in ("wav_path", "mp3_path"):
        value = meow.get(field)
        if not value:
            continue
        if is_s3_enabled() and not value.startswith("/"):
            delete_from_s3_sync(value)
        else:
            p = Path(value)
            if p.exists():
                p.unlink()

    deleted = ctx.db.delete(id)
    ctx.db.close()

    if deleted:
        print_success(f"Deleted {id[:8]}")
    else:
        print_error(f"Failed to delete {id[:8]}")
        sys.exit(1)
