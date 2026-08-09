from __future__ import annotations

import sqlite3
import uuid

from pathlib import Path

import pytest

from meowdb.db import MeowDB

# ---------------------------------------------------------------------------
# Old-schema DDL
# ---------------------------------------------------------------------------

# Original schema columns (present from the start, no ALTER TABLE needed)
_V0_MEOWS_BARE = """
CREATE TABLE meows (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    labels TEXT NOT NULL DEFAULT '[]',
    play_count INTEGER NOT NULL DEFAULT 0,
    last_played TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    wav_path TEXT NOT NULL,
    mp3_path TEXT NOT NULL,
    waveform_data TEXT NOT NULL DEFAULT '[]',
    peak_dbfs REAL,
    cat_energy_ratio REAL,
    ai_analysis TEXT,
    recorded_at TEXT,
    title TEXT
)
"""

# Full ALTER-era schema: original columns + everything added via ALTER TABLE
_V0_MEOWS_FULL = """
CREATE TABLE meows (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    labels TEXT NOT NULL DEFAULT '[]',
    play_count INTEGER NOT NULL DEFAULT 0,
    last_played TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    wav_path TEXT NOT NULL,
    mp3_path TEXT NOT NULL,
    waveform_data TEXT NOT NULL DEFAULT '[]',
    peak_dbfs REAL,
    cat_energy_ratio REAL,
    ai_analysis TEXT,
    recorded_at TEXT,
    title TEXT,
    meow_fingerprint TEXT,
    uniqueness_score REAL,
    upvote_count INTEGER NOT NULL DEFAULT 0,
    downvote_count INTEGER NOT NULL DEFAULT 0
)
"""

_V0_CAT_PHOTOS_BARE = """
CREATE TABLE cat_photos (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    is_default BOOLEAN NOT NULL DEFAULT 0
)
"""

_V0_CAT_PHOTOS_FULL = """
CREATE TABLE cat_photos (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    is_default BOOLEAN NOT NULL DEFAULT 0,
    updated_at TEXT
)
"""

_V0_INGEST_JOBS = """
CREATE TABLE ingest_jobs (
    id TEXT PRIMARY KEY,
    source_filename TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

_V0_INGEST_SEGMENTS = """
CREATE TABLE ingest_segments (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES ingest_jobs(id) ON DELETE CASCADE,
    index_in_job INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL,
    wav_path TEXT NOT NULL,
    waveform_data TEXT NOT NULL DEFAULT '[]',
    peak_dbfs REAL,
    cat_energy_ratio REAL,
    status TEXT NOT NULL DEFAULT 'pending'
)
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_v0_db(path: Path, *, full_schema: bool) -> dict[str, str]:
    """Create a v0 SQLite DB on disk with old meow-centric schema.

    Two meows are inserted: meow1 without a uniqueness_score, meow2 with
    uniqueness_score=0.85 (full_schema only, since the bare schema lacks the
    column). Also inserts one cat_photo, one ingest job, and one ingest segment.

    Returns a dict mapping logical name → inserted row id so tests can look up
    specific rows after migration.
    """
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(_V0_MEOWS_FULL if full_schema else _V0_MEOWS_BARE)
        conn.execute(_V0_CAT_PHOTOS_FULL if full_schema else _V0_CAT_PHOTOS_BARE)
        conn.execute(_V0_INGEST_JOBS)
        conn.execute(_V0_INGEST_SEGMENTS)

        ids = {k: str(uuid.uuid4()) for k in ("meow1", "meow2", "photo1", "job1", "seg1")}

        # meow1: no uniqueness_score (regardless of schema variant)
        conn.execute(
            "INSERT INTO meows (id, timestamp, duration_ms, labels, wav_path, mp3_path, waveform_data)"
            " VALUES (?, '2026-01-01T00:00:00', 1000, '[]', '/wav/m1.wav', '/mp3/m1.mp3', '[]')",
            (ids["meow1"],),
        )

        if full_schema:
            # meow2: uniqueness_score set — both score columns should mirror it after migration
            conn.execute(
                "INSERT INTO meows"
                " (id, timestamp, duration_ms, labels, wav_path, mp3_path, waveform_data, uniqueness_score)"
                " VALUES (?, '2026-01-02T00:00:00', 2000, '[]', '/wav/m2.wav', '/mp3/m2.mp3', '[]', 0.85)",
                (ids["meow2"],),
            )
        else:
            conn.execute(
                "INSERT INTO meows (id, timestamp, duration_ms, labels, wav_path, mp3_path, waveform_data)"
                " VALUES (?, '2026-01-02T00:00:00', 2000, '[]', '/wav/m2.wav', '/mp3/m2.mp3', '[]')",
                (ids["meow2"],),
            )

        conn.execute(
            "INSERT INTO cat_photos (id, filename) VALUES (?, 'kitty.jpg')",
            (ids["photo1"],),
        )
        conn.execute(
            "INSERT INTO ingest_jobs (id, source_filename) VALUES (?, 'recording.m4a')",
            (ids["job1"],),
        )
        conn.execute(
            "INSERT INTO ingest_segments"
            " (id, job_id, index_in_job, duration_ms, wav_path, cat_energy_ratio)"
            " VALUES (?, ?, 0, 800, '/wav/seg.wav', 1.8)",
            (ids["seg1"], ids["job1"]),
        )
        conn.commit()
    finally:
        conn.close()
    return ids


def _schema_columns(db_path: Path, table: str) -> set[str]:
    """Return the set of column names for a table in a SQLite file."""
    conn = sqlite3.connect(str(db_path))
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    finally:
        conn.close()


def _user_version(db_path: Path) -> int:
    conn = sqlite3.connect(str(db_path))
    try:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Tests: bare original schema (no ALTER-era optional columns)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_migration_bare_sounds_carried_over(tmp_path: Path) -> None:
    """Both meow rows migrate to sounds assigned to the auto-created Squishy animal."""
    db_path = tmp_path / "test.sqlite"
    ids = _build_v0_db(db_path, full_schema=False)

    db = MeowDB(db_path)
    try:
        # Exactly one animal created: Squishy
        animals = db.get_animals()
        assert len(animals) == 1
        squishy = animals[0]
        assert squishy["name"] == "Squishy"
        squishy_id = squishy["id"]

        # Both meows present as sounds, IDs preserved
        assert db.get_by_id(ids["meow1"]) is not None
        assert db.get_by_id(ids["meow2"]) is not None
        assert db.get_count() == 2

        # All sounds belong to Squishy
        for sid in (ids["meow1"], ids["meow2"]):
            sound = db.get_by_id(sid)
            assert sound is not None
            assert sound["animal_id"] == squishy_id

        # uniqueness_score absent in bare schema → both score columns NULL
        sound1 = db.get_by_id(ids["meow1"])
        assert sound1 is not None
        assert sound1["animal_uniqueness_score"] is None
        assert sound1["species_uniqueness_score"] is None
    finally:
        db.close()


@pytest.mark.unit
def test_migration_bare_photo_carried_over(tmp_path: Path) -> None:
    """cat_photos row migrates to animal_photos and is assigned to Squishy."""
    db_path = tmp_path / "test.sqlite"
    ids = _build_v0_db(db_path, full_schema=False)

    db = MeowDB(db_path)
    try:
        squishy_id = db.get_animals()[0]["id"]
        photos = db.get_photos()
        assert len(photos) == 1
        assert photos[0]["id"] == ids["photo1"]
        assert photos[0]["filename"] == "kitty.jpg"
        assert photos[0]["animal_id"] == squishy_id
    finally:
        db.close()


@pytest.mark.unit
def test_migration_bare_job_has_animal_id(tmp_path: Path) -> None:
    """Migrated ingest_job row has animal_id set to Squishy's id."""
    db_path = tmp_path / "test.sqlite"
    ids = _build_v0_db(db_path, full_schema=False)

    db = MeowDB(db_path)
    try:
        squishy_id = db.get_animals()[0]["id"]
        job = db.get_job(ids["job1"])
        assert job is not None
        assert job["animal_id"] == squishy_id
    finally:
        db.close()


@pytest.mark.unit
def test_migration_bare_segment_column_renamed(tmp_path: Path) -> None:
    """ingest_segments.cat_energy_ratio is renamed to species_energy_ratio."""
    db_path = tmp_path / "test.sqlite"
    _build_v0_db(db_path, full_schema=False)

    db = MeowDB(db_path)
    db.close()

    cols = _schema_columns(db_path, "ingest_segments")
    assert "species_energy_ratio" in cols
    assert "cat_energy_ratio" not in cols


@pytest.mark.unit
def test_migration_bare_backup_file_created(tmp_path: Path) -> None:
    """A .pre-v2-backup file is created next to the DB file during migration."""
    db_path = tmp_path / "test.sqlite"
    _build_v0_db(db_path, full_schema=False)

    db = MeowDB(db_path)
    db.close()

    assert Path(str(db_path) + ".pre-v2-backup").exists()


@pytest.mark.unit
def test_migration_bare_user_version_stamped(tmp_path: Path) -> None:
    """After migration, PRAGMA user_version == 2."""
    db_path = tmp_path / "test.sqlite"
    _build_v0_db(db_path, full_schema=False)

    db = MeowDB(db_path)
    db.close()

    assert _user_version(db_path) == 2


# ---------------------------------------------------------------------------
# Tests: full ALTER-era schema (includes uniqueness_score and updated_at)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_migration_full_uniqueness_score_propagates_to_both_columns(tmp_path: Path) -> None:
    """uniqueness_score from old meows is copied to both animal_ and species_ score columns."""
    db_path = tmp_path / "test.sqlite"
    ids = _build_v0_db(db_path, full_schema=True)

    db = MeowDB(db_path)
    try:
        # meow1 had no uniqueness_score set → both score columns remain NULL
        sound1 = db.get_by_id(ids["meow1"])
        assert sound1 is not None
        assert sound1["animal_uniqueness_score"] is None
        assert sound1["species_uniqueness_score"] is None

        # meow2 had uniqueness_score=0.85 → both columns carry that value
        sound2 = db.get_by_id(ids["meow2"])
        assert sound2 is not None
        assert sound2["animal_uniqueness_score"] == pytest.approx(0.85)
        assert sound2["species_uniqueness_score"] == pytest.approx(0.85)
    finally:
        db.close()


@pytest.mark.unit
def test_migration_full_cat_photos_updated_at_tolerated(tmp_path: Path) -> None:
    """Migration succeeds when cat_photos has the optional updated_at column."""
    db_path = tmp_path / "test.sqlite"
    _build_v0_db(db_path, full_schema=True)

    db = MeowDB(db_path)
    try:
        # The photo row is still present — migration did not crash on updated_at
        photos = db.get_photos()
        assert len(photos) == 1
        assert photos[0]["filename"] == "kitty.jpg"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Tests: idempotency and no-op cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_migration_reopen_is_noop(tmp_path: Path) -> None:
    """Opening a migrated DB a second time does not re-run migration or add animals."""
    db_path = tmp_path / "test.sqlite"
    _build_v0_db(db_path, full_schema=True)

    db1 = MeowDB(db_path)
    first_animal_id = db1.get_animals()[0]["id"]
    db1.close()

    db2 = MeowDB(db_path)
    animals = db2.get_animals()
    db2.close()

    assert len(animals) == 1
    assert animals[0]["id"] == first_animal_id


@pytest.mark.unit
def test_fresh_db_no_backup_file(tmp_path: Path) -> None:
    """A fresh DB (no meows table) never triggers migration and creates no backup file."""
    db_path = tmp_path / "fresh.sqlite"
    db = MeowDB(db_path)
    db.close()

    assert not Path(str(db_path) + ".pre-v2-backup").exists()


# ---------------------------------------------------------------------------
# Tests: missing optional tables (cat_photos_exists == False, ingest absent)
# ---------------------------------------------------------------------------


def _build_v0_db_no_cat_photos(path: Path) -> dict[str, str]:
    """Create a v0 DB with meows + ingest tables but NO cat_photos table.

    Returns a dict mapping logical name → inserted row id.
    """
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(_V0_MEOWS_FULL)
        conn.execute(_V0_INGEST_JOBS)
        conn.execute(_V0_INGEST_SEGMENTS)

        ids = {k: str(uuid.uuid4()) for k in ("meow1", "job1", "seg1")}

        conn.execute(
            "INSERT INTO meows (id, timestamp, duration_ms, labels, wav_path, mp3_path, waveform_data)"
            " VALUES (?, '2026-01-01T00:00:00', 1000, '[]', '/wav/m1.wav', '/mp3/m1.mp3', '[]')",
            (ids["meow1"],),
        )
        conn.execute(
            "INSERT INTO ingest_jobs (id, source_filename) VALUES (?, 'recording.m4a')",
            (ids["job1"],),
        )
        conn.execute(
            "INSERT INTO ingest_segments"
            " (id, job_id, index_in_job, duration_ms, wav_path, cat_energy_ratio)"
            " VALUES (?, ?, 0, 800, '/wav/seg.wav', 1.8)",
            (ids["seg1"], ids["job1"]),
        )
        conn.commit()
    finally:
        conn.close()
    return ids


def _build_v0_db_no_ingest(path: Path) -> dict[str, str]:
    """Create a v0 DB with meows + cat_photos but NO ingest_jobs or ingest_segments tables.

    Returns a dict mapping logical name → inserted row id.
    """
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(_V0_MEOWS_FULL)
        conn.execute(_V0_CAT_PHOTOS_FULL)

        ids = {k: str(uuid.uuid4()) for k in ("meow1", "photo1")}

        conn.execute(
            "INSERT INTO meows (id, timestamp, duration_ms, labels, wav_path, mp3_path, waveform_data)"
            " VALUES (?, '2026-01-01T00:00:00', 1000, '[]', '/wav/m1.wav', '/mp3/m1.mp3', '[]')",
            (ids["meow1"],),
        )
        conn.execute(
            "INSERT INTO cat_photos (id, filename) VALUES (?, 'kitty.jpg')",
            (ids["photo1"],),
        )
        conn.commit()
    finally:
        conn.close()
    return ids


@pytest.mark.unit
def test_migration_no_cat_photos_succeeds(tmp_path: Path) -> None:
    """Migration succeeds when cat_photos table is absent; sounds preserved, photos empty."""
    db_path = tmp_path / "test.sqlite"
    ids = _build_v0_db_no_cat_photos(db_path)

    db = MeowDB(db_path)
    try:
        # Exactly one animal created: Squishy
        animals = db.get_animals()
        assert len(animals) == 1
        squishy_id = animals[0]["id"]
        assert animals[0]["name"] == "Squishy"

        # The meow row migrated to sounds, ID preserved
        sound = db.get_by_id(ids["meow1"])
        assert sound is not None
        assert sound["animal_id"] == squishy_id
        assert db.get_count() == 1

        # No cat_photos existed → photo list is empty
        assert db.get_photos() == []
    finally:
        db.close()


@pytest.mark.unit
def test_migration_no_ingest_tables_succeeds(tmp_path: Path) -> None:
    """Migration succeeds when ingest_jobs and ingest_segments are absent; data preserved."""
    db_path = tmp_path / "test.sqlite"
    ids = _build_v0_db_no_ingest(db_path)

    db = MeowDB(db_path)
    try:
        # Migration did not crash — exactly one animal
        animals = db.get_animals()
        assert len(animals) == 1
        squishy_id = animals[0]["id"]

        # Sound migrated with preserved ID and animal assignment
        sound = db.get_by_id(ids["meow1"])
        assert sound is not None
        assert sound["animal_id"] == squishy_id

        # Photo migrated with preserved ID and animal assignment
        photos = db.get_photos()
        assert len(photos) == 1
        assert photos[0]["id"] == ids["photo1"]
        assert photos[0]["animal_id"] == squishy_id
        assert photos[0]["filename"] == "kitty.jpg"
    finally:
        db.close()


@pytest.mark.unit
def test_migration_succeeds_with_concurrent_reader(tmp_path: Path) -> None:
    """Migration completes even when another connection holds an open read transaction.

    Simulates a Litestream sidecar holding a permanent WAL read lock: the old
    checkpoint-based backup raised RuntimeError here; the online backup API must not.
    """
    db_path = tmp_path / "test.sqlite"
    ids = _build_v0_db(db_path, full_schema=False)

    # MeowDB sets journal_mode=WAL in __init__, but switching modes requires
    # exclusive access (no other readers). Switch to WAL now, before opening the
    # long-lived reader, so the MeowDB constructor's PRAGMA is a no-op idempotent
    # check rather than a mode change.
    pre = sqlite3.connect(str(db_path))
    pre.execute("PRAGMA journal_mode=WAL")
    pre.close()

    # Open the long-lived reader BEFORE creating WAL frames.  The reader's open
    # transaction blocks the auto-checkpoint that would otherwise run when the
    # write connection closes, ensuring WAL frames persist into the migration.
    # Without frames, wal_checkpoint(TRUNCATE) reports busy=0 even with an open
    # reader (nothing to checkpoint), so the old checkpoint-guard code path would
    # not have been exercised.
    reader = sqlite3.connect(str(db_path))
    reader.execute("BEGIN")
    reader.execute("SELECT * FROM meows").fetchall()

    # Commit a real write so WAL frames exist.  SQLite optimises away no-op
    # updates (e.g. "col = col"), so the value must actually change.  The
    # open reader prevents the auto-checkpoint that normally fires on
    # connection close, so the frames remain in the WAL when MeowDB.__init__
    # runs.
    stamp = sqlite3.connect(str(db_path))
    stamp.execute("UPDATE meows SET play_count = play_count + 1")
    stamp.commit()
    stamp.close()

    db: MeowDB | None = None
    try:
        # Must not raise even with the concurrent reader holding a WAL read lock.
        db = MeowDB(db_path)

        # Migration produced the expected data.
        animals = db.get_animals()
        assert len(animals) == 1
        assert animals[0]["name"] == "Squishy"

        assert db.get_count() == 2
        assert db.get_by_id(ids["meow1"]) is not None
        assert db.get_by_id(ids["meow2"]) is not None
    finally:
        if db is not None:
            db.close()
        reader.close()

    # The backup file exists and contains the original v0 rows.
    backup_path = Path(str(db_path) + ".pre-v2-backup")
    assert backup_path.exists()
    backup_conn = sqlite3.connect(str(backup_path))
    try:
        rows = backup_conn.execute("SELECT id FROM meows").fetchall()
        assert len(rows) == 2
    finally:
        backup_conn.close()
