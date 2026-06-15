from __future__ import annotations

import click

from meowdb import __version__


@click.group()
@click.version_option(version=__version__, prog_name="meowdb")
def main() -> None:
    """MeowDB — a personal cat meow library."""


def _register_commands() -> None:
    from meowdb.cli.commands.delete import delete
    from meowdb.cli.commands.ingest import ingest
    from meowdb.cli.commands.list import list_meows
    from meowdb.cli.commands.play import play
    from meowdb.cli.commands.serve import serve
    from meowdb.cli.commands.stats import stats
    from meowdb.cli.groups.db import db

    main.add_command(delete)
    main.add_command(ingest)
    main.add_command(list_meows, name="list")
    main.add_command(play)
    main.add_command(serve)
    main.add_command(stats)
    main.add_command(db)


_register_commands()


def cli_entrypoint() -> None:
    main(complete_var="_MEOWDB_COMPLETE")
