from __future__ import annotations

import click

db_path_option = click.option(
    "--db-path",
    type=click.Path(dir_okay=False),
    default=None,
    hidden=True,
    help="Override database path (for testing).",
)
