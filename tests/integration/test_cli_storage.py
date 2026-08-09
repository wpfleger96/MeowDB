from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import boto3
import pytest

from click.testing import CliRunner
from moto import mock_aws

from meowdb import config
from meowdb.cli import main
from meowdb.db import MeowDB
from meowdb.storage import _reset_s3_client

_BUCKET = "test-meowdb"
_REGION = "us-east-1"


@pytest.fixture
def s3_cli(monkeypatch, tmp_path):
    """Activate moto, patch config and CLI module-level dir constants.

    Yields (s3_boto3_client, tmp_path, db_path).  The DB is empty; callers
    seed it as needed before invoking the CLI.
    """
    wav_dir = tmp_path / "wav"
    mp3_dir = tmp_path / "mp3"
    photos_dir = tmp_path / "photos"
    wav_dir.mkdir()
    mp3_dir.mkdir()
    photos_dir.mkdir()

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", _REGION)
    monkeypatch.setattr(config, "S3_BUCKET", _BUCKET)
    monkeypatch.setattr(config, "S3_REGION", _REGION)
    monkeypatch.setattr(config, "S3_ACCESS_KEY_ID", None)
    monkeypatch.setattr(config, "S3_SECRET_ACCESS_KEY", None)
    monkeypatch.setattr(config, "S3_ENDPOINT_URL", None)

    with (
        mock_aws(),
        patch("meowdb.cli.groups.storage.WAV_DIR", wav_dir),
        patch("meowdb.cli.groups.storage.MP3_DIR", mp3_dir),
        patch("meowdb.cli.groups.storage.PHOTOS_DIR", photos_dir),
    ):
        _reset_s3_client()
        s3 = boto3.client("s3", region_name=_REGION)
        s3.create_bucket(Bucket=_BUCKET)
        yield s3, tmp_path, tmp_path / "test.sqlite"
    _reset_s3_client()


def _seed_local_meow(db: MeowDB, wav_dir: Path, mp3_dir: Path) -> tuple[str, Path, Path]:
    """Insert a meow row with absolute local paths and create stub audio files.

    Returns (meow_id, wav_path, mp3_path).
    """
    wav_file = wav_dir / "test.wav"
    mp3_file = mp3_dir / "test.mp3"
    wav_file.write_bytes(b"RIFF" + b"\x00" * 36)
    mp3_file.write_bytes(b"\xff\xfb" + b"\x00" * 50)

    meow_id = db.add(
        {
            "timestamp": "2026-01-01T00:00:00",
            "duration_ms": 1000,
            "labels": [],
            "wav_path": str(wav_file),
            "mp3_path": str(mp3_file),
            "waveform_data": [],
            "peak_dbfs": -10.0,
            "cat_energy_ratio": 2.5,
        }
    )
    return meow_id, wav_file, mp3_file


# ---------------------------------------------------------------------------
# migrate-to-s3 — basic migration
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_migrate_to_s3_uploads_files_and_updates_db_paths(s3_cli):
    s3, tmp_path, db_path = s3_cli
    wav_dir = tmp_path / "wav"
    mp3_dir = tmp_path / "mp3"

    db = MeowDB(db_path)
    meow_id, wav_file, mp3_file = _seed_local_meow(db, wav_dir, mp3_dir)
    db.close()

    runner = CliRunner()
    result = runner.invoke(main, ["storage", "migrate-to-s3", "--db-path", str(db_path)])
    assert result.exit_code == 0, result.output

    # Both audio objects are in the bucket
    bucket_keys = [o["Key"] for o in s3.list_objects_v2(Bucket=_BUCKET).get("Contents", [])]
    assert f"audio/wav/{meow_id}.wav" in bucket_keys
    assert f"audio/mp3/{meow_id}.mp3" in bucket_keys

    # DB paths updated to S3 keys
    db2 = MeowDB(db_path)
    meow = db2.get_by_id(meow_id)
    assert meow is not None
    assert meow["wav_path"] == f"audio/wav/{meow_id}.wav"
    assert meow["mp3_path"] == f"audio/mp3/{meow_id}.mp3"
    db2.close()

    # Local files still on disk (no --delete-local)
    assert wav_file.exists()
    assert mp3_file.exists()


# ---------------------------------------------------------------------------
# migrate-to-s3 — idempotency
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_migrate_to_s3_is_idempotent_for_already_migrated_meows(s3_cli):
    s3, tmp_path, db_path = s3_cli
    wav_dir = tmp_path / "wav"
    mp3_dir = tmp_path / "mp3"

    db = MeowDB(db_path)
    meow_id, _wav, _mp3 = _seed_local_meow(db, wav_dir, mp3_dir)
    db.close()

    runner = CliRunner()

    # First run migrates the meow
    result1 = runner.invoke(main, ["storage", "migrate-to-s3", "--db-path", str(db_path)])
    assert result1.exit_code == 0
    assert "1 meow(s) migrated" in result1.output

    # Second run finds S3 keys in DB (no leading "/") and skips them
    result2 = runner.invoke(main, ["storage", "migrate-to-s3", "--db-path", str(db_path)])
    assert result2.exit_code == 0
    assert "1 skipped" in result2.output
    assert "0 meow(s) migrated" in result2.output


# ---------------------------------------------------------------------------
# migrate-to-s3 --delete-local
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_migrate_to_s3_delete_local_removes_audio_files(s3_cli):
    s3, tmp_path, db_path = s3_cli
    wav_dir = tmp_path / "wav"
    mp3_dir = tmp_path / "mp3"

    db = MeowDB(db_path)
    _meow_id, wav_file, mp3_file = _seed_local_meow(db, wav_dir, mp3_dir)
    db.close()

    runner = CliRunner()
    result = runner.invoke(
        main, ["storage", "migrate-to-s3", "--delete-local", "--db-path", str(db_path)]
    )
    assert result.exit_code == 0, result.output

    # Local files removed
    assert not wav_file.exists()
    assert not mp3_file.exists()


# ---------------------------------------------------------------------------
# migrate-to-s3 --dry-run
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_migrate_to_s3_dry_run_makes_no_changes(s3_cli):
    s3, tmp_path, db_path = s3_cli
    wav_dir = tmp_path / "wav"
    mp3_dir = tmp_path / "mp3"

    db = MeowDB(db_path)
    meow_id, wav_file, mp3_file = _seed_local_meow(db, wav_dir, mp3_dir)
    original_wav_path = db.get_by_id(meow_id)["wav_path"]  # type: ignore[index]
    db.close()

    runner = CliRunner()
    result = runner.invoke(
        main, ["storage", "migrate-to-s3", "--dry-run", "--db-path", str(db_path)]
    )
    assert result.exit_code == 0, result.output

    # No S3 objects created
    objects = s3.list_objects_v2(Bucket=_BUCKET).get("Contents", [])
    assert objects == []

    # DB paths unchanged
    db2 = MeowDB(db_path)
    meow = db2.get_by_id(meow_id)
    assert meow is not None
    assert meow["wav_path"] == original_wav_path
    db2.close()

    # Local files still present
    assert wav_file.exists()
    assert mp3_file.exists()


# ---------------------------------------------------------------------------
# restore-from-s3
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_restore_from_s3_downloads_and_restores_db_paths(s3_cli):
    s3, tmp_path, db_path = s3_cli
    wav_dir = tmp_path / "wav"
    mp3_dir = tmp_path / "mp3"

    wav_content = b"RIFF" + b"\x00" * 36
    mp3_content = b"\xff\xfb" + b"\x00" * 50

    # Seed DB with S3 keys (simulates post-migration state)
    db = MeowDB(db_path)
    meow_id = db.add(
        {
            "timestamp": "2026-01-01T00:00:00",
            "duration_ms": 1000,
            "labels": [],
            "wav_path": "audio/wav/restore-id.wav",
            "mp3_path": "audio/mp3/restore-id.mp3",
            "waveform_data": [],
            "peak_dbfs": -10.0,
            "cat_energy_ratio": 2.5,
        }
    )
    # Update DB to hold our known S3 keys
    db.update_meow_paths(meow_id, f"audio/wav/{meow_id}.wav", f"audio/mp3/{meow_id}.mp3")
    db.close()

    # Pre-populate bucket objects
    s3.put_object(Bucket=_BUCKET, Key=f"audio/wav/{meow_id}.wav", Body=wav_content)
    s3.put_object(Bucket=_BUCKET, Key=f"audio/mp3/{meow_id}.mp3", Body=mp3_content)

    runner = CliRunner()
    result = runner.invoke(main, ["storage", "restore-from-s3", "--db-path", str(db_path)])
    assert result.exit_code == 0, result.output

    # Files written to the (patched) WAV/MP3 dirs
    assert (wav_dir / f"{meow_id}.wav").read_bytes() == wav_content
    assert (mp3_dir / f"{meow_id}.mp3").read_bytes() == mp3_content

    # DB paths restored to absolute local paths
    db2 = MeowDB(db_path)
    meow = db2.get_by_id(meow_id)
    assert meow is not None
    assert meow["wav_path"] == str(wav_dir / f"{meow_id}.wav")
    assert meow["mp3_path"] == str(mp3_dir / f"{meow_id}.mp3")
    db2.close()


# ---------------------------------------------------------------------------
# migrate-to-s3 with an mp3-less meow
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_migrate_to_s3_mp3less_meow_wav_migrates_mp3_path_stays_empty(s3_cli):
    """A meow with an absolute wav_path but empty mp3_path migrates only the WAV.

    The DB mp3_path must stay empty — no phantom 'audio/mp3/...' key created.
    """
    s3, tmp_path, db_path = s3_cli
    wav_dir = tmp_path / "wav"

    wav_file = wav_dir / "silent.wav"
    wav_file.write_bytes(b"RIFF" + b"\x00" * 36)

    db = MeowDB(db_path)
    meow_id = db.add(
        {
            "timestamp": "2026-01-01T00:00:00",
            "duration_ms": 1000,
            "labels": [],
            "wav_path": str(wav_file),
            "mp3_path": "",
            "waveform_data": [],
            "peak_dbfs": -10.0,
            "cat_energy_ratio": 2.5,
        }
    )
    db.close()

    runner = CliRunner()
    result = runner.invoke(main, ["storage", "migrate-to-s3", "--db-path", str(db_path)])
    assert result.exit_code == 0, result.output

    # WAV is in the bucket
    bucket_keys = [o["Key"] for o in s3.list_objects_v2(Bucket=_BUCKET).get("Contents", [])]
    assert f"audio/wav/{meow_id}.wav" in bucket_keys

    # No phantom MP3 key
    assert f"audio/mp3/{meow_id}.mp3" not in bucket_keys

    # DB: wav updated to S3 key, mp3_path stays empty
    db2 = MeowDB(db_path)
    meow = db2.get_by_id(meow_id)
    assert meow is not None
    assert meow["wav_path"] == f"audio/wav/{meow_id}.wav"
    assert meow["mp3_path"] == ""
    db2.close()


# ---------------------------------------------------------------------------
# migrate-to-s3 resilience: per-item failures don't abort the whole batch
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_migrate_to_s3_continues_after_per_item_failure(s3_cli):
    """Deleting one meow's WAV before migration causes that item to fail.

    The command must complete (exit 0), report the failure in its summary,
    and fully migrate the other meow.
    """
    s3, tmp_path, db_path = s3_cli
    wav_dir = tmp_path / "wav"
    mp3_dir = tmp_path / "mp3"

    # meow1 — files exist, will migrate successfully
    wav1 = wav_dir / "m1.wav"
    mp3_1 = mp3_dir / "m1.mp3"
    wav1.write_bytes(b"RIFF" + b"\x00" * 36)
    mp3_1.write_bytes(b"\xff\xfb" + b"\x00" * 50)

    # meow2 — WAV deliberately deleted before migration
    wav2 = wav_dir / "m2.wav"
    mp3_2 = mp3_dir / "m2.mp3"
    wav2.write_bytes(b"RIFF" + b"\x00" * 36)
    mp3_2.write_bytes(b"\xff\xfb" + b"\x00" * 50)

    db = MeowDB(db_path)
    meow1_id = db.add(
        {
            "timestamp": "2026-01-01T00:00:00",
            "duration_ms": 1000,
            "labels": [],
            "wav_path": str(wav1),
            "mp3_path": str(mp3_1),
            "waveform_data": [],
            "peak_dbfs": -10.0,
            "cat_energy_ratio": 2.5,
        }
    )
    meow2_id = db.add(
        {
            "timestamp": "2026-01-02T00:00:00",
            "duration_ms": 500,
            "labels": [],
            "wav_path": str(wav2),
            "mp3_path": str(mp3_2),
            "waveform_data": [],
            "peak_dbfs": -12.0,
            "cat_energy_ratio": 1.5,
        }
    )
    db.close()

    # Delete meow2's WAV to force a FileNotFoundError during migration
    wav2.unlink()

    runner = CliRunner()
    result = runner.invoke(main, ["storage", "migrate-to-s3", "--db-path", str(db_path)])
    assert result.exit_code == 0, result.output
    assert "1 failed" in result.output

    # meow1 migrated successfully
    bucket_keys = [o["Key"] for o in s3.list_objects_v2(Bucket=_BUCKET).get("Contents", [])]
    assert f"audio/wav/{meow1_id}.wav" in bucket_keys
    assert f"audio/mp3/{meow1_id}.mp3" in bucket_keys

    db2 = MeowDB(db_path)
    m1 = db2.get_by_id(meow1_id)
    assert m1 is not None
    assert m1["wav_path"] == f"audio/wav/{meow1_id}.wav"

    # meow2 failed — DB path unchanged (still absolute)
    m2 = db2.get_by_id(meow2_id)
    assert m2 is not None
    assert m2["wav_path"] == str(wav2)  # unchanged
    db2.close()
