from __future__ import annotations

import json
import uuid
import zipfile

from pathlib import Path

import pytest

from click.testing import CliRunner

from meowdb.cli import main
from meowdb.db import MeowDB

_MANIFEST_PATH = "meowdb-export/manifest.json"


class _FakeAudioSegment:
    """Stub that avoids needing ffmpeg in CI."""

    @staticmethod
    def from_wav(path: str) -> _FakeAudioSegment:
        return _FakeAudioSegment()

    def export(self, path: str, **kwargs: object) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(b"\x00")


@pytest.fixture(autouse=True)
def _mock_pydub(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch AudioSegment in import_cmd so tests don't need ffmpeg."""
    import meowdb.cli.commands.import_cmd as mod

    monkeypatch.setattr(mod, "AudioSegment", _FakeAudioSegment)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.sqlite"


def _write_wav(path: Path, silent_wav_bytes: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(silent_wav_bytes)


def _insert_meow(db: MeowDB, wav_path: Path, mp3_path: Path) -> str:
    """Insert a minimal meow record and return its ID."""
    meow_id = str(uuid.uuid4())
    db.import_meow(
        meow_id,
        {
            "timestamp": "2026-01-01T00:00:00",
            "duration_ms": 1000,
            "labels": ["tag1"],
            "title": "Test meow",
            "play_count": 3,
            "last_played": None,
            "created_at": "2026-01-01T00:00:00",
            "waveform_data": [0.1, 0.2, 0.3],
            "peak_dbfs": -3.0,
            "cat_energy_ratio": 4.5,
            "recorded_at": None,
            "upvote_count": 1,
            "downvote_count": 0,
        },
        str(wav_path),
        str(mp3_path),
    )
    return meow_id


@pytest.mark.integration
def test_export_empty_library(runner: CliRunner, db_path: Path, tmp_path: Path) -> None:
    out = tmp_path / "out.zip"
    result = runner.invoke(main, ["export", str(out), "--db-path", str(db_path)])
    assert result.exit_code == 0, result.output
    assert out.exists()
    with zipfile.ZipFile(out) as zf:
        manifest = json.loads(zf.read(_MANIFEST_PATH))
    assert manifest["format_version"] == 1
    assert manifest["meow_count"] == 0
    assert manifest["meows"] == []


@pytest.mark.integration
def test_export_includes_meow_wav_and_metadata(
    runner: CliRunner, db_path: Path, tmp_path: Path, silent_wav_bytes: bytes
) -> None:
    wav = tmp_path / "wav" / "test.wav"
    mp3 = tmp_path / "mp3" / "test.mp3"
    _write_wav(wav, silent_wav_bytes)
    mp3.parent.mkdir(parents=True, exist_ok=True)
    mp3.write_bytes(b"")

    db = MeowDB(db_path)
    meow_id = _insert_meow(db, wav, mp3)
    db.close()

    out = tmp_path / "out.zip"
    result = runner.invoke(main, ["export", str(out), "--db-path", str(db_path)])
    assert result.exit_code == 0, result.output

    with zipfile.ZipFile(out) as zf:
        manifest = json.loads(zf.read(_MANIFEST_PATH))
        names = zf.namelist()

    assert manifest["meow_count"] == 1
    assert manifest["meows"][0]["id"] == meow_id
    assert manifest["meows"][0]["title"] == "Test meow"
    assert manifest["meows"][0]["labels"] == ["tag1"]
    assert manifest["meows"][0]["play_count"] == 3
    assert f"meowdb-export/audio/{meow_id}.wav" in names


@pytest.mark.integration
def test_export_excludes_nonportable_fields(
    runner: CliRunner, db_path: Path, tmp_path: Path, silent_wav_bytes: bytes
) -> None:
    wav = tmp_path / "wav" / "test.wav"
    mp3 = tmp_path / "mp3" / "test.mp3"
    _write_wav(wav, silent_wav_bytes)
    mp3.parent.mkdir(parents=True, exist_ok=True)
    mp3.write_bytes(b"")

    db = MeowDB(db_path)
    _insert_meow(db, wav, mp3)
    db.close()

    out = tmp_path / "out.zip"
    runner.invoke(main, ["export", str(out), "--db-path", str(db_path)])

    with zipfile.ZipFile(out) as zf:
        meow = json.loads(zf.read(_MANIFEST_PATH))["meows"][0]

    for field in ("wav_path", "mp3_path", "meow_fingerprint", "uniqueness_score", "ai_analysis"):
        assert field not in meow, f"Non-portable field {field!r} should not be in manifest"


@pytest.mark.integration
def test_export_skips_missing_wav(runner: CliRunner, db_path: Path, tmp_path: Path) -> None:
    db = MeowDB(db_path)
    _insert_meow(db, Path("/nonexistent/path.wav"), Path("/nonexistent/path.mp3"))
    db.close()

    out = tmp_path / "out.zip"
    result = runner.invoke(main, ["export", str(out), "--db-path", str(db_path)])
    assert result.exit_code == 0
    with zipfile.ZipFile(out) as zf:
        manifest = json.loads(zf.read(_MANIFEST_PATH))
    assert manifest["meow_count"] == 0


@pytest.mark.integration
def test_import_adds_meows(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
    db_path: Path,
    tmp_path: Path,
    silent_wav_bytes: bytes,
) -> None:
    # Build an export archive manually
    archive = tmp_path / "export.zip"
    meow_id = str(uuid.uuid4())
    manifest = {
        "format_version": 1,
        "meow_count": 1,
        "meows": [
            {
                "id": meow_id,
                "timestamp": "2026-01-01T00:00:00",
                "duration_ms": 1000,
                "labels": ["imported"],
                "title": "Imported meow",
                "play_count": 5,
                "last_played": None,
                "created_at": "2026-01-01T00:00:00",
                "waveform_data": [0.5],
                "peak_dbfs": -6.0,
                "cat_energy_ratio": 3.5,
                "recorded_at": None,
                "upvote_count": 2,
                "downvote_count": 0,
            }
        ],
    }
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(_MANIFEST_PATH, json.dumps(manifest))
        zf.writestr(f"meowdb-export/audio/{meow_id}.wav", silent_wav_bytes)

    wav_dir = tmp_path / "wav"
    mp3_dir = tmp_path / "mp3"
    import meowdb.cli.commands.import_cmd as import_mod

    monkeypatch.setattr(import_mod, "WAV_DIR", wav_dir)
    monkeypatch.setattr(import_mod, "MP3_DIR", mp3_dir)

    result = runner.invoke(main, ["import", str(archive), "--db-path", str(db_path)])
    assert result.exit_code == 0, result.output

    db = MeowDB(db_path)
    meow = db.get_by_id(meow_id)
    db.close()

    assert meow is not None
    assert meow["title"] == "Imported meow"
    assert meow["labels"] == ["imported"]
    assert meow["play_count"] == 5
    assert (wav_dir / f"{meow_id}.wav").exists()
    assert (mp3_dir / f"{meow_id}.mp3").exists()


@pytest.mark.integration
def test_import_skip_conflict(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
    db_path: Path,
    tmp_path: Path,
    silent_wav_bytes: bytes,
) -> None:
    # Pre-populate DB with the same meow ID
    wav = tmp_path / "existing.wav"
    mp3 = tmp_path / "existing.mp3"
    _write_wav(wav, silent_wav_bytes)
    mp3.write_bytes(b"")
    db = MeowDB(db_path)
    meow_id = _insert_meow(db, wav, mp3)
    db.close()

    archive = tmp_path / "export.zip"
    manifest = {
        "format_version": 1,
        "meow_count": 1,
        "meows": [
            {
                "id": meow_id,
                "timestamp": "",
                "duration_ms": 500,
                "labels": [],
                "title": "Should be skipped",
                "play_count": 0,
                "last_played": None,
                "created_at": "",
                "waveform_data": [],
                "peak_dbfs": None,
                "cat_energy_ratio": None,
                "recorded_at": None,
                "upvote_count": 0,
                "downvote_count": 0,
            }
        ],
    }
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(_MANIFEST_PATH, json.dumps(manifest))
        zf.writestr(f"meowdb-export/audio/{meow_id}.wav", silent_wav_bytes)

    import meowdb.cli.commands.import_cmd as import_mod

    monkeypatch.setattr(import_mod, "WAV_DIR", tmp_path / "wav")
    monkeypatch.setattr(import_mod, "MP3_DIR", tmp_path / "mp3")

    result = runner.invoke(
        main, ["import", str(archive), "--on-conflict", "skip", "--db-path", str(db_path)]
    )
    assert result.exit_code == 0

    db = MeowDB(db_path)
    meow = db.get_by_id(meow_id)
    db.close()
    assert meow is not None
    # Title should still be the original, not "Should be skipped"
    assert meow["title"] == "Test meow"


@pytest.mark.integration
def test_import_new_ids(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
    db_path: Path,
    tmp_path: Path,
    silent_wav_bytes: bytes,
) -> None:
    original_id = str(uuid.uuid4())
    archive = tmp_path / "export.zip"
    manifest = {
        "format_version": 1,
        "meow_count": 1,
        "meows": [
            {
                "id": original_id,
                "timestamp": "",
                "duration_ms": 1000,
                "labels": [],
                "title": "New ID test",
                "play_count": 0,
                "last_played": None,
                "created_at": "",
                "waveform_data": [],
                "peak_dbfs": None,
                "cat_energy_ratio": None,
                "recorded_at": None,
                "upvote_count": 0,
                "downvote_count": 0,
            }
        ],
    }
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(_MANIFEST_PATH, json.dumps(manifest))
        zf.writestr(f"meowdb-export/audio/{original_id}.wav", silent_wav_bytes)

    wav_dir = tmp_path / "wav"
    mp3_dir = tmp_path / "mp3"
    import meowdb.cli.commands.import_cmd as import_mod

    monkeypatch.setattr(import_mod, "WAV_DIR", wav_dir)
    monkeypatch.setattr(import_mod, "MP3_DIR", mp3_dir)

    result = runner.invoke(
        main, ["import", str(archive), "--on-conflict", "new-ids", "--db-path", str(db_path)]
    )
    assert result.exit_code == 0

    db = MeowDB(db_path)
    # Original ID should not exist
    assert db.get_by_id(original_id) is None
    # But one meow with the right title should
    meows = db.get_all(limit=10)
    db.close()
    assert len(meows) == 1
    assert meows[0]["title"] == "New ID test"
    assert meows[0]["id"] != original_id


@pytest.mark.integration
def test_import_invalid_zip(runner: CliRunner, db_path: Path, tmp_path: Path) -> None:
    bad_file = tmp_path / "notazip.zip"
    bad_file.write_bytes(b"this is not a zip file")
    result = runner.invoke(main, ["import", str(bad_file), "--db-path", str(db_path)])
    assert result.exit_code != 0


@pytest.mark.integration
def test_import_missing_manifest(runner: CliRunner, db_path: Path, tmp_path: Path) -> None:
    archive = tmp_path / "nomanifest.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("some-other-file.txt", "hello")
    result = runner.invoke(main, ["import", str(archive), "--db-path", str(db_path)])
    assert result.exit_code != 0


@pytest.mark.integration
def test_round_trip(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
    tmp_path: Path,
    silent_wav_bytes: bytes,
) -> None:
    """Export from one DB, import into another — metadata is preserved."""
    src_db_path = tmp_path / "src.sqlite"
    dst_db_path = tmp_path / "dst.sqlite"

    # Set up source library with one meow
    wav = tmp_path / "src_wav" / "test.wav"
    mp3 = tmp_path / "src_mp3" / "test.mp3"
    _write_wav(wav, silent_wav_bytes)
    mp3.parent.mkdir(parents=True, exist_ok=True)
    mp3.write_bytes(b"")

    src_db = MeowDB(src_db_path)
    meow_id = _insert_meow(src_db, wav, mp3)
    src_db.close()

    # Export
    archive = tmp_path / "export.zip"
    result = runner.invoke(main, ["export", str(archive), "--db-path", str(src_db_path)])
    assert result.exit_code == 0, result.output

    # Import into fresh DB
    dst_wav_dir = tmp_path / "dst_wav"
    dst_mp3_dir = tmp_path / "dst_mp3"
    import meowdb.cli.commands.import_cmd as import_mod

    monkeypatch.setattr(import_mod, "WAV_DIR", dst_wav_dir)
    monkeypatch.setattr(import_mod, "MP3_DIR", dst_mp3_dir)

    result = runner.invoke(main, ["import", str(archive), "--db-path", str(dst_db_path)])
    assert result.exit_code == 0, result.output

    dst_db = MeowDB(dst_db_path)
    meow = dst_db.get_by_id(meow_id)
    dst_db.close()

    assert meow is not None
    assert meow["id"] == meow_id
    assert meow["title"] == "Test meow"
    assert meow["labels"] == ["tag1"]
    assert meow["play_count"] == 3
    assert meow["upvote_count"] == 1
    assert (dst_wav_dir / f"{meow_id}.wav").exists()
    assert (dst_mp3_dir / f"{meow_id}.mp3").exists()


# ---------------------------------------------------------------------------
# Photo export / import tests
# ---------------------------------------------------------------------------


def _make_webp(path: Path) -> None:
    """Write a minimal valid WebP file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Minimal 1x1 white WebP (lossy, 26 bytes)
    path.write_bytes(
        b"RIFF\x1a\x00\x00\x00WEBPVP8 \x0e\x00\x00\x00\x30\x01\x00\x9d"
        b"\x01\x2a\x01\x00\x01\x00\x02\x00\x34\x25\x9f"
    )


def _insert_photo(db: MeowDB, photos_dir: Path) -> str:
    photo_id = str(uuid.uuid4())
    filename = f"{photo_id}.webp"
    _make_webp(photos_dir / filename)
    db.import_photo(photo_id, filename, "2026-01-01T00:00:00", False, None)
    return photo_id


@pytest.mark.integration
def test_export_includes_photos(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
    db_path: Path,
    tmp_path: Path,
    silent_wav_bytes: bytes,
) -> None:
    photos_dir = tmp_path / "photos"
    import meowdb.cli.commands.export_cmd as export_mod

    monkeypatch.setattr(export_mod, "PHOTOS_DIR", photos_dir)

    db = MeowDB(db_path)
    photo_id = _insert_photo(db, photos_dir)
    db.close()

    out = tmp_path / "out.zip"
    result = runner.invoke(
        main, ["export", str(out), "--include-photos", "--db-path", str(db_path)]
    )
    assert result.exit_code == 0, result.output

    with zipfile.ZipFile(out) as zf:
        manifest = json.loads(zf.read(_MANIFEST_PATH))
        names = zf.namelist()

    assert "photos" in manifest
    assert len(manifest["photos"]) == 1
    assert manifest["photos"][0]["id"] == photo_id
    assert f"meowdb-export/photos/{photo_id}.webp" in names


@pytest.mark.integration
def test_export_without_flag_omits_photos(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
    db_path: Path,
    tmp_path: Path,
) -> None:
    photos_dir = tmp_path / "photos"
    import meowdb.cli.commands.export_cmd as export_mod

    monkeypatch.setattr(export_mod, "PHOTOS_DIR", photos_dir)

    db = MeowDB(db_path)
    _insert_photo(db, photos_dir)
    db.close()

    out = tmp_path / "out.zip"
    runner.invoke(main, ["export", str(out), "--db-path", str(db_path)])

    with zipfile.ZipFile(out) as zf:
        manifest = json.loads(zf.read(_MANIFEST_PATH))
        names = zf.namelist()

    assert "photos" not in manifest
    assert not any(n.startswith("meowdb-export/photos/") for n in names)


@pytest.mark.integration
def test_import_photos_round_trip(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
    tmp_path: Path,
    silent_wav_bytes: bytes,
) -> None:
    src_db_path = tmp_path / "src.sqlite"
    dst_db_path = tmp_path / "dst.sqlite"
    src_photos_dir = tmp_path / "src_photos"
    dst_photos_dir = tmp_path / "dst_photos"

    import meowdb.cli.commands.export_cmd as export_mod
    import meowdb.cli.commands.import_cmd as import_mod

    monkeypatch.setattr(export_mod, "PHOTOS_DIR", src_photos_dir)
    monkeypatch.setattr(import_mod, "PHOTOS_DIR", dst_photos_dir)
    monkeypatch.setattr(import_mod, "WAV_DIR", tmp_path / "wav")
    monkeypatch.setattr(import_mod, "MP3_DIR", tmp_path / "mp3")

    src_db = MeowDB(src_db_path)
    photo_id = _insert_photo(src_db, src_photos_dir)
    src_db.close()

    archive = tmp_path / "export.zip"
    result = runner.invoke(
        main, ["export", str(archive), "--include-photos", "--db-path", str(src_db_path)]
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(
        main, ["import", str(archive), "--include-photos", "--db-path", str(dst_db_path)]
    )
    assert result.exit_code == 0, result.output

    dst_db = MeowDB(dst_db_path)
    photo = dst_db.get_photo(photo_id)
    dst_db.close()

    assert photo is not None
    assert photo["id"] == photo_id
    assert (dst_photos_dir / f"{photo_id}.webp").exists()


@pytest.mark.integration
def test_import_photos_skip_conflict(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "test.sqlite"
    photos_dir = tmp_path / "photos"

    import meowdb.cli.commands.export_cmd as export_mod
    import meowdb.cli.commands.import_cmd as import_mod

    monkeypatch.setattr(export_mod, "PHOTOS_DIR", photos_dir)
    monkeypatch.setattr(import_mod, "PHOTOS_DIR", photos_dir)
    monkeypatch.setattr(import_mod, "WAV_DIR", tmp_path / "wav")
    monkeypatch.setattr(import_mod, "MP3_DIR", tmp_path / "mp3")

    db = MeowDB(db_path)
    photo_id = _insert_photo(db, photos_dir)
    db.close()

    # Export then re-import with skip (default)
    archive = tmp_path / "export.zip"
    runner.invoke(main, ["export", str(archive), "--include-photos", "--db-path", str(db_path)])
    result = runner.invoke(
        main,
        [
            "import",
            str(archive),
            "--include-photos",
            "--on-conflict",
            "skip",
            "--db-path",
            str(db_path),
        ],
    )
    assert result.exit_code == 0

    # Should still be exactly one photo
    db = MeowDB(db_path)
    photos = db.get_photos()
    db.close()
    assert len(photos) == 1
    assert photos[0]["id"] == photo_id


@pytest.mark.integration
def test_import_photos_warns_when_archive_has_no_photos(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
    db_path: Path,
    tmp_path: Path,
    silent_wav_bytes: bytes,
) -> None:
    """--include-photos on an archive that was exported without photos warns gracefully."""
    import meowdb.cli.commands.import_cmd as import_mod

    monkeypatch.setattr(import_mod, "WAV_DIR", tmp_path / "wav")
    monkeypatch.setattr(import_mod, "MP3_DIR", tmp_path / "mp3")
    monkeypatch.setattr(import_mod, "PHOTOS_DIR", tmp_path / "photos")

    # Build a meow-only archive (no photos key in manifest)
    archive = tmp_path / "meows_only.zip"
    manifest = {
        "format_version": 1,
        "meow_count": 0,
        "meows": [],
    }
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(_MANIFEST_PATH, json.dumps(manifest))

    result = runner.invoke(
        main, ["import", str(archive), "--include-photos", "--db-path", str(db_path)]
    )
    assert result.exit_code == 0
    assert "does not contain photos" in result.output
