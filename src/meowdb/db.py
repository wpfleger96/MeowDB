from __future__ import annotations

import json
import shutil
import sqlite3
import threading
import uuid

from pathlib import Path

_CREATE_ANIMALS = """
CREATE TABLE IF NOT EXISTS animals (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    species TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

_CREATE_SOUNDS = """
CREATE TABLE IF NOT EXISTS sounds (
    id TEXT PRIMARY KEY,
    animal_id TEXT NOT NULL REFERENCES animals(id) ON DELETE CASCADE,
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
    species_energy_ratio REAL,
    ai_analysis TEXT,
    recorded_at TEXT,
    title TEXT,
    sound_fingerprint TEXT,
    animal_uniqueness_score REAL,
    species_uniqueness_score REAL,
    upvote_count INTEGER NOT NULL DEFAULT 0,
    downvote_count INTEGER NOT NULL DEFAULT 0
)
"""

_CREATE_ANIMAL_PHOTOS = """
CREATE TABLE IF NOT EXISTS animal_photos (
    id TEXT PRIMARY KEY,
    animal_id TEXT NOT NULL REFERENCES animals(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT,
    is_default BOOLEAN NOT NULL DEFAULT 0
)
"""

_CREATE_INGEST_JOBS = """
CREATE TABLE IF NOT EXISTS ingest_jobs (
    id TEXT PRIMARY KEY,
    source_filename TEXT NOT NULL,
    animal_id TEXT NOT NULL REFERENCES animals(id),
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

_CREATE_INGEST_SEGMENTS = """
CREATE TABLE IF NOT EXISTS ingest_segments (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES ingest_jobs(id) ON DELETE CASCADE,
    index_in_job INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL,
    wav_path TEXT NOT NULL,
    waveform_data TEXT NOT NULL DEFAULT '[]',
    peak_dbfs REAL,
    species_energy_ratio REAL,
    status TEXT NOT NULL DEFAULT 'pending'
)
"""

_SORT_MAP = {
    "newest": "created_at DESC, rowid DESC",
    "oldest": "created_at ASC, rowid ASC",
    "most_played": "play_count DESC, rowid DESC",
    "duration_asc": "duration_ms ASC, rowid ASC",
    "duration_desc": "duration_ms DESC, rowid DESC",
    "most_unique": "animal_uniqueness_score DESC, rowid DESC",
    "most_upvoted": "upvote_count DESC, rowid DESC",
    "most_downvoted": "downvote_count DESC, rowid DESC",
}


class MeowDB:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        # RLock (reentrant) so methods that call other methods (e.g. get_stats →
        # _count_labels) don't deadlock when both try to acquire the same lock.
        self._lock = threading.RLock()
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")

        # Run migration check before CREATE TABLE IF NOT EXISTS.
        # FK enforcement is intentionally OFF during migration so we can freely
        # drop/rename tables that reference each other.
        self._migrate_v0_to_v2()

        # Enable FK enforcement for all subsequent operations.
        self._conn.execute("PRAGMA foreign_keys = ON")

        self._conn.execute(_CREATE_ANIMALS)
        self._conn.execute(_CREATE_SOUNDS)
        self._conn.execute(_CREATE_ANIMAL_PHOTOS)
        self._conn.execute(_CREATE_INGEST_JOBS)
        self._conn.execute(_CREATE_INGEST_SEGMENTS)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sounds_created_at ON sounds(created_at DESC)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sounds_play_count ON sounds(play_count DESC)"
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_sounds_animal_id ON sounds(animal_id)")
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_animal_photos_animal_id ON animal_photos(animal_id)"
        )

        # Fresh DB: stamp version and seed Squishy.
        user_ver = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if user_ver == 0:
            self._conn.execute("PRAGMA user_version = 2")

        count = self._conn.execute("SELECT COUNT(*) FROM animals").fetchone()[0]
        if count == 0:
            squishy_id = str(uuid.uuid4())
            self._conn.execute(
                "INSERT INTO animals (id, name, species) VALUES (?, ?, ?)",
                (squishy_id, "Squishy", "cat"),
            )

        self._conn.commit()

    # ------------------------------------------------------------------
    # Migration
    # ------------------------------------------------------------------

    def _migrate_v0_to_v2(self) -> None:
        """One-time migration: meows/cat_photos → sounds/animal_photos + animals table.

        Trigger: user_version == 0 AND table 'meows' exists.
        Idempotent: stamps user_version = 2 on success.
        """
        user_ver = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if user_ver != 0:
            return

        meows_exists = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='meows'"
        ).fetchone()
        if meows_exists is None:
            return  # Fresh DB — no migration needed.

        # Checkpoint WAL before backup (must be outside any transaction).
        self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

        backup_path = Path(str(self._db_path) + ".pre-v2-backup")
        if not backup_path.exists():
            shutil.copy2(str(self._db_path), str(backup_path))

        # Inspect which optional columns the old meows table actually has
        # (some were added via ALTER TABLE in later versions).
        meows_cols = {
            row["name"] for row in self._conn.execute("PRAGMA table_info(meows)").fetchall()
        }

        cat_photos_exists = (
            self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='cat_photos'"
            ).fetchone()
            is not None
        )
        cat_photos_cols: set[str] = set()
        if cat_photos_exists:
            cat_photos_cols = {
                row["name"]
                for row in self._conn.execute("PRAGMA table_info(cat_photos)").fetchall()
            }

        ingest_jobs_exists = (
            self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='ingest_jobs'"
            ).fetchone()
            is not None
        )

        ingest_segs_exists = (
            self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='ingest_segments'"
            ).fetchone()
            is not None
        )

        squishy_id = str(uuid.uuid4())

        # Use an explicit transaction so DDL + DML are atomic.
        self._conn.execute("BEGIN EXCLUSIVE")
        try:
            # Step 1: Create animals, insert Squishy.
            self._conn.execute("""
                CREATE TABLE animals (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    species TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            self._conn.execute(
                "INSERT INTO animals (id, name, species) VALUES (?, ?, ?)",
                (squishy_id, "Squishy", "cat"),
            )

            # Step 2: Create sounds, copy from meows.
            self._conn.execute("""
                CREATE TABLE sounds (
                    id TEXT PRIMARY KEY,
                    animal_id TEXT NOT NULL REFERENCES animals(id) ON DELETE CASCADE,
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
                    species_energy_ratio REAL,
                    ai_analysis TEXT,
                    recorded_at TEXT,
                    title TEXT,
                    sound_fingerprint TEXT,
                    animal_uniqueness_score REAL,
                    species_uniqueness_score REAL,
                    upvote_count INTEGER NOT NULL DEFAULT 0,
                    downvote_count INTEGER NOT NULL DEFAULT 0
                )
            """)

            # Build SELECT expressions for every column that was ever added via
            # ALTER TABLE — none can be assumed present in very old DBs.
            def _col(name: str, default: str = "NULL") -> str:
                return name if name in meows_cols else default

            self._conn.execute(f"""
                INSERT INTO sounds
                    (id, animal_id, timestamp, duration_ms, labels, play_count, last_played,
                     created_at, wav_path, mp3_path, waveform_data, peak_dbfs,
                     species_energy_ratio, ai_analysis, recorded_at, title,
                     sound_fingerprint, animal_uniqueness_score, species_uniqueness_score,
                     upvote_count, downvote_count)
                SELECT
                    id, '{squishy_id}', timestamp, duration_ms, labels,
                    {_col("play_count", "0")}, {_col("last_played")},
                    created_at, wav_path, mp3_path, waveform_data, peak_dbfs,
                    cat_energy_ratio, {_col("ai_analysis")},
                    {_col("recorded_at")}, {_col("title")},
                    {_col("meow_fingerprint")},
                    {_col("uniqueness_score")}, {_col("uniqueness_score")},
                    {_col("upvote_count", "0")}, {_col("downvote_count", "0")}
                FROM meows
            """)
            self._conn.execute("DROP TABLE meows")

            # Step 3: Create animal_photos, copy from cat_photos.
            self._conn.execute("""
                CREATE TABLE animal_photos (
                    id TEXT PRIMARY KEY,
                    animal_id TEXT NOT NULL REFERENCES animals(id) ON DELETE CASCADE,
                    filename TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT,
                    is_default BOOLEAN NOT NULL DEFAULT 0
                )
            """)
            if cat_photos_exists:
                updated_at_expr = "updated_at" if "updated_at" in cat_photos_cols else "NULL"
                self._conn.execute(f"""
                    INSERT INTO animal_photos
                        (id, animal_id, filename, created_at, updated_at, is_default)
                    SELECT id, '{squishy_id}', filename, created_at, {updated_at_expr}, is_default
                    FROM cat_photos
                """)
                self._conn.execute("DROP TABLE cat_photos")

            # Step 4: Recreate ingest_jobs with animal_id column.
            if ingest_jobs_exists:
                self._conn.execute("""
                    CREATE TABLE ingest_jobs_new (
                        id TEXT PRIMARY KEY,
                        source_filename TEXT NOT NULL,
                        animal_id TEXT NOT NULL REFERENCES animals(id),
                        status TEXT NOT NULL DEFAULT 'pending',
                        error TEXT,
                        created_at TEXT NOT NULL DEFAULT (datetime('now')),
                        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                    )
                """)
                self._conn.execute(f"""
                    INSERT INTO ingest_jobs_new
                        (id, source_filename, animal_id, status, error, created_at, updated_at)
                    SELECT id, source_filename, '{squishy_id}', status, error, created_at, updated_at
                    FROM ingest_jobs
                """)
                self._conn.execute("DROP TABLE ingest_jobs")
                self._conn.execute("ALTER TABLE ingest_jobs_new RENAME TO ingest_jobs")

            # Rename ingest_segments.cat_energy_ratio → species_energy_ratio.
            if ingest_segs_exists:
                segs_cols = {
                    row["name"]
                    for row in self._conn.execute("PRAGMA table_info(ingest_segments)").fetchall()
                }
                if "cat_energy_ratio" in segs_cols:
                    self._conn.execute(
                        "ALTER TABLE ingest_segments RENAME COLUMN cat_energy_ratio TO species_energy_ratio"
                    )

            # Step 5: Stamp user_version.
            self._conn.execute("PRAGMA user_version = 2")
            self._conn.execute("COMMIT")

        except Exception:
            try:
                self._conn.execute("ROLLBACK")
            except Exception:
                pass
            raise

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def ping(self) -> bool:
        try:
            with self._lock:
                self._conn.execute("SELECT 1").fetchone()
            return True
        except Exception:
            return False

    def _row_to_dict(self, row: sqlite3.Row) -> dict:  # type: ignore[type-arg]
        d = dict(row)
        for field in ("labels", "waveform_data"):
            if field in d and isinstance(d[field], str):
                d[field] = json.loads(d[field])
        return d

    def _random_sound_row(
        self,
        exclude_id: str | None = None,
        animal_id: str | None = None,
    ) -> sqlite3.Row | None:
        """Return a random sounds row joined with animal name/species."""
        with self._lock:
            where_parts: list[str] = []
            params: list[object] = []
            if exclude_id:
                where_parts.append("s.id != ?")
                params.append(exclude_id)
            if animal_id:
                where_parts.append("s.animal_id = ?")
                params.append(animal_id)
            where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

            row = self._conn.execute(
                f"""
                SELECT s.*, a.name AS animal_name, a.species AS animal_species
                FROM sounds s JOIN animals a ON s.animal_id = a.id
                {where} ORDER BY RANDOM() LIMIT 1
                """,
                params,
            ).fetchone()

            if row is None and exclude_id:
                # Fall back: return any sound (ignore exclude_id when pool is tiny).
                fallback_parts: list[str] = []
                fallback_params: list[object] = []
                if animal_id:
                    fallback_parts.append("s.animal_id = ?")
                    fallback_params.append(animal_id)
                fallback_where = ("WHERE " + " AND ".join(fallback_parts)) if fallback_parts else ""
                row = self._conn.execute(
                    f"""
                    SELECT s.*, a.name AS animal_name, a.species AS animal_species
                    FROM sounds s JOIN animals a ON s.animal_id = a.id
                    {fallback_where} ORDER BY RANDOM() LIMIT 1
                    """,
                    fallback_params,
                ).fetchone()
        return row  # type: ignore[no-any-return]

    def _random_photo_row(
        self,
        animal_id: str | None = None,
        exclude_id: str | None = None,
    ) -> sqlite3.Row | None:
        """Return a random animal_photos row, optionally filtered by animal."""
        with self._lock:
            where_parts: list[str] = []
            params: list[object] = []
            if exclude_id:
                where_parts.append("id != ?")
                params.append(exclude_id)
            if animal_id:
                where_parts.append("animal_id = ?")
                params.append(animal_id)
            where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

            row = self._conn.execute(
                f"SELECT * FROM animal_photos {where} ORDER BY RANDOM() LIMIT 1",
                params,
            ).fetchone()

            if row is None and exclude_id:
                # Fall back: ignore exclude when pool is tiny.
                fallback_parts: list[str] = []
                fallback_params: list[object] = []
                if animal_id:
                    fallback_parts.append("animal_id = ?")
                    fallback_params.append(animal_id)
                fallback_where = ("WHERE " + " AND ".join(fallback_parts)) if fallback_parts else ""
                row = self._conn.execute(
                    f"SELECT * FROM animal_photos {fallback_where} ORDER BY RANDOM() LIMIT 1",
                    fallback_params,
                ).fetchone()
        return row  # type: ignore[no-any-return]

    # ------------------------------------------------------------------
    # Animals
    # ------------------------------------------------------------------

    def add_animal(self, name: str, species: str) -> str:
        """Insert a new animal and return its id."""
        animal_id = str(uuid.uuid4())
        with self._lock:
            self._conn.execute(
                "INSERT INTO animals (id, name, species) VALUES (?, ?, ?)",
                (animal_id, name, species),
            )
            self._conn.commit()
        return animal_id

    def get_animals(self) -> list[dict]:  # type: ignore[type-arg]
        """Return all animals with sound_count and photo_count, ordered by created_at."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT a.id, a.name, a.species, a.created_at,
                    COUNT(DISTINCT s.id) AS sound_count,
                    COUNT(DISTINCT p.id) AS photo_count
                FROM animals a
                LEFT JOIN sounds s ON s.animal_id = a.id
                LEFT JOIN animal_photos p ON p.animal_id = a.id
                GROUP BY a.id, a.name, a.species, a.created_at
                ORDER BY a.created_at
                """
            ).fetchall()
        return [dict(r) for r in rows]

    def get_animal(self, animal_id: str) -> dict | None:  # type: ignore[type-arg]
        with self._lock:
            row = self._conn.execute(
                """
                SELECT a.id, a.name, a.species, a.created_at,
                    COUNT(DISTINCT s.id) AS sound_count,
                    COUNT(DISTINCT p.id) AS photo_count
                FROM animals a
                LEFT JOIN sounds s ON s.animal_id = a.id
                LEFT JOIN animal_photos p ON p.animal_id = a.id
                WHERE a.id = ?
                GROUP BY a.id
                """,
                (animal_id,),
            ).fetchone()
        return dict(row) if row else None

    def delete_animal(self, animal_id: str) -> dict[str, list[str]] | None:
        """Delete an animal and return file paths to remove from disk.

        Returns a dict with keys:
          "audio_paths"     — absolute wav/mp3 paths from the sounds table
          "photo_filenames" — photo filenames (relative; caller resolves against photos dir)
        Returns None if the animal does not exist.
        The DB row deletion cascades to sounds and animal_photos.
        """
        with self._lock:
            exists = self._conn.execute(
                "SELECT id FROM animals WHERE id = ?", (animal_id,)
            ).fetchone()
            if exists is None:
                return None

            sound_rows = self._conn.execute(
                "SELECT wav_path, mp3_path FROM sounds WHERE animal_id = ?", (animal_id,)
            ).fetchall()
            audio_paths: list[str] = []
            for r in sound_rows:
                audio_paths.append(r["wav_path"])
                audio_paths.append(r["mp3_path"])

            photo_rows = self._conn.execute(
                "SELECT filename FROM animal_photos WHERE animal_id = ?", (animal_id,)
            ).fetchall()
            photo_filenames = [r["filename"] for r in photo_rows]

            self._conn.execute("DELETE FROM animals WHERE id = ?", (animal_id,))
            self._conn.commit()

        return {"audio_paths": audio_paths, "photo_filenames": photo_filenames}

    # ------------------------------------------------------------------
    # Sounds (core CRUD)
    # ------------------------------------------------------------------

    def add(self, metadata: dict) -> str:  # type: ignore[type-arg]
        """Insert a new sound row. metadata must include animal_id."""
        sound_id = str(uuid.uuid4())
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO sounds
                    (id, animal_id, timestamp, duration_ms, labels, wav_path, mp3_path,
                     waveform_data, peak_dbfs, species_energy_ratio)
                VALUES
                    (:id, :animal_id, :timestamp, :duration_ms, :labels, :wav_path, :mp3_path,
                     :waveform_data, :peak_dbfs, :species_energy_ratio)
                """,
                {
                    "id": sound_id,
                    "animal_id": metadata["animal_id"],
                    "timestamp": metadata.get("timestamp", ""),
                    "duration_ms": metadata["duration_ms"],
                    "labels": json.dumps(metadata.get("labels", [])),
                    "wav_path": metadata["wav_path"],
                    "mp3_path": metadata["mp3_path"],
                    "waveform_data": json.dumps(metadata.get("waveform_data", [])),
                    "peak_dbfs": metadata.get("peak_dbfs"),
                    "species_energy_ratio": metadata.get("species_energy_ratio"),
                },
            )
            self._conn.commit()
        return sound_id

    def get_all_for_export(self) -> list[dict]:  # type: ignore[type-arg]
        with self._lock:
            rows = self._conn.execute("SELECT * FROM sounds ORDER BY created_at ASC").fetchall()
        return [self._row_to_dict(r) for r in rows]

    def import_sound(
        self,
        sound_id: str,
        sound: dict,  # type: ignore[type-arg]
        wav_path: str,
        mp3_path: str,
        animal_id: str,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO sounds
                    (id, animal_id, timestamp, duration_ms, labels, wav_path, mp3_path,
                     waveform_data, peak_dbfs, species_energy_ratio, recorded_at,
                     title, play_count, last_played, created_at,
                     upvote_count, downvote_count)
                VALUES
                    (:id, :animal_id, :timestamp, :duration_ms, :labels, :wav_path, :mp3_path,
                     :waveform_data, :peak_dbfs, :species_energy_ratio, :recorded_at,
                     :title, :play_count, :last_played, :created_at,
                     :upvote_count, :downvote_count)
                """,
                {
                    "id": sound_id,
                    "animal_id": animal_id,
                    "timestamp": sound.get("timestamp", ""),
                    "duration_ms": sound["duration_ms"],
                    "labels": json.dumps(sound.get("labels", [])),
                    "wav_path": wav_path,
                    "mp3_path": mp3_path,
                    "waveform_data": json.dumps(sound.get("waveform_data", [])),
                    "peak_dbfs": sound.get("peak_dbfs"),
                    "species_energy_ratio": sound.get("species_energy_ratio"),
                    "recorded_at": sound.get("recorded_at"),
                    "title": sound.get("title"),
                    "play_count": sound.get("play_count", 0),
                    "last_played": sound.get("last_played"),
                    "created_at": sound.get("created_at", ""),
                    "upvote_count": sound.get("upvote_count", 0),
                    "downvote_count": sound.get("downvote_count", 0),
                },
            )
            self._conn.commit()

    def get_random_sound(self, exclude_id: str | None = None) -> dict | None:  # type: ignore[type-arg]
        """Return a random sound dict including animal_name and animal_species."""
        row = self._random_sound_row(exclude_id=exclude_id)
        return self._row_to_dict(row) if row else None

    def get_all(
        self,
        sort: str = "newest",
        label_filter: str | None = None,
        animal_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:  # type: ignore[type-arg]
        if sort not in _SORT_MAP:
            raise ValueError(f"Invalid sort: {sort!r}")
        order = _SORT_MAP[sort]

        with self._lock:
            where_parts: list[str] = []
            params: list[object] = []
            if label_filter:
                where_parts.append("labels LIKE ?")
                params.append(f'%"{label_filter}"%')
            if animal_id:
                where_parts.append("animal_id = ?")
                params.append(animal_id)
            where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
            params.extend([limit, offset])

            rows = self._conn.execute(
                f"SELECT * FROM sounds {where} ORDER BY {order} LIMIT ? OFFSET ?",
                params,
            ).fetchall()

        return [self._row_to_dict(r) for r in rows]

    def get_by_id(self, sound_id: str) -> dict | None:  # type: ignore[type-arg]
        with self._lock:
            row = self._conn.execute("SELECT * FROM sounds WHERE id = ?", (sound_id,)).fetchone()
        return self._row_to_dict(row) if row else None

    def update_sound(self, sound_id: str, updates: dict) -> bool:  # type: ignore[type-arg]
        allowed = {"title", "recorded_at"}
        fields = {k: v for k, v in updates.items() if k in allowed}
        if not fields:
            return True
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [sound_id]
        with self._lock:
            cursor = self._conn.execute(
                f"UPDATE sounds SET {set_clause} WHERE id = ?",
                values,
            )
            self._conn.commit()
        return cursor.rowcount > 0

    def update_labels(self, sound_id: str, labels: list[str]) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE sounds SET labels = ? WHERE id = ?",
                (json.dumps(labels), sound_id),
            )
            self._conn.commit()
        return cursor.rowcount > 0

    def delete(self, sound_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM sounds WHERE id = ?", (sound_id,))
            self._conn.commit()
        return cursor.rowcount > 0

    def increment_play_count(self, sound_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE sounds SET play_count = play_count + 1, last_played = datetime('now') WHERE id = ?",
                (sound_id,),
            )
            self._conn.commit()
        return cursor.rowcount > 0

    def record_feedback(self, sound_id: str, is_upvote: bool) -> bool:
        col = "upvote_count" if is_upvote else "downvote_count"
        with self._lock:
            cursor = self._conn.execute(
                f"UPDATE sounds SET {col} = {col} + 1 WHERE id = ?",
                (sound_id,),
            )
            self._conn.commit()
        return cursor.rowcount > 0

    def switch_feedback(self, sound_id: str, is_upvote: bool) -> bool:
        inc = "upvote_count" if is_upvote else "downvote_count"
        dec = "downvote_count" if is_upvote else "upvote_count"
        with self._lock:
            cursor = self._conn.execute(
                f"UPDATE sounds SET {inc} = {inc} + 1, {dec} = MAX({dec} - 1, 0) WHERE id = ?",
                (sound_id,),
            )
            self._conn.commit()
        return cursor.rowcount > 0

    def get_count(self, label_filter: str | None = None, animal_id: str | None = None) -> int:
        with self._lock:
            where_parts: list[str] = []
            params: list[object] = []
            if label_filter:
                where_parts.append("labels LIKE ?")
                params.append(f'%"{label_filter}"%')
            if animal_id:
                where_parts.append("animal_id = ?")
                params.append(animal_id)
            where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
            row = self._conn.execute(f"SELECT COUNT(*) FROM sounds {where}", params).fetchone()
        return int(row[0])

    def update_sound_paths(self, sound_id: str, wav_path: str, mp3_path: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE sounds SET wav_path = ?, mp3_path = ? WHERE id = ?",
                (wav_path, mp3_path, sound_id),
            )
            self._conn.commit()

    # ------------------------------------------------------------------
    # Fingerprint & uniqueness
    # ------------------------------------------------------------------

    def update_fingerprint(self, sound_id: str, fingerprint: list[float]) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE sounds SET sound_fingerprint = ? WHERE id = ?",
                (json.dumps(fingerprint), sound_id),
            )
            self._conn.commit()

    def update_uniqueness_scores_bulk(
        self,
        animal_scores: dict[str, float | None],
        species_scores: dict[str, float | None],
    ) -> None:
        """Update animal_uniqueness_score and/or species_uniqueness_score per sound."""
        all_ids = set(animal_scores) | set(species_scores)
        with self._lock:
            for sound_id in all_ids:
                sets: list[str] = []
                params: list[object] = []
                if sound_id in animal_scores:
                    sets.append("animal_uniqueness_score = ?")
                    params.append(animal_scores[sound_id])
                if sound_id in species_scores:
                    sets.append("species_uniqueness_score = ?")
                    params.append(species_scores[sound_id])
                if sets:
                    params.append(sound_id)
                    self._conn.execute(
                        f"UPDATE sounds SET {', '.join(sets)} WHERE id = ?",
                        params,
                    )
            self._conn.commit()

    def get_all_fingerprints(self) -> dict[str, list[float]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, sound_fingerprint FROM sounds WHERE sound_fingerprint IS NOT NULL"
            ).fetchall()
        return {
            row["id"]: json.loads(row["sound_fingerprint"])
            for row in rows
            if row["sound_fingerprint"]
        }

    # ------------------------------------------------------------------
    # Sound grouping helpers (for similarity scoring)
    # ------------------------------------------------------------------

    def get_sound_animal_groups(self) -> dict[str, str]:
        """{sound_id: animal_id} for all sounds."""
        with self._lock:
            rows = self._conn.execute("SELECT id, animal_id FROM sounds").fetchall()
        return {row["id"]: row["animal_id"] for row in rows}

    def get_sound_species_groups(self) -> dict[str, str]:
        """{sound_id: species} for all sounds, resolved via JOIN animals."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT s.id, a.species FROM sounds s JOIN animals a ON s.animal_id = a.id"
            ).fetchall()
        return {row["id"]: row["species"] for row in rows}

    # ------------------------------------------------------------------
    # Stats & labels
    # ------------------------------------------------------------------

    def _count_labels(self) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute("SELECT labels FROM sounds").fetchall()
        counts: dict[str, int] = {}
        for row in rows:
            for label in json.loads(row["labels"]):
                counts[label] = counts.get(label, 0) + 1
        return counts

    def get_stats(self) -> dict:  # type: ignore[type-arg]
        with self._lock:
            agg = self._conn.execute(
                """
                SELECT
                    COUNT(*) AS total_sounds,
                    COALESCE(SUM(duration_ms), 0) AS total_duration_ms,
                    COALESCE(AVG(duration_ms), 0) AS avg_duration_ms,
                    MIN(created_at) AS first_sound_at
                FROM sounds
                """
            ).fetchone()

            most_played = [
                self._row_to_dict(r)
                for r in self._conn.execute(
                    "SELECT * FROM sounds ORDER BY play_count DESC LIMIT 5"
                ).fetchall()
            ]

            recent = [
                self._row_to_dict(r)
                for r in self._conn.execute(
                    "SELECT * FROM sounds ORDER BY created_at DESC LIMIT 10"
                ).fetchall()
            ]

            most_upvoted = [
                self._row_to_dict(r)
                for r in self._conn.execute(
                    "SELECT * FROM sounds WHERE upvote_count > 0 ORDER BY upvote_count DESC LIMIT 5"
                ).fetchall()
            ]

            most_downvoted_stats = [
                self._row_to_dict(r)
                for r in self._conn.execute(
                    "SELECT * FROM sounds WHERE downvote_count > 0 ORDER BY downvote_count DESC LIMIT 5"
                ).fetchall()
            ]

            # RLock allows reentry so _count_labels() can acquire the same lock.
            label_counts = self._count_labels()

            species_rows = self._conn.execute(
                """
                SELECT a.species, COUNT(s.id) AS cnt
                FROM sounds s JOIN animals a ON s.animal_id = a.id
                GROUP BY a.species
                """
            ).fetchall()
            species_counts = {row["species"]: row["cnt"] for row in species_rows}

        return {
            "total_sounds": agg["total_sounds"],
            "total_duration_ms": agg["total_duration_ms"],
            "avg_duration_ms": agg["avg_duration_ms"],
            "first_sound_at": agg["first_sound_at"],
            "most_played": most_played,
            "recent": recent,
            "most_upvoted": most_upvoted,
            "most_downvoted": most_downvoted_stats,
            "label_counts": label_counts,
            "species_counts": species_counts,
        }

    def get_labels(self) -> list[dict]:  # type: ignore[type-arg]
        counts = self._count_labels()
        return [{"label": lbl, "count": cnt} for lbl, cnt in sorted(counts.items())]

    # ------------------------------------------------------------------
    # Photos
    # ------------------------------------------------------------------

    def add_photo(
        self,
        filename: str,
        animal_id: str,
        photo_id: str | None = None,
        is_default: bool = False,
    ) -> str:
        if photo_id is None:
            photo_id = str(uuid.uuid4())
        with self._lock:
            self._conn.execute(
                "INSERT INTO animal_photos (id, animal_id, filename, is_default) VALUES (?, ?, ?, ?)",
                (photo_id, animal_id, filename, is_default),
            )
            self._conn.commit()
        return photo_id

    def get_photos(self, animal_id: str | None = None) -> list[dict]:  # type: ignore[type-arg]
        with self._lock:
            if animal_id:
                rows = self._conn.execute(
                    "SELECT * FROM animal_photos WHERE animal_id = ? ORDER BY created_at DESC",
                    (animal_id,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM animal_photos ORDER BY created_at DESC"
                ).fetchall()
        return [dict(r) for r in rows]

    def import_photo(
        self,
        photo_id: str,
        filename: str,
        animal_id: str,
        created_at: str | None,
        is_default: bool,
        updated_at: str | None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO animal_photos
                    (id, animal_id, filename, created_at, is_default, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (photo_id, animal_id, filename, created_at, is_default, updated_at),
            )
            self._conn.commit()

    def get_random_photo(self, exclude_id: str | None = None) -> dict | None:  # type: ignore[type-arg]
        """Return a random photo from any animal; dict includes animal_id."""
        row = self._random_photo_row(exclude_id=exclude_id)
        return dict(row) if row else None

    def get_random_photo_for_animal(
        self, animal_id: str, exclude_id: str | None = None
    ) -> dict | None:  # type: ignore[type-arg]
        """Return a random photo restricted to a specific animal."""
        row = self._random_photo_row(animal_id=animal_id, exclude_id=exclude_id)
        return dict(row) if row else None

    def get_photo(self, photo_id: str) -> dict | None:  # type: ignore[type-arg]
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM animal_photos WHERE id = ?", (photo_id,)
            ).fetchone()
        return dict(row) if row else None

    def update_photo_filename(self, photo_id: str, filename: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE animal_photos SET filename = ?, updated_at = datetime('now') WHERE id = ?",
                (filename, photo_id),
            )
            self._conn.commit()

    def touch_photo(self, photo_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE animal_photos SET updated_at = datetime('now') WHERE id = ?",
                (photo_id,),
            )
            self._conn.commit()

    def delete_photo(self, photo_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM animal_photos WHERE id = ?", (photo_id,))
            self._conn.commit()
        return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Wav paths
    # ------------------------------------------------------------------

    def get_all_wav_paths(self) -> list[dict]:  # type: ignore[type-arg]
        with self._lock:
            rows = self._conn.execute("SELECT id, wav_path FROM sounds").fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Ingest jobs
    # ------------------------------------------------------------------

    def create_job(self, source_filename: str, animal_id: str) -> str:
        job_id = str(uuid.uuid4())
        with self._lock:
            self._conn.execute(
                "INSERT INTO ingest_jobs (id, source_filename, animal_id) VALUES (?, ?, ?)",
                (job_id, source_filename, animal_id),
            )
            self._conn.commit()
        return job_id

    def get_job(self, job_id: str) -> dict | None:  # type: ignore[type-arg]
        with self._lock:
            row = self._conn.execute("SELECT * FROM ingest_jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                return None
            job = dict(row)
            if job["status"] == "ready":
                segs = self._conn.execute(
                    "SELECT * FROM ingest_segments WHERE job_id = ? ORDER BY index_in_job",
                    (job_id,),
                ).fetchall()
                job["segments"] = [self._row_to_dict(s) for s in segs]
        return job

    def update_job_status(self, job_id: str, status: str, error: str | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE ingest_jobs SET status = ?, error = ?, updated_at = datetime('now') WHERE id = ?",
                (status, error, job_id),
            )
            self._conn.commit()

    def add_segments(self, job_id: str, segments: list[dict]) -> None:  # type: ignore[type-arg]
        with self._lock:
            for seg in segments:
                seg_id = str(uuid.uuid4())
                self._conn.execute(
                    """
                    INSERT INTO ingest_segments
                        (id, job_id, index_in_job, duration_ms, wav_path, waveform_data,
                         peak_dbfs, species_energy_ratio)
                    VALUES
                        (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        seg_id,
                        job_id,
                        seg["index"],
                        seg["duration_ms"],
                        seg["wav_path"],
                        json.dumps(seg.get("waveform_data", [])),
                        seg.get("peak_dbfs"),
                        seg.get("species_energy_ratio"),
                    ),
                )
            self._conn.commit()

    def update_segment_status(self, segment_id: str, status: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE ingest_segments SET status = ? WHERE id = ?",
                (status, segment_id),
            )
            self._conn.commit()

    def get_segment(self, segment_id: str, job_id: str) -> dict | None:  # type: ignore[type-arg]
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM ingest_segments WHERE id = ? AND job_id = ?",
                (segment_id, job_id),
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def get_segment_ids(self, job_id: str) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id FROM ingest_segments WHERE job_id = ?", (job_id,)
            ).fetchall()
        return [row["id"] for row in rows]

    def commit_job(
        self,
        job_id: str,
        accepted_ids: list[str],
        rejected_ids: list[str],
        wav_dir: Path,
        mp3_dir: Path,
        recorded_at: str | None = None,
    ) -> list[str]:
        new_sound_ids: list[str] = []
        # (seg_id, sound_id, seg, dst_wav, dst_mp3) tuples built after file moves
        committed: list[tuple[str, str, dict, Path, Path]] = []  # type: ignore[type-arg]

        if accepted_ids:
            wav_dir.mkdir(parents=True, exist_ok=True)
            mp3_dir.mkdir(parents=True, exist_ok=True)

            with self._lock:
                job_row = self._conn.execute(
                    "SELECT animal_id FROM ingest_jobs WHERE id = ?", (job_id,)
                ).fetchone()
                animal_id = job_row["animal_id"] if job_row else None

                placeholders = ",".join("?" * len(accepted_ids))
                seg_rows = self._conn.execute(
                    f"SELECT * FROM ingest_segments WHERE id IN ({placeholders})",
                    accepted_ids,
                ).fetchall()
                seg_by_id = {row["id"]: self._row_to_dict(row) for row in seg_rows}

            # File moves happen outside the lock (filesystem, not DB).
            for seg_id in accepted_ids:
                seg = seg_by_id.get(seg_id)
                if seg is None:
                    continue
                sound_id = str(uuid.uuid4())
                src_wav = Path(seg["wav_path"])
                dst_wav = wav_dir / f"{sound_id}.wav"
                dst_mp3 = mp3_dir / f"{sound_id}.mp3"
                shutil.move(str(src_wav), dst_wav)
                shutil.move(str(src_wav.with_suffix(".mp3")), dst_mp3)
                committed.append((seg_id, sound_id, seg, dst_wav, dst_mp3))
                new_sound_ids.append(sound_id)

        # All DB writes in a single lock acquisition to preserve transaction atomicity.
        with self._lock:
            for seg_id, sound_id, seg, dst_wav, dst_mp3 in committed:
                self._conn.execute(
                    """
                    INSERT INTO sounds
                        (id, animal_id, timestamp, duration_ms, labels, wav_path, mp3_path,
                         waveform_data, peak_dbfs, species_energy_ratio, recorded_at)
                    VALUES
                        (:id, :animal_id, datetime('now'), :duration_ms, '[]', :wav_path,
                         :mp3_path, :waveform_data, :peak_dbfs, :species_energy_ratio, :recorded_at)
                    """,
                    {
                        "id": sound_id,
                        "animal_id": animal_id,
                        "duration_ms": seg["duration_ms"],
                        "wav_path": str(dst_wav),
                        "mp3_path": str(dst_mp3),
                        "waveform_data": json.dumps(seg.get("waveform_data", [])),
                        "peak_dbfs": seg.get("peak_dbfs"),
                        "species_energy_ratio": seg.get("species_energy_ratio"),
                        "recorded_at": recorded_at,
                    },
                )
                self._conn.execute(
                    "UPDATE ingest_segments SET status = 'accepted' WHERE id = ?", (seg_id,)
                )

            for seg_id in rejected_ids:
                self._conn.execute(
                    "UPDATE ingest_segments SET status = 'rejected' WHERE id = ?", (seg_id,)
                )

            self._conn.execute(
                "UPDATE ingest_jobs SET status = 'committed', updated_at = datetime('now') WHERE id = ?",
                (job_id,),
            )
            self._conn.commit()
        return new_sound_ids

    def delete_job(self, job_id: str) -> None:
        # ON DELETE CASCADE removes segments automatically.
        with self._lock:
            self._conn.execute("DELETE FROM ingest_jobs WHERE id = ?", (job_id,))
            self._conn.commit()
