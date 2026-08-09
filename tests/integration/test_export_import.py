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
    """Patch AudioSegment and uniqueness recompute so tests don't need ffmpeg."""
    import meowdb.cli.commands.import_cmd as mod

    monkeypatch.setattr(mod, "AudioSegment", _FakeAudioSegment)
    monkeypatch.setattr(mod, "update_library_uniqueness", lambda db, ids: None)


def _write_wav(path: Path, silent_wav_bytes: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(silent_wav_bytes)


def _insert_sound(db: MeowDB, wav_path: Path, mp3_path: Path, animal_id: str | None = None) -> str:
    """Insert a minimal sound record and return its ID."""
    if animal_id is None:
        animal_id = db.get_animals()[0]["id"]
    sound_id = str(uuid.uuid4())
    db.import_sound(
        sound_id,
        {
            "timestamp": "2026-01-01T00:00:00",
            "duration_ms": 1000,
            "labels": ["tag1"],
            "title": "Test sound",
            "play_count": 3,
            "last_played": None,
            "created_at": "2026-01-01T00:00:00",
            "waveform_data": [0.1, 0.2, 0.3],
            "peak_dbfs": -3.0,
            "species_energy_ratio": 4.5,
            "recorded_at": None,
            "upvote_count": 1,
            "downvote_count": 0,
        },
        str(wav_path),
        str(mp3_path),
        animal_id,
    )
    return sound_id


@pytest.mark.integration
def test_export_empty_library(cli_runner: CliRunner, db_path: Path, tmp_path: Path) -> None:
    out = tmp_path / "out.zip"
    result = cli_runner.invoke(main, ["export", str(out), "--db-path", str(db_path)])
    assert result.exit_code == 0, result.output
    assert out.exists()
    with zipfile.ZipFile(out) as zf:
        manifest = json.loads(zf.read(_MANIFEST_PATH))
    assert manifest["format_version"] == 2
    assert "animals" in manifest
    assert manifest["sound_count"] == 0
    assert manifest["sounds"] == []


@pytest.mark.integration
def test_export_includes_sound_wav_and_metadata(
    cli_runner: CliRunner, db_path: Path, tmp_path: Path, silent_wav_bytes: bytes
) -> None:
    wav = tmp_path / "wav" / "test.wav"
    mp3 = tmp_path / "mp3" / "test.mp3"
    _write_wav(wav, silent_wav_bytes)
    mp3.parent.mkdir(parents=True, exist_ok=True)
    mp3.write_bytes(b"")

    db = MeowDB(db_path)
    sound_id = _insert_sound(db, wav, mp3)
    animal_id = db.get_animals()[0]["id"]
    db.close()

    out = tmp_path / "out.zip"
    result = cli_runner.invoke(main, ["export", str(out), "--db-path", str(db_path)])
    assert result.exit_code == 0, result.output

    with zipfile.ZipFile(out) as zf:
        manifest = json.loads(zf.read(_MANIFEST_PATH))
        names = zf.namelist()

    assert manifest["format_version"] == 2
    assert len(manifest["animals"]) >= 1
    assert manifest["animals"][0]["id"] == animal_id
    assert manifest["sound_count"] == 1
    assert manifest["sounds"][0]["id"] == sound_id
    assert manifest["sounds"][0]["title"] == "Test sound"
    assert manifest["sounds"][0]["labels"] == ["tag1"]
    assert manifest["sounds"][0]["play_count"] == 3
    assert manifest["sounds"][0]["animal_id"] == animal_id
    assert f"meowdb-export/audio/{sound_id}.wav" in names


@pytest.mark.integration
def test_export_excludes_nonportable_fields(
    cli_runner: CliRunner, db_path: Path, tmp_path: Path, silent_wav_bytes: bytes
) -> None:
    wav = tmp_path / "wav" / "test.wav"
    mp3 = tmp_path / "mp3" / "test.mp3"
    _write_wav(wav, silent_wav_bytes)
    mp3.parent.mkdir(parents=True, exist_ok=True)
    mp3.write_bytes(b"")

    db = MeowDB(db_path)
    _insert_sound(db, wav, mp3)
    db.close()

    out = tmp_path / "out.zip"
    cli_runner.invoke(main, ["export", str(out), "--db-path", str(db_path)])

    with zipfile.ZipFile(out) as zf:
        sound = json.loads(zf.read(_MANIFEST_PATH))["sounds"][0]

    for field in (
        "wav_path",
        "mp3_path",
        "sound_fingerprint",
        "animal_uniqueness_score",
        "species_uniqueness_score",
        "ai_analysis",
    ):
        assert field not in sound, f"Non-portable field {field!r} should not be in manifest"


@pytest.mark.integration
def test_export_skips_missing_wav(cli_runner: CliRunner, db_path: Path, tmp_path: Path) -> None:
    db = MeowDB(db_path)
    _insert_sound(db, Path("/nonexistent/path.wav"), Path("/nonexistent/path.mp3"))
    db.close()

    out = tmp_path / "out.zip"
    result = cli_runner.invoke(main, ["export", str(out), "--db-path", str(db_path)])
    assert result.exit_code == 0
    with zipfile.ZipFile(out) as zf:
        manifest = json.loads(zf.read(_MANIFEST_PATH))
    assert manifest["sound_count"] == 0


@pytest.mark.integration
def test_import_adds_sounds_v1_format(
    monkeypatch: pytest.MonkeyPatch,
    cli_runner: CliRunner,
    db_path: Path,
    tmp_path: Path,
    silent_wav_bytes: bytes,
) -> None:
    """v1 archive (meows key + cat_energy_ratio) imports to the default animal with field remapped."""
    archive = tmp_path / "export.zip"
    sound_id = str(uuid.uuid4())
    manifest = {
        "format_version": 1,
        "meow_count": 1,
        "meows": [
            {
                "id": sound_id,
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
        zf.writestr(f"meowdb-export/audio/{sound_id}.wav", silent_wav_bytes)

    wav_dir = tmp_path / "wav"
    mp3_dir = tmp_path / "mp3"
    import meowdb.cli.commands.import_cmd as import_mod

    monkeypatch.setattr(import_mod, "WAV_DIR", wav_dir)
    monkeypatch.setattr(import_mod, "MP3_DIR", mp3_dir)

    result = cli_runner.invoke(main, ["import", str(archive), "--db-path", str(db_path)])
    assert result.exit_code == 0, result.output

    db = MeowDB(db_path)
    sound = db.get_by_id(sound_id)
    default_animal = db.get_animals()[0]
    db.close()

    assert sound is not None
    assert sound["title"] == "Imported meow"
    assert sound["labels"] == ["imported"]
    assert sound["play_count"] == 5
    # v1: all sounds assigned to the first/default animal
    assert sound["animal_id"] == default_animal["id"]
    # cat_energy_ratio remapped to species_energy_ratio
    assert sound["species_energy_ratio"] == pytest.approx(3.5)
    assert (wav_dir / f"{sound_id}.wav").exists()
    assert (mp3_dir / f"{sound_id}.mp3").exists()


@pytest.mark.integration
def test_import_skip_conflict(
    monkeypatch: pytest.MonkeyPatch,
    cli_runner: CliRunner,
    db_path: Path,
    tmp_path: Path,
    silent_wav_bytes: bytes,
) -> None:
    # Pre-populate DB with the same sound ID
    wav = tmp_path / "existing.wav"
    mp3 = tmp_path / "existing.mp3"
    _write_wav(wav, silent_wav_bytes)
    mp3.write_bytes(b"")
    db = MeowDB(db_path)
    sound_id = _insert_sound(db, wav, mp3)
    db.close()

    archive = tmp_path / "export.zip"
    manifest = {
        "format_version": 1,
        "meow_count": 1,
        "meows": [
            {
                "id": sound_id,
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
        zf.writestr(f"meowdb-export/audio/{sound_id}.wav", silent_wav_bytes)

    import meowdb.cli.commands.import_cmd as import_mod

    monkeypatch.setattr(import_mod, "WAV_DIR", tmp_path / "wav")
    monkeypatch.setattr(import_mod, "MP3_DIR", tmp_path / "mp3")

    result = cli_runner.invoke(
        main, ["import", str(archive), "--on-conflict", "skip", "--db-path", str(db_path)]
    )
    assert result.exit_code == 0

    db = MeowDB(db_path)
    sound = db.get_by_id(sound_id)
    db.close()
    assert sound is not None
    # Title should still be the original, not "Should be skipped"
    assert sound["title"] == "Test sound"


@pytest.mark.integration
def test_import_new_ids(
    monkeypatch: pytest.MonkeyPatch,
    cli_runner: CliRunner,
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

    result = cli_runner.invoke(
        main, ["import", str(archive), "--on-conflict", "new-ids", "--db-path", str(db_path)]
    )
    assert result.exit_code == 0

    db = MeowDB(db_path)
    # Original ID should not exist
    assert db.get_by_id(original_id) is None
    # But one sound with the right title should
    sounds = db.get_all(limit=10)
    db.close()
    assert len(sounds) == 1
    assert sounds[0]["title"] == "New ID test"
    assert sounds[0]["id"] != original_id


@pytest.mark.integration
def test_import_invalid_zip(cli_runner: CliRunner, db_path: Path, tmp_path: Path) -> None:
    bad_file = tmp_path / "notazip.zip"
    bad_file.write_bytes(b"this is not a zip file")
    result = cli_runner.invoke(main, ["import", str(bad_file), "--db-path", str(db_path)])
    assert result.exit_code != 0


@pytest.mark.integration
def test_import_missing_manifest(cli_runner: CliRunner, db_path: Path, tmp_path: Path) -> None:
    archive = tmp_path / "nomanifest.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("some-other-file.txt", "hello")
    result = cli_runner.invoke(main, ["import", str(archive), "--db-path", str(db_path)])
    assert result.exit_code != 0


@pytest.mark.integration
def test_round_trip(
    monkeypatch: pytest.MonkeyPatch,
    cli_runner: CliRunner,
    tmp_path: Path,
    silent_wav_bytes: bytes,
) -> None:
    """Export from one DB, import into another — metadata and animal assignment are preserved."""
    src_db_path = tmp_path / "src.sqlite"
    dst_db_path = tmp_path / "dst.sqlite"

    wav = tmp_path / "src_wav" / "test.wav"
    mp3 = tmp_path / "src_mp3" / "test.mp3"
    _write_wav(wav, silent_wav_bytes)
    mp3.parent.mkdir(parents=True, exist_ok=True)
    mp3.write_bytes(b"")

    src_db = MeowDB(src_db_path)
    sound_id = _insert_sound(src_db, wav, mp3)
    src_db.close()

    archive = tmp_path / "export.zip"
    result = cli_runner.invoke(main, ["export", str(archive), "--db-path", str(src_db_path)])
    assert result.exit_code == 0, result.output

    dst_wav_dir = tmp_path / "dst_wav"
    dst_mp3_dir = tmp_path / "dst_mp3"
    import meowdb.cli.commands.import_cmd as import_mod

    monkeypatch.setattr(import_mod, "WAV_DIR", dst_wav_dir)
    monkeypatch.setattr(import_mod, "MP3_DIR", dst_mp3_dir)

    result = cli_runner.invoke(main, ["import", str(archive), "--db-path", str(dst_db_path)])
    assert result.exit_code == 0, result.output

    dst_db = MeowDB(dst_db_path)
    sound = dst_db.get_by_id(sound_id)
    dst_animals = dst_db.get_animals()
    dst_db.close()

    assert sound is not None
    assert sound["id"] == sound_id
    assert sound["title"] == "Test sound"
    assert sound["labels"] == ["tag1"]
    assert sound["play_count"] == 3
    assert sound["upvote_count"] == 1
    # Sound must be assigned to an animal in the destination DB
    assert any(a["id"] == sound["animal_id"] for a in dst_animals)
    assert (dst_wav_dir / f"{sound_id}.wav").exists()
    assert (dst_mp3_dir / f"{sound_id}.mp3").exists()


@pytest.mark.integration
def test_round_trip_multi_animal(
    monkeypatch: pytest.MonkeyPatch,
    cli_runner: CliRunner,
    tmp_path: Path,
    silent_wav_bytes: bytes,
) -> None:
    """Multi-animal export→import preserves both animals and their sound assignments."""
    src_db_path = tmp_path / "src.sqlite"
    dst_db_path = tmp_path / "dst.sqlite"

    src_db = MeowDB(src_db_path)
    squishy_id = src_db.get_animals()[0]["id"]  # auto-seeded Squishy/cat
    buddy_id = src_db.add_animal("Buddy", "dog")

    wav1 = tmp_path / "cat.wav"
    wav2 = tmp_path / "dog.wav"
    mp3_stub = tmp_path / "stub.mp3"
    _write_wav(wav1, silent_wav_bytes)
    _write_wav(wav2, silent_wav_bytes)
    mp3_stub.write_bytes(b"")

    cat_sound_id = _insert_sound(src_db, wav1, mp3_stub, squishy_id)
    dog_sound_id = _insert_sound(src_db, wav2, mp3_stub, buddy_id)
    src_db.close()

    archive = tmp_path / "export.zip"
    result = cli_runner.invoke(main, ["export", str(archive), "--db-path", str(src_db_path)])
    assert result.exit_code == 0, result.output

    dst_wav_dir = tmp_path / "dst_wav"
    dst_mp3_dir = tmp_path / "dst_mp3"
    import meowdb.cli.commands.import_cmd as import_mod

    monkeypatch.setattr(import_mod, "WAV_DIR", dst_wav_dir)
    monkeypatch.setattr(import_mod, "MP3_DIR", dst_mp3_dir)

    result = cli_runner.invoke(main, ["import", str(archive), "--db-path", str(dst_db_path)])
    assert result.exit_code == 0, result.output

    dst_db = MeowDB(dst_db_path)
    animals = dst_db.get_animals()
    animal_by_name = {a["name"]: a for a in animals}

    assert "Squishy" in animal_by_name
    assert "Buddy" in animal_by_name
    assert animal_by_name["Squishy"]["species"] == "cat"
    assert animal_by_name["Buddy"]["species"] == "dog"

    cat_sound = dst_db.get_by_id(cat_sound_id)
    dog_sound = dst_db.get_by_id(dog_sound_id)
    assert cat_sound is not None
    assert dog_sound is not None
    assert cat_sound["animal_id"] == animal_by_name["Squishy"]["id"]
    assert dog_sound["animal_id"] == animal_by_name["Buddy"]["id"]
    dst_db.close()


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


def _insert_photo(db: MeowDB, photos_dir: Path, animal_id: str | None = None) -> str:
    if animal_id is None:
        animal_id = db.get_animals()[0]["id"]
    photo_id = str(uuid.uuid4())
    filename = f"{photo_id}.webp"
    _make_webp(photos_dir / filename)
    db.import_photo(photo_id, filename, animal_id, "2026-01-01T00:00:00", False, None)
    return photo_id


@pytest.mark.integration
def test_export_includes_photos(
    monkeypatch: pytest.MonkeyPatch,
    cli_runner: CliRunner,
    db_path: Path,
    tmp_path: Path,
    silent_wav_bytes: bytes,
) -> None:
    photos_dir = tmp_path / "photos"
    import meowdb.cli.commands.export_cmd as export_mod

    monkeypatch.setattr(export_mod, "PHOTOS_DIR", photos_dir)

    db = MeowDB(db_path)
    photo_id = _insert_photo(db, photos_dir)
    default_animal_id = db.get_animals()[0]["id"]
    db.close()

    out = tmp_path / "out.zip"
    result = cli_runner.invoke(
        main, ["export", str(out), "--include-photos", "--db-path", str(db_path)]
    )
    assert result.exit_code == 0, result.output

    with zipfile.ZipFile(out) as zf:
        manifest = json.loads(zf.read(_MANIFEST_PATH))
        names = zf.namelist()

    assert "photos" in manifest
    assert len(manifest["photos"]) == 1
    assert manifest["photos"][0]["id"] == photo_id
    assert manifest["photos"][0]["animal_id"] == default_animal_id
    assert f"meowdb-export/photos/{photo_id}.webp" in names


@pytest.mark.integration
def test_export_without_flag_omits_photos(
    monkeypatch: pytest.MonkeyPatch,
    cli_runner: CliRunner,
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
    cli_runner.invoke(main, ["export", str(out), "--db-path", str(db_path)])

    with zipfile.ZipFile(out) as zf:
        manifest = json.loads(zf.read(_MANIFEST_PATH))
        names = zf.namelist()

    assert "photos" not in manifest
    assert not any(n.startswith("meowdb-export/photos/") for n in names)


@pytest.mark.integration
def test_import_photos_round_trip(
    monkeypatch: pytest.MonkeyPatch,
    cli_runner: CliRunner,
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
    result = cli_runner.invoke(
        main, ["export", str(archive), "--include-photos", "--db-path", str(src_db_path)]
    )
    assert result.exit_code == 0, result.output

    result = cli_runner.invoke(
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
    cli_runner: CliRunner,
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
    cli_runner.invoke(main, ["export", str(archive), "--include-photos", "--db-path", str(db_path)])
    result = cli_runner.invoke(
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
    cli_runner: CliRunner,
    db_path: Path,
    tmp_path: Path,
    silent_wav_bytes: bytes,
) -> None:
    """--include-photos on an archive that was exported without photos warns gracefully."""
    import meowdb.cli.commands.import_cmd as import_mod

    monkeypatch.setattr(import_mod, "WAV_DIR", tmp_path / "wav")
    monkeypatch.setattr(import_mod, "MP3_DIR", tmp_path / "mp3")
    monkeypatch.setattr(import_mod, "PHOTOS_DIR", tmp_path / "photos")

    # Build a sounds-only v1 archive (no photos key in manifest)
    archive = tmp_path / "sounds_only.zip"
    manifest = {
        "format_version": 1,
        "meow_count": 0,
        "meows": [],
    }
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(_MANIFEST_PATH, json.dumps(manifest))

    result = cli_runner.invoke(
        main, ["import", str(archive), "--include-photos", "--db-path", str(db_path)]
    )
    assert result.exit_code == 0
    assert "does not contain photos" in result.output


# ---------------------------------------------------------------------------
# Import hardening tests (path-traversal, corrupt audio, unsafe IDs)
# ---------------------------------------------------------------------------

_EMPTY_SOUND: dict = {
    "timestamp": "",
    "duration_ms": 100,
    "labels": [],
    "title": None,
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


@pytest.mark.integration
def test_import_traversal_sound_id_rejected(
    monkeypatch: pytest.MonkeyPatch,
    cli_runner: CliRunner,
    db_path: Path,
    tmp_path: Path,
) -> None:
    """A manifest entry with a path-traversal sound ID is skipped; nothing written to disk."""
    import meowdb.cli.commands.import_cmd as import_mod

    wav_dir = tmp_path / "wav"
    mp3_dir = tmp_path / "mp3"
    monkeypatch.setattr(import_mod, "WAV_DIR", wav_dir)
    monkeypatch.setattr(import_mod, "MP3_DIR", mp3_dir)

    archive = tmp_path / "export.zip"
    manifest = {
        "format_version": 1,
        "meow_count": 1,
        "meows": [{"id": "../../evil", **_EMPTY_SOUND}],
    }
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(_MANIFEST_PATH, json.dumps(manifest))

    result = cli_runner.invoke(main, ["import", str(archive), "--db-path", str(db_path)])
    assert result.exit_code == 0, result.output

    # Traversal ID rejected — no DB record created
    db = MeowDB(db_path)
    assert db.get_count() == 0
    db.close()

    # No WAV file written inside WAV_DIR
    if wav_dir.exists():
        assert list(wav_dir.glob("*.wav")) == []


@pytest.mark.integration
def test_import_traversal_photo_filename_rejected(
    monkeypatch: pytest.MonkeyPatch,
    cli_runner: CliRunner,
    db_path: Path,
    tmp_path: Path,
) -> None:
    """A manifest photo with a path-traversal filename is skipped; nothing written outside PHOTOS_DIR."""
    import meowdb.cli.commands.import_cmd as import_mod

    photos_dir = tmp_path / "photos"
    monkeypatch.setattr(import_mod, "WAV_DIR", tmp_path / "wav")
    monkeypatch.setattr(import_mod, "MP3_DIR", tmp_path / "mp3")
    monkeypatch.setattr(import_mod, "PHOTOS_DIR", photos_dir)

    archive = tmp_path / "export.zip"
    manifest = {
        "format_version": 1,
        "meow_count": 0,
        "meows": [],
        "photos": [
            {
                "id": str(uuid.uuid4()),
                "animal_id": None,
                "filename": "../etc/passwd.webp",
                "created_at": "2026-01-01T00:00:00",
                "is_default": False,
                "updated_at": None,
            }
        ],
    }
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(_MANIFEST_PATH, json.dumps(manifest))

    result = cli_runner.invoke(
        main, ["import", str(archive), "--include-photos", "--db-path", str(db_path)]
    )
    assert result.exit_code == 0, result.output

    # Photo skipped — no DB record
    db = MeowDB(db_path)
    assert db.get_photos() == []
    db.close()

    # No file written at the escaped path
    escaped = tmp_path / "etc" / "passwd.webp"
    assert not escaped.exists()

    # Nothing inside photos_dir either
    if photos_dir.exists():
        assert list(photos_dir.glob("*.webp")) == []


@pytest.mark.integration
def test_import_corrupt_wav_skipped(
    monkeypatch: pytest.MonkeyPatch,
    cli_runner: CliRunner,
    db_path: Path,
    tmp_path: Path,
    silent_wav_bytes: bytes,
) -> None:
    """Corrupt WAV entry is skipped with no artifacts on disk; valid sibling entry still imports."""
    import meowdb.cli.commands.import_cmd as import_mod

    wav_dir = tmp_path / "wav"
    mp3_dir = tmp_path / "mp3"
    monkeypatch.setattr(import_mod, "WAV_DIR", wav_dir)
    monkeypatch.setattr(import_mod, "MP3_DIR", mp3_dir)

    corrupt_id = str(uuid.uuid4())
    valid_id = str(uuid.uuid4())

    archive = tmp_path / "export.zip"
    manifest = {
        "format_version": 1,
        "meow_count": 2,
        "meows": [
            {"id": corrupt_id, **_EMPTY_SOUND},
            {"id": valid_id, **_EMPTY_SOUND},
        ],
    }
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(_MANIFEST_PATH, json.dumps(manifest))
        zf.writestr(f"meowdb-export/audio/{corrupt_id}.wav", b"\xff" * 100)
        zf.writestr(f"meowdb-export/audio/{valid_id}.wav", silent_wav_bytes)

    # Override the autouse AudioSegment stub: fail only for the corrupt entry's path.
    corrupt_wav_path = str(wav_dir / f"{corrupt_id}.wav")

    class _SelectiveAudioSegment:
        @staticmethod
        def from_wav(path: str) -> _SelectiveAudioSegment:
            if path == corrupt_wav_path:
                raise Exception("Unreadable audio")
            return _SelectiveAudioSegment()

        def export(self, path: str, **kwargs: object) -> None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(b"\x00")

    monkeypatch.setattr(import_mod, "AudioSegment", _SelectiveAudioSegment)

    result = cli_runner.invoke(main, ["import", str(archive), "--db-path", str(db_path)])
    assert result.exit_code == 0, result.output

    # Corrupt entry: no .wav on disk, no .mp3, no DB record
    assert not (wav_dir / f"{corrupt_id}.wav").exists()
    assert not (mp3_dir / f"{corrupt_id}.mp3").exists()
    db = MeowDB(db_path)
    assert db.get_by_id(corrupt_id) is None

    # Valid sibling entry: imported successfully
    assert (wav_dir / f"{valid_id}.wav").exists()
    assert (mp3_dir / f"{valid_id}.mp3").exists()
    assert db.get_by_id(valid_id) is not None
    db.close()


@pytest.mark.integration
def test_import_unsafe_sound_ids_rejected(
    monkeypatch: pytest.MonkeyPatch,
    cli_runner: CliRunner,
    db_path: Path,
    tmp_path: Path,
) -> None:
    """Empty string, single-dot, and double-dot IDs are each rejected; no files written."""
    import meowdb.cli.commands.import_cmd as import_mod

    wav_dir = tmp_path / "wav"
    mp3_dir = tmp_path / "mp3"
    monkeypatch.setattr(import_mod, "WAV_DIR", wav_dir)
    monkeypatch.setattr(import_mod, "MP3_DIR", mp3_dir)

    archive = tmp_path / "export.zip"
    manifest = {
        "format_version": 1,
        "meow_count": 3,
        "meows": [
            {"id": "", **_EMPTY_SOUND},
            {"id": ".", **_EMPTY_SOUND},
            {"id": "..", **_EMPTY_SOUND},
        ],
    }
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(_MANIFEST_PATH, json.dumps(manifest))

    result = cli_runner.invoke(main, ["import", str(archive), "--db-path", str(db_path)])
    assert result.exit_code == 0, result.output

    # All three unsafe IDs rejected — nothing in DB
    db = MeowDB(db_path)
    assert db.get_count() == 0
    db.close()

    # No WAV files written
    if wav_dir.exists():
        assert list(wav_dir.glob("*.wav")) == []


# ---------------------------------------------------------------------------
# Export / import in S3 mode
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_export_s3_backed_library_downloads_from_bucket(
    monkeypatch: pytest.MonkeyPatch,
    cli_runner: CliRunner,
    db_path: Path,
    tmp_path: Path,
    silent_wav_bytes: bytes,
    s3_state,
) -> None:
    """Export downloads WAV and photo bytes from S3 when no local files are present."""

    _BUCKET = "test-meowdb"

    # s3_state already patched config.S3_BUCKET and created the bucket.
    s3 = s3_state

    import meowdb.cli.commands.export_cmd as export_mod

    photos_dir = tmp_path / "photos"
    monkeypatch.setattr(export_mod, "PHOTOS_DIR", photos_dir)

    # Seed DB with S3-backed sound
    sound_id = str(uuid.uuid4())
    db = MeowDB(db_path)
    animal_id = db.get_animals()[0]["id"]
    db.import_sound(
        sound_id,
        {
            "timestamp": "2026-01-01T00:00:00",
            "duration_ms": 1000,
            "labels": [],
            "title": "S3 export test",
            "play_count": 0,
            "last_played": None,
            "created_at": "2026-01-01T00:00:00",
            "waveform_data": [],
            "peak_dbfs": None,
            "species_energy_ratio": None,
            "recorded_at": None,
            "upvote_count": 0,
            "downvote_count": 0,
        },
        f"audio/wav/{sound_id}.wav",  # S3 key stored as wav_path
        f"audio/mp3/{sound_id}.mp3",
        animal_id,
    )
    # Seed S3-backed photo
    photo_id = str(uuid.uuid4())
    photo_filename = f"{photo_id}.webp"
    _make_webp(photos_dir / "ignored.webp")  # ensure photos_dir exists but no actual file
    photos_dir.mkdir(parents=True, exist_ok=True)
    db.import_photo(photo_id, photo_filename, animal_id, "2026-01-01T00:00:00", False, None)
    db.close()

    # Put objects in mock S3
    s3.put_object(Bucket=_BUCKET, Key=f"audio/wav/{sound_id}.wav", Body=silent_wav_bytes)
    photo_bytes = b"RIFF\x1a\x00\x00\x00WEBPVP8 \x0e\x00\x00\x00\x30\x01\x00\x9d\x01\x2a\x01\x00\x01\x00\x02\x00\x34\x25\x9f"
    s3.put_object(Bucket=_BUCKET, Key=f"photos/{photo_filename}", Body=photo_bytes)

    out = tmp_path / "out.zip"
    result = cli_runner.invoke(
        main, ["export", str(out), "--include-photos", "--db-path", str(db_path)]
    )
    assert result.exit_code == 0, result.output

    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        arc_wav = zf.read(f"meowdb-export/audio/{sound_id}.wav")
        arc_photo = zf.read(f"meowdb-export/photos/{photo_filename}")

    assert f"meowdb-export/audio/{sound_id}.wav" in names
    assert f"meowdb-export/photos/{photo_filename}" in names
    assert arc_wav == silent_wav_bytes
    assert arc_photo == photo_bytes


@pytest.mark.integration
def test_import_s3_mode_uploads_to_bucket_and_clears_local(
    monkeypatch: pytest.MonkeyPatch,
    cli_runner: CliRunner,
    db_path: Path,
    tmp_path: Path,
    silent_wav_bytes: bytes,
    s3_state,
) -> None:
    """Import in S3 mode uploads WAV+MP3 to the bucket and removes local copies."""
    _BUCKET = "test-meowdb"
    s3 = s3_state

    sound_id = str(uuid.uuid4())
    archive = tmp_path / "export.zip"
    manifest = {
        "format_version": 1,
        "meow_count": 1,
        "meows": [
            {
                "id": sound_id,
                "timestamp": "2026-01-01T00:00:00",
                "duration_ms": 1000,
                "labels": [],
                "title": "S3 import test",
                "play_count": 0,
                "last_played": None,
                "created_at": "2026-01-01T00:00:00",
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
        zf.writestr(f"meowdb-export/audio/{sound_id}.wav", silent_wav_bytes)

    wav_dir = tmp_path / "wav"
    mp3_dir = tmp_path / "mp3"
    import meowdb.cli.commands.import_cmd as import_mod

    monkeypatch.setattr(import_mod, "WAV_DIR", wav_dir)
    monkeypatch.setattr(import_mod, "MP3_DIR", mp3_dir)

    result = cli_runner.invoke(main, ["import", str(archive), "--db-path", str(db_path)])
    assert result.exit_code == 0, result.output

    # Objects in S3 at derived keys
    bucket_keys = [o["Key"] for o in s3.list_objects_v2(Bucket=_BUCKET).get("Contents", [])]
    assert f"audio/wav/{sound_id}.wav" in bucket_keys
    assert f"audio/mp3/{sound_id}.mp3" in bucket_keys

    # DB paths are S3 keys
    db = MeowDB(db_path)
    sound = db.get_by_id(sound_id)
    db.close()
    assert sound is not None
    assert sound["wav_path"] == f"audio/wav/{sound_id}.wav"
    assert sound["mp3_path"] == f"audio/mp3/{sound_id}.mp3"

    # Local copies removed
    assert not (wav_dir / f"{sound_id}.wav").exists()
    assert not (mp3_dir / f"{sound_id}.mp3").exists()


@pytest.mark.integration
def test_import_replace_conflict_deletes_old_s3_objects(
    monkeypatch: pytest.MonkeyPatch,
    cli_runner: CliRunner,
    db_path: Path,
    tmp_path: Path,
    silent_wav_bytes: bytes,
    s3_state,
) -> None:
    """--on-conflict replace removes the old S3 objects for the displaced sound."""
    _BUCKET = "test-meowdb"
    s3 = s3_state

    existing_id = str(uuid.uuid4())

    # Pre-populate DB with the meow already pointing at S3 keys
    old_wav_content = b"OLD-WAV-BYTES"
    old_mp3_content = b"OLD-MP3-BYTES"
    s3.put_object(Bucket=_BUCKET, Key=f"audio/wav/{existing_id}.wav", Body=old_wav_content)
    s3.put_object(Bucket=_BUCKET, Key=f"audio/mp3/{existing_id}.mp3", Body=old_mp3_content)

    db = MeowDB(db_path)
    animal_id = db.get_animals()[0]["id"]
    db.import_sound(
        existing_id,
        {
            "timestamp": "2026-01-01T00:00:00",
            "duration_ms": 500,
            "labels": [],
            "title": "Old sound",
            "play_count": 0,
            "last_played": None,
            "created_at": "2026-01-01T00:00:00",
            "waveform_data": [],
            "peak_dbfs": None,
            "species_energy_ratio": None,
            "recorded_at": None,
            "upvote_count": 0,
            "downvote_count": 0,
        },
        f"audio/wav/{existing_id}.wav",  # S3 key stored as wav_path
        f"audio/mp3/{existing_id}.mp3",
        animal_id,
    )
    db.close()

    # Build archive with same sound ID but different WAV bytes
    archive = tmp_path / "replace.zip"
    manifest = {
        "format_version": 1,
        "meow_count": 1,
        "meows": [
            {
                "id": existing_id,
                "timestamp": "2026-06-01T00:00:00",
                "duration_ms": 1000,
                "labels": ["replaced"],
                "title": "Replacement sound",
                "play_count": 0,
                "last_played": None,
                "created_at": "2026-06-01T00:00:00",
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
        zf.writestr(f"meowdb-export/audio/{existing_id}.wav", silent_wav_bytes)

    wav_dir = tmp_path / "wav"
    mp3_dir = tmp_path / "mp3"
    import meowdb.cli.commands.import_cmd as import_mod

    monkeypatch.setattr(import_mod, "WAV_DIR", wav_dir)
    monkeypatch.setattr(import_mod, "MP3_DIR", mp3_dir)

    result = cli_runner.invoke(
        main,
        ["import", str(archive), "--on-conflict", "replace", "--db-path", str(db_path)],
    )
    assert result.exit_code == 0, result.output

    # Old content is gone — new WAV was uploaded (different bytes)
    new_wav = s3.get_object(Bucket=_BUCKET, Key=f"audio/wav/{existing_id}.wav")["Body"].read()
    assert new_wav == silent_wav_bytes  # replaced content, not old_wav_content

    # DB updated
    db2 = MeowDB(db_path)
    sound = db2.get_by_id(existing_id)
    db2.close()
    assert sound is not None
    assert sound["title"] == "Replacement sound"
