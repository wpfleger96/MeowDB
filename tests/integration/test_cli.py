from __future__ import annotations

import json
import uuid

from pathlib import Path

import pytest

from click.testing import CliRunner

from meowdb.cli import main
from meowdb.db import MeowDB


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
    assert "No sounds" in result.output


@pytest.mark.integration
def test_stats_empty_db(cli_runner: CliRunner, db_path: Path) -> None:
    result = cli_runner.invoke(main, ["stats", "--db-path", str(db_path)])
    assert result.exit_code == 0
    assert "No sounds" in result.output


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
    assert "--animal" in result.output


@pytest.mark.integration
def test_list_animal_filter(cli_runner: CliRunner, db_path: Path) -> None:
    """list --animal <name> returns only sounds belonging to that animal."""
    db = MeowDB(db_path)
    squishy_id = db.get_animals()[0]["id"]
    buddy_id = db.add_animal("Buddy", "dog")

    def _add_sound(title: str, animal_id: str) -> None:
        db.import_sound(
            str(uuid.uuid4()),
            {
                "timestamp": "",
                "duration_ms": 500,
                "labels": [],
                "title": title,
                "play_count": 0,
                "last_played": None,
                "created_at": "",
                "waveform_data": [],
                "peak_dbfs": None,
                "species_energy_ratio": None,
                "recorded_at": None,
                "upvote_count": 0,
                "downvote_count": 0,
            },
            "/fake/path.wav",
            "/fake/path.mp3",
            animal_id,
        )

    _add_sound("Cat sound", squishy_id)
    _add_sound("Dog sound", buddy_id)
    db.close()

    result = cli_runner.invoke(
        main,
        ["list", "--animal", "Buddy", "--format", "json", "--db-path", str(db_path)],
    )
    assert result.exit_code == 0, result.output
    sounds = json.loads(result.output)
    assert len(sounds) == 1
    assert sounds[0]["title"] == "Dog sound"


@pytest.mark.integration
def test_ingest_unknown_animal_errors(cli_runner: CliRunner, db_path: Path, tmp_path: Path) -> None:
    """ingest --animal with an unknown name exits with a non-zero code."""
    dummy = tmp_path / "dummy.wav"
    dummy.write_bytes(b"\x00")
    result = cli_runner.invoke(
        main,
        [
            "ingest",
            str(dummy),
            "--animal",
            "NoSuchAnimal",
            "--no-review",
            "--db-path",
            str(db_path),
        ],
    )
    assert result.exit_code != 0
