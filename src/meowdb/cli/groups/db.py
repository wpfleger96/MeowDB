from __future__ import annotations

import sqlite3
import sys

from pathlib import Path

import click

from meowdb.cli.options import db_path_option
from meowdb.config import DB_PATH
from meowdb.display import print_error, print_info, print_success, print_warning


def _format_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024  # type: ignore[assignment]
    return f"{n:.1f} TB"


@click.group()
def db() -> None:
    """Database management tools."""


@db.command()
@db_path_option
def init(db_path: str | None) -> None:
    """Initialize the database (create tables if needed)."""
    from meowdb.db import MeowDB

    path = Path(db_path) if db_path else DB_PATH
    instance = MeowDB(path)
    instance.close()
    print_success(f"Database ready at {path}")


@db.command()
@db_path_option
def stats(db_path: str | None) -> None:
    """Show database statistics."""
    from meowdb.db import MeowDB

    path = Path(db_path) if db_path else DB_PATH
    if not path.exists():
        print_error(f"Database not found: {path}")
        sys.exit(1)

    instance = MeowDB(path)
    db_stats = instance.get_stats()
    count = db_stats["total_meows"]
    total_ms = db_stats["total_duration_ms"]
    avg_ms = db_stats["avg_duration_ms"]
    instance.close()

    size = path.stat().st_size
    total_sec = total_ms // 1000
    avg_sec = avg_ms / 1000

    print_info(f"Path:           {path}")
    print_info(f"File size:      {_format_bytes(size)}")
    print_info(f"Meows:          {count}")
    if count > 0:
        print_info(f"Total duration: {total_sec // 60}m {total_sec % 60}s")
        print_info(f"Avg duration:   {avg_sec:.1f}s")


@db.command()
@click.option("--force", is_flag=True, help="Skip confirmation prompt.")
@db_path_option
def vacuum(force: bool, db_path: str | None) -> None:
    """Compact the database file (SQLite VACUUM)."""
    path = Path(db_path) if db_path else DB_PATH
    if not path.exists():
        print_error(f"Database not found: {path}")
        sys.exit(1)

    size_before = path.stat().st_size
    print_info(f"Current size: {_format_bytes(size_before)}")

    if not force and not click.confirm("Run VACUUM?", default=True):
        return

    conn = sqlite3.connect(str(path))
    conn.execute("VACUUM")
    conn.close()

    size_after = path.stat().st_size
    saved = size_before - size_after
    print_success(
        f"Vacuumed: {_format_bytes(size_before)} → {_format_bytes(size_after)}"
        + (f" (saved {_format_bytes(saved)})" if saved > 0 else "")
    )


@db.command()
@click.option("--force", is_flag=True, help="Skip confirmation prompt.")
@db_path_option
def drop(force: bool, db_path: str | None) -> None:
    """Delete the database file permanently."""
    from meowdb.db import MeowDB

    path = Path(db_path) if db_path else DB_PATH
    if not path.exists():
        print_error(f"Database not found: {path}")
        sys.exit(1)

    instance = MeowDB(path)
    count = instance.get_count()
    instance.close()

    size = path.stat().st_size
    print_warning(f"This will permanently delete {count} meow(s) and the database file.")
    print_info(f"  File: {path}")
    print_info(f"  Size: {_format_bytes(size)}")

    if not force and not click.confirm("Are you sure?", default=False):
        return

    path.unlink()
    for ext in (".wal", ".shm"):
        sidecar = path.with_suffix(path.suffix + ext)
        if sidecar.exists():
            sidecar.unlink()

    print_success("Database deleted.")
