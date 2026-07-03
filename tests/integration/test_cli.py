from __future__ import annotations

from pathlib import Path

import pytest

from click.testing import CliRunner

from meowdb.cli import main


@pytest.mark.integration
def test_help_shows_all_commands(cli_runner: CliRunner) -> None:
    result = cli_runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    for cmd in ("ingest", "list", "play", "delete", "serve", "stats", "export", "import"):
        assert cmd in result.output


@pytest.mark.integration
def test_version(cli_runner: CliRunner) -> None:
    result = cli_runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "meowdb" in result.output


@pytest.mark.integration
def test_list_empty_db(cli_runner: CliRunner, db_path: Path) -> None:
    result = cli_runner.invoke(main, ["list", "--db-path", str(db_path)])
    assert result.exit_code == 0
    assert "No meows" in result.output


@pytest.mark.integration
def test_stats_empty_db(cli_runner: CliRunner, db_path: Path) -> None:
    result = cli_runner.invoke(main, ["stats", "--db-path", str(db_path)])
    assert result.exit_code == 0
    assert "No meows" in result.output


@pytest.mark.integration
def test_serve_help(cli_runner: CliRunner) -> None:
    result = cli_runner.invoke(main, ["serve", "--help"])
    assert result.exit_code == 0
    assert "--host" in result.output
    assert "--port" in result.output
    assert "--reload" in result.output


@pytest.mark.integration
def test_list_json_format(cli_runner: CliRunner, db_path: Path) -> None:
    result = cli_runner.invoke(main, ["list", "--format", "json", "--db-path", str(db_path)])
    assert result.exit_code == 0
    # Empty db → empty JSON array
    import json

    assert json.loads(result.output) == []


@pytest.mark.integration
def test_delete_not_found(cli_runner: CliRunner, db_path: Path) -> None:
    result = cli_runner.invoke(
        main, ["delete", "nonexistent-id", "--yes", "--db-path", str(db_path)]
    )
    assert result.exit_code != 0


@pytest.mark.integration
def test_ingest_help(cli_runner: CliRunner) -> None:
    result = cli_runner.invoke(main, ["ingest", "--help"])
    assert result.exit_code == 0
    assert "--dry-run" in result.output
    assert "--review" in result.output
