from __future__ import annotations

from pathlib import Path

import pytest

from meowdb.db import MeowDB


def _aid(db: MeowDB) -> str:
    """Return the auto-seeded Squishy animal's ID."""
    return str(db.get_animals()[0]["id"])


def _sound(
    animal_id: str,
    wav_path: str = "/tmp/test.wav",
    mp3_path: str = "/tmp/test.mp3",
    duration_ms: int = 1000,
    labels: list | None = None,
    waveform_data: list | None = None,
    peak_dbfs: float | None = -10.0,
    species_energy_ratio: float | None = 1.5,
) -> dict:
    return {
        "animal_id": animal_id,
        "timestamp": "2026-06-14T12:00:00",
        "duration_ms": duration_ms,
        "labels": labels or [],
        "wav_path": wav_path,
        "mp3_path": mp3_path,
        "waveform_data": waveform_data or [],
        "peak_dbfs": peak_dbfs,
        "species_energy_ratio": species_energy_ratio,
    }


def _segment(
    index: int = 0,
    wav_path: str = "/tmp/seg.wav",
    duration_ms: int = 800,
    waveform_data: list | None = None,
    peak_dbfs: float | None = -12.0,
    species_energy_ratio: float | None = 1.8,
) -> dict:
    return {
        "index": index,
        "duration_ms": duration_ms,
        "wav_path": wav_path,
        "waveform_data": waveform_data or [0.1, 0.5, 0.9],
        "peak_dbfs": peak_dbfs,
        "species_energy_ratio": species_energy_ratio,
    }


# =============================================================================
# Auto-seed
# =============================================================================


@pytest.mark.unit
def test_fresh_db_auto_seeds_squishy(tmp_db: MeowDB) -> None:
    animals = tmp_db.get_animals()
    assert len(animals) == 1
    assert animals[0]["name"] == "Squishy"
    assert animals[0]["species"] == "cat"


@pytest.mark.unit
def test_reopen_db_does_not_duplicate_squishy(tmp_path: Path) -> None:
    db_path = tmp_path / "reopen.sqlite"
    db1 = MeowDB(db_path)
    db1.close()
    db2 = MeowDB(db_path)
    animals = db2.get_animals()
    db2.close()
    assert len(animals) == 1


# =============================================================================
# Animal CRUD
# =============================================================================


@pytest.mark.unit
def test_add_animal_and_get_animal(tmp_db: MeowDB) -> None:
    dog_id = tmp_db.add_animal("Rex", "dog")
    animal = tmp_db.get_animal(dog_id)
    assert animal is not None
    assert animal["id"] == dog_id
    assert animal["name"] == "Rex"
    assert animal["species"] == "dog"
    assert animal["sound_count"] == 0
    assert animal["photo_count"] == 0


@pytest.mark.unit
def test_add_animal_returns_unique_ids(tmp_db: MeowDB) -> None:
    id1 = tmp_db.add_animal("Rex", "dog")
    id2 = tmp_db.add_animal("Whiskers", "cat")
    assert id1 != id2


@pytest.mark.unit
def test_get_animals_returns_counts(tmp_db: MeowDB) -> None:
    squishy_id = _aid(tmp_db)
    tmp_db.add(_sound(squishy_id))
    tmp_db.add_photo("photo.jpg", squishy_id)
    animals = tmp_db.get_animals()
    assert len(animals) == 1
    assert animals[0]["sound_count"] == 1
    assert animals[0]["photo_count"] == 1


@pytest.mark.unit
def test_get_animal_missing(tmp_db: MeowDB) -> None:
    assert tmp_db.get_animal("nonexistent") is None


@pytest.mark.unit
def test_delete_animal_returns_file_paths(tmp_db: MeowDB) -> None:
    squishy_id = _aid(tmp_db)
    tmp_db.add(_sound(squishy_id, wav_path="/audio/a.wav", mp3_path="/audio/a.mp3"))
    tmp_db.add_photo("photo.jpg", squishy_id)

    result = tmp_db.delete_animal(squishy_id)

    assert result is not None
    assert "/audio/a.wav" in result["audio_paths"]
    assert "/audio/a.mp3" in result["audio_paths"]
    assert "photo.jpg" in result["photo_filenames"]


@pytest.mark.unit
def test_delete_animal_cascade_removes_sounds_and_photos(tmp_db: MeowDB) -> None:
    squishy_id = _aid(tmp_db)
    tmp_db.add(_sound(squishy_id))
    tmp_db.add_photo("photo.jpg", squishy_id)

    tmp_db.delete_animal(squishy_id)

    assert tmp_db.get_count() == 0
    assert tmp_db.get_photos() == []
    assert tmp_db.get_animal(squishy_id) is None


@pytest.mark.unit
def test_delete_animal_missing_returns_none(tmp_db: MeowDB) -> None:
    assert tmp_db.delete_animal("nonexistent") is None


# =============================================================================
# Sound CRUD
# =============================================================================


@pytest.mark.unit
def test_add_and_get_by_id(tmp_db: MeowDB) -> None:
    sound_id = tmp_db.add(_sound(_aid(tmp_db), duration_ms=500))
    result = tmp_db.get_by_id(sound_id)
    assert result is not None
    assert result["id"] == sound_id
    assert result["duration_ms"] == 500
    assert result["labels"] == []
    assert result["play_count"] == 0


@pytest.mark.unit
def test_add_returns_unique_ids(tmp_db: MeowDB) -> None:
    aid = _aid(tmp_db)
    id1 = tmp_db.add(_sound(aid))
    id2 = tmp_db.add(_sound(aid))
    assert id1 != id2


@pytest.mark.unit
def test_add_stores_labels_and_waveform(tmp_db: MeowDB) -> None:
    sound_id = tmp_db.add(
        _sound(_aid(tmp_db), labels=["happy", "loud"], waveform_data=[0.1, 0.5, 1.0])
    )
    result = tmp_db.get_by_id(sound_id)
    assert result is not None
    assert result["labels"] == ["happy", "loud"]
    assert result["waveform_data"] == [0.1, 0.5, 1.0]


@pytest.mark.unit
def test_get_by_id_missing(tmp_db: MeowDB) -> None:
    assert tmp_db.get_by_id("nonexistent-id") is None


@pytest.mark.unit
def test_get_random_sound_empty(tmp_db: MeowDB) -> None:
    assert tmp_db.get_random_sound() is None


@pytest.mark.unit
def test_get_random_sound_returns_sound(tmp_db: MeowDB) -> None:
    sound_id = tmp_db.add(_sound(_aid(tmp_db)))
    result = tmp_db.get_random_sound()
    assert result is not None
    assert result["id"] == sound_id


@pytest.mark.unit
def test_get_random_sound_does_not_count_a_play(tmp_db: MeowDB) -> None:
    # get_random_sound is a read, not a play; play_count must stay zero
    sound_id = tmp_db.add(_sound(_aid(tmp_db)))
    for _ in range(3):
        tmp_db.get_random_sound()
    result = tmp_db.get_by_id(sound_id)
    assert result is not None
    assert result["play_count"] == 0


@pytest.mark.unit
def test_get_random_sound_includes_animal_fields(tmp_db: MeowDB) -> None:
    tmp_db.add(_sound(_aid(tmp_db)))
    result = tmp_db.get_random_sound()
    assert result is not None
    assert result["animal_name"] == "Squishy"
    assert result["animal_species"] == "cat"


@pytest.mark.unit
def test_get_all_empty(tmp_db: MeowDB) -> None:
    assert tmp_db.get_all() == []


@pytest.mark.unit
def test_get_all_returns_all(tmp_db: MeowDB) -> None:
    aid = _aid(tmp_db)
    tmp_db.add(_sound(aid, duration_ms=100))
    tmp_db.add(_sound(aid, duration_ms=200))
    results = tmp_db.get_all()
    assert len(results) == 2


@pytest.mark.unit
def test_get_all_sort_newest(tmp_db: MeowDB) -> None:
    aid = _aid(tmp_db)
    id1 = tmp_db.add(_sound(aid, duration_ms=100))
    id2 = tmp_db.add(_sound(aid, duration_ms=200))
    results = tmp_db.get_all(sort="newest")
    assert results[0]["id"] == id2
    assert results[1]["id"] == id1


@pytest.mark.unit
def test_get_all_sort_oldest(tmp_db: MeowDB) -> None:
    aid = _aid(tmp_db)
    id1 = tmp_db.add(_sound(aid, duration_ms=100))
    id2 = tmp_db.add(_sound(aid, duration_ms=200))
    results = tmp_db.get_all(sort="oldest")
    assert results[0]["id"] == id1
    assert results[1]["id"] == id2


@pytest.mark.unit
def test_get_all_sort_duration_asc(tmp_db: MeowDB) -> None:
    aid = _aid(tmp_db)
    id1 = tmp_db.add(_sound(aid, duration_ms=300))
    id2 = tmp_db.add(_sound(aid, duration_ms=100))
    id3 = tmp_db.add(_sound(aid, duration_ms=200))
    results = tmp_db.get_all(sort="duration_asc")
    assert results[0]["id"] == id2
    assert results[1]["id"] == id3
    assert results[2]["id"] == id1


@pytest.mark.unit
def test_get_all_sort_duration_desc(tmp_db: MeowDB) -> None:
    aid = _aid(tmp_db)
    id1 = tmp_db.add(_sound(aid, duration_ms=300))
    id2 = tmp_db.add(_sound(aid, duration_ms=100))
    results = tmp_db.get_all(sort="duration_desc")
    assert results[0]["id"] == id1
    assert results[1]["id"] == id2


@pytest.mark.unit
def test_get_all_sort_most_played(tmp_db: MeowDB) -> None:
    aid = _aid(tmp_db)
    id1 = tmp_db.add(_sound(aid))
    id2 = tmp_db.add(_sound(aid))
    tmp_db.increment_play_count(id2)
    tmp_db.increment_play_count(id2)
    tmp_db.increment_play_count(id1)
    results = tmp_db.get_all(sort="most_played")
    assert results[0]["id"] == id2


@pytest.mark.unit
def test_get_all_label_filter(tmp_db: MeowDB) -> None:
    aid = _aid(tmp_db)
    id1 = tmp_db.add(_sound(aid, labels=["morning"]))
    tmp_db.add(_sound(aid, labels=["evening"]))
    results = tmp_db.get_all(label_filter="morning")
    assert len(results) == 1
    assert results[0]["id"] == id1


@pytest.mark.unit
def test_get_all_label_filter_no_match(tmp_db: MeowDB) -> None:
    tmp_db.add(_sound(_aid(tmp_db), labels=["evening"]))
    assert tmp_db.get_all(label_filter="morning") == []


@pytest.mark.unit
def test_get_all_pagination(tmp_db: MeowDB) -> None:
    aid = _aid(tmp_db)
    for i in range(5):
        tmp_db.add(_sound(aid, duration_ms=i * 100))
    page1 = tmp_db.get_all(sort="oldest", limit=3, offset=0)
    page2 = tmp_db.get_all(sort="oldest", limit=3, offset=3)
    assert len(page1) == 3
    assert len(page2) == 2
    ids1 = {r["id"] for r in page1}
    ids2 = {r["id"] for r in page2}
    assert ids1.isdisjoint(ids2)


@pytest.mark.unit
def test_get_all_animal_id_filter(tmp_db: MeowDB) -> None:
    squishy_id = _aid(tmp_db)
    dog_id = tmp_db.add_animal("Rex", "dog")
    s1 = tmp_db.add(_sound(squishy_id))
    tmp_db.add(_sound(dog_id))
    results = tmp_db.get_all(animal_id=squishy_id)
    assert len(results) == 1
    assert results[0]["id"] == s1


@pytest.mark.unit
def test_update_labels(tmp_db: MeowDB) -> None:
    sound_id = tmp_db.add(_sound(_aid(tmp_db), labels=["old"]))
    result = tmp_db.update_labels(sound_id, ["new", "tag"])
    assert result is True
    updated = tmp_db.get_by_id(sound_id)
    assert updated is not None
    assert updated["labels"] == ["new", "tag"]


@pytest.mark.unit
def test_update_labels_clears(tmp_db: MeowDB) -> None:
    sound_id = tmp_db.add(_sound(_aid(tmp_db), labels=["old"]))
    tmp_db.update_labels(sound_id, [])
    updated = tmp_db.get_by_id(sound_id)
    assert updated is not None
    assert updated["labels"] == []


@pytest.mark.unit
def test_update_labels_missing_id(tmp_db: MeowDB) -> None:
    assert tmp_db.update_labels("nonexistent", ["x"]) is False


@pytest.mark.unit
def test_delete(tmp_db: MeowDB) -> None:
    sound_id = tmp_db.add(_sound(_aid(tmp_db)))
    result = tmp_db.delete(sound_id)
    assert result is True
    assert tmp_db.get_by_id(sound_id) is None


@pytest.mark.unit
def test_delete_missing(tmp_db: MeowDB) -> None:
    assert tmp_db.delete("nonexistent") is False


@pytest.mark.unit
def test_increment_play_count(tmp_db: MeowDB) -> None:
    sound_id = tmp_db.add(_sound(_aid(tmp_db)))
    assert tmp_db.increment_play_count(sound_id) is True
    assert tmp_db.increment_play_count(sound_id) is True
    result = tmp_db.get_by_id(sound_id)
    assert result is not None
    assert result["play_count"] == 2


@pytest.mark.unit
def test_increment_play_count_missing_id(tmp_db: MeowDB) -> None:
    assert tmp_db.increment_play_count("nonexistent") is False


@pytest.mark.unit
def test_record_feedback_upvote(tmp_db: MeowDB) -> None:
    sound_id = tmp_db.add(_sound(_aid(tmp_db)))
    assert tmp_db.record_feedback(sound_id, is_upvote=True) is True
    assert tmp_db.record_feedback(sound_id, is_upvote=True) is True
    result = tmp_db.get_by_id(sound_id)
    assert result is not None
    assert result["upvote_count"] == 2
    assert result["downvote_count"] == 0


@pytest.mark.unit
def test_record_feedback_downvote(tmp_db: MeowDB) -> None:
    sound_id = tmp_db.add(_sound(_aid(tmp_db)))
    assert tmp_db.record_feedback(sound_id, is_upvote=False) is True
    result = tmp_db.get_by_id(sound_id)
    assert result is not None
    assert result["downvote_count"] == 1
    assert result["upvote_count"] == 0


@pytest.mark.unit
def test_record_feedback_missing_id(tmp_db: MeowDB) -> None:
    assert tmp_db.record_feedback("nonexistent", is_upvote=True) is False


@pytest.mark.unit
def test_get_all_sort_most_downvoted(tmp_db: MeowDB) -> None:
    aid = _aid(tmp_db)
    id1 = tmp_db.add(_sound(aid))
    id2 = tmp_db.add(_sound(aid))
    tmp_db.record_feedback(id1, is_upvote=False)
    tmp_db.record_feedback(id2, is_upvote=False)
    tmp_db.record_feedback(id2, is_upvote=False)
    results = tmp_db.get_all(sort="most_downvoted")
    assert results[0]["id"] == id2


@pytest.mark.unit
def test_get_all_sort_most_upvoted(tmp_db: MeowDB) -> None:
    aid = _aid(tmp_db)
    id1 = tmp_db.add(_sound(aid))
    id2 = tmp_db.add(_sound(aid))
    tmp_db.record_feedback(id1, is_upvote=True)
    tmp_db.record_feedback(id2, is_upvote=True)
    tmp_db.record_feedback(id1, is_upvote=True)
    results = tmp_db.get_all(sort="most_upvoted")
    assert results[0]["id"] == id1


@pytest.mark.unit
def test_get_stats_includes_vote_leaderboards(tmp_db: MeowDB) -> None:
    aid = _aid(tmp_db)
    id1 = tmp_db.add(_sound(aid))
    id2 = tmp_db.add(_sound(aid))
    tmp_db.record_feedback(id1, is_upvote=True)
    tmp_db.record_feedback(id2, is_upvote=False)
    stats = tmp_db.get_stats()
    assert len(stats["most_upvoted"]) == 1
    assert stats["most_upvoted"][0]["id"] == id1
    assert len(stats["most_downvoted"]) == 1
    assert stats["most_downvoted"][0]["id"] == id2


@pytest.mark.unit
def test_switch_feedback(tmp_db: MeowDB) -> None:
    sound_id = tmp_db.add(_sound(_aid(tmp_db)))
    tmp_db.record_feedback(sound_id, is_upvote=True)
    assert tmp_db.switch_feedback(sound_id, is_upvote=False) is True
    result = tmp_db.get_by_id(sound_id)
    assert result is not None
    assert result["upvote_count"] == 0
    assert result["downvote_count"] == 1


@pytest.mark.unit
def test_switch_feedback_prevents_negative(tmp_db: MeowDB) -> None:
    sound_id = tmp_db.add(_sound(_aid(tmp_db)))
    tmp_db.switch_feedback(sound_id, is_upvote=True)
    result = tmp_db.get_by_id(sound_id)
    assert result is not None
    assert result["downvote_count"] == 0  # MAX(..., 0) prevents going negative
    assert result["upvote_count"] == 1


@pytest.mark.unit
def test_switch_feedback_missing_id(tmp_db: MeowDB) -> None:
    assert tmp_db.switch_feedback("nonexistent", is_upvote=True) is False


# =============================================================================
# get_count
# =============================================================================


@pytest.mark.unit
def test_get_count_animal_id_filter(tmp_db: MeowDB) -> None:
    squishy_id = _aid(tmp_db)
    dog_id = tmp_db.add_animal("Rex", "dog")
    tmp_db.add(_sound(squishy_id))
    tmp_db.add(_sound(squishy_id))
    tmp_db.add(_sound(dog_id))
    assert tmp_db.get_count(animal_id=squishy_id) == 2
    assert tmp_db.get_count(animal_id=dog_id) == 1
    assert tmp_db.get_count() == 3


# =============================================================================
# Job staging flow
# =============================================================================


@pytest.mark.unit
def test_create_job(tmp_db: MeowDB) -> None:
    job_id = tmp_db.create_job("recording.m4a", _aid(tmp_db))
    job = tmp_db.get_job(job_id)
    assert job is not None
    assert job["id"] == job_id
    assert job["source_filename"] == "recording.m4a"
    assert job["status"] == "pending"


@pytest.mark.unit
def test_create_job_stores_animal_id(tmp_db: MeowDB) -> None:
    aid = _aid(tmp_db)
    job_id = tmp_db.create_job("recording.m4a", aid)
    job = tmp_db.get_job(job_id)
    assert job is not None
    assert job["animal_id"] == aid


@pytest.mark.unit
def test_create_job_returns_unique_ids(tmp_db: MeowDB) -> None:
    aid = _aid(tmp_db)
    id1 = tmp_db.create_job("a.m4a", aid)
    id2 = tmp_db.create_job("b.m4a", aid)
    assert id1 != id2


@pytest.mark.unit
def test_get_job_missing(tmp_db: MeowDB) -> None:
    assert tmp_db.get_job("nonexistent") is None


@pytest.mark.unit
def test_update_job_status(tmp_db: MeowDB) -> None:
    job_id = tmp_db.create_job("recording.m4a", _aid(tmp_db))
    tmp_db.update_job_status(job_id, "processing")
    job = tmp_db.get_job(job_id)
    assert job is not None
    assert job["status"] == "processing"


@pytest.mark.unit
def test_update_job_status_with_error(tmp_db: MeowDB) -> None:
    job_id = tmp_db.create_job("recording.m4a", _aid(tmp_db))
    tmp_db.update_job_status(job_id, "failed", error="ffmpeg not found")
    job = tmp_db.get_job(job_id)
    assert job is not None
    assert job["status"] == "failed"
    assert job["error"] == "ffmpeg not found"


@pytest.mark.unit
def test_add_segments(tmp_db: MeowDB) -> None:
    job_id = tmp_db.create_job("recording.m4a", _aid(tmp_db))
    tmp_db.add_segments(job_id, [_segment(0), _segment(1)])
    tmp_db.update_job_status(job_id, "ready")
    job = tmp_db.get_job(job_id)
    assert job is not None
    assert "segments" in job
    assert len(job["segments"]) == 2


@pytest.mark.unit
def test_add_segments_waveform_parsed(tmp_db: MeowDB) -> None:
    job_id = tmp_db.create_job("recording.m4a", _aid(tmp_db))
    tmp_db.add_segments(job_id, [_segment(0, waveform_data=[0.1, 0.5, 0.9])])
    tmp_db.update_job_status(job_id, "ready")
    job = tmp_db.get_job(job_id)
    assert job is not None
    seg = job["segments"][0]
    assert seg["waveform_data"] == [0.1, 0.5, 0.9]


@pytest.mark.unit
def test_segments_not_included_before_ready(tmp_db: MeowDB) -> None:
    job_id = tmp_db.create_job("recording.m4a", _aid(tmp_db))
    tmp_db.add_segments(job_id, [_segment(0)])
    job = tmp_db.get_job(job_id)
    assert job is not None
    assert "segments" not in job


@pytest.mark.unit
def test_update_segment_status(tmp_db: MeowDB) -> None:
    job_id = tmp_db.create_job("recording.m4a", _aid(tmp_db))
    tmp_db.add_segments(job_id, [_segment(0)])
    tmp_db.update_job_status(job_id, "ready")
    job = tmp_db.get_job(job_id)
    assert job is not None
    seg_id = job["segments"][0]["id"]
    tmp_db.update_segment_status(seg_id, "accepted")
    tmp_db.update_job_status(job_id, "ready")
    job2 = tmp_db.get_job(job_id)
    assert job2 is not None
    assert job2["segments"][0]["status"] == "accepted"


def _create_staging_files(tmp_path: Path, count: int) -> list[dict]:
    staging = tmp_path / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    segs = []
    for i in range(count):
        wav = staging / f"seg_{i}.wav"
        mp3 = staging / f"seg_{i}.mp3"
        wav.write_bytes(b"RIFF" + b"\x00" * 100)
        mp3.write_bytes(b"\xff\xfb" + b"\x00" * 100)
        segs.append(_segment(i, wav_path=str(wav)))
    return segs


@pytest.mark.unit
def test_commit_job_creates_sound_records(tmp_db: MeowDB, tmp_path: Path) -> None:
    segs = _create_staging_files(tmp_path, 2)
    segs[0]["duration_ms"] = 900
    segs[1]["duration_ms"] = 700
    job_id = tmp_db.create_job("recording.m4a", _aid(tmp_db))
    tmp_db.add_segments(job_id, segs)
    tmp_db.update_job_status(job_id, "ready")
    job = tmp_db.get_job(job_id)
    assert job is not None
    seg_ids = [s["id"] for s in job["segments"]]
    wav_dir = tmp_path / "wav"
    mp3_dir = tmp_path / "mp3"

    new_ids = tmp_db.commit_job(
        job_id, accepted_ids=seg_ids[:1], rejected_ids=seg_ids[1:], wav_dir=wav_dir, mp3_dir=mp3_dir
    )
    assert len(new_ids) == 1

    sound = tmp_db.get_by_id(new_ids[0])
    assert sound is not None
    assert sound["duration_ms"] == 900


@pytest.mark.unit
def test_commit_job_all_accepted(tmp_db: MeowDB, tmp_path: Path) -> None:
    segs = _create_staging_files(tmp_path, 3)
    job_id = tmp_db.create_job("recording.m4a", _aid(tmp_db))
    tmp_db.add_segments(job_id, segs)
    tmp_db.update_job_status(job_id, "ready")
    job = tmp_db.get_job(job_id)
    assert job is not None
    seg_ids = [s["id"] for s in job["segments"]]
    wav_dir = tmp_path / "wav"
    mp3_dir = tmp_path / "mp3"

    new_ids = tmp_db.commit_job(
        job_id, accepted_ids=seg_ids, rejected_ids=[], wav_dir=wav_dir, mp3_dir=mp3_dir
    )
    assert len(new_ids) == 3
    assert tmp_db.get_all() != []


@pytest.mark.unit
def test_commit_job_all_rejected(tmp_db: MeowDB, tmp_path: Path) -> None:
    segs = _create_staging_files(tmp_path, 1)
    job_id = tmp_db.create_job("recording.m4a", _aid(tmp_db))
    tmp_db.add_segments(job_id, segs)
    tmp_db.update_job_status(job_id, "ready")
    job = tmp_db.get_job(job_id)
    assert job is not None
    seg_ids = [s["id"] for s in job["segments"]]
    wav_dir = tmp_path / "wav"
    mp3_dir = tmp_path / "mp3"

    new_ids = tmp_db.commit_job(
        job_id, accepted_ids=[], rejected_ids=seg_ids, wav_dir=wav_dir, mp3_dir=mp3_dir
    )
    assert new_ids == []
    assert tmp_db.get_all() == []


@pytest.mark.unit
def test_commit_job_marks_job_committed(tmp_db: MeowDB, tmp_path: Path) -> None:
    segs = _create_staging_files(tmp_path, 1)
    job_id = tmp_db.create_job("recording.m4a", _aid(tmp_db))
    tmp_db.add_segments(job_id, segs)
    tmp_db.update_job_status(job_id, "ready")
    job = tmp_db.get_job(job_id)
    assert job is not None
    seg_ids = [s["id"] for s in job["segments"]]
    wav_dir = tmp_path / "wav"
    mp3_dir = tmp_path / "mp3"
    tmp_db.commit_job(
        job_id, accepted_ids=seg_ids, rejected_ids=[], wav_dir=wav_dir, mp3_dir=mp3_dir
    )

    committed_job = tmp_db.get_job(job_id)
    assert committed_job is not None
    assert committed_job["status"] == "committed"


@pytest.mark.unit
def test_delete_job(tmp_db: MeowDB) -> None:
    job_id = tmp_db.create_job("recording.m4a", _aid(tmp_db))
    tmp_db.delete_job(job_id)
    assert tmp_db.get_job(job_id) is None


@pytest.mark.unit
def test_delete_job_cascades_segments(tmp_db: MeowDB) -> None:
    job_id = tmp_db.create_job("recording.m4a", _aid(tmp_db))
    tmp_db.add_segments(job_id, [_segment(0)])
    tmp_db.update_job_status(job_id, "ready")
    tmp_db.delete_job(job_id)
    assert tmp_db.get_job(job_id) is None


# =============================================================================
# Sound grouping helpers
# =============================================================================


@pytest.mark.unit
def test_get_sound_animal_groups(tmp_db: MeowDB) -> None:
    squishy_id = _aid(tmp_db)
    dog_id = tmp_db.add_animal("Rex", "dog")
    s1 = tmp_db.add(_sound(squishy_id))
    s2 = tmp_db.add(_sound(dog_id))
    groups = tmp_db.get_sound_animal_groups()
    assert groups[s1] == squishy_id
    assert groups[s2] == dog_id


@pytest.mark.unit
def test_get_sound_species_groups(tmp_db: MeowDB) -> None:
    squishy_id = _aid(tmp_db)
    dog_id = tmp_db.add_animal("Rex", "dog")
    s1 = tmp_db.add(_sound(squishy_id))
    s2 = tmp_db.add(_sound(dog_id))
    groups = tmp_db.get_sound_species_groups()
    assert groups[s1] == "cat"
    assert groups[s2] == "dog"


# =============================================================================
# Uniqueness scores
# =============================================================================


@pytest.mark.unit
def test_update_uniqueness_scores_bulk_writes_both_columns(tmp_db: MeowDB) -> None:
    aid = _aid(tmp_db)
    s1 = tmp_db.add(_sound(aid))
    s2 = tmp_db.add(_sound(aid))

    tmp_db.update_uniqueness_scores_bulk(
        animal_scores={s1: 0.9, s2: 0.7},
        species_scores={s1: 0.8, s2: 0.6},
    )

    sound1 = tmp_db.get_by_id(s1)
    sound2 = tmp_db.get_by_id(s2)
    assert sound1 is not None
    assert sound1["animal_uniqueness_score"] == pytest.approx(0.9)
    assert sound1["species_uniqueness_score"] == pytest.approx(0.8)
    assert sound2 is not None
    assert sound2["animal_uniqueness_score"] == pytest.approx(0.7)
    assert sound2["species_uniqueness_score"] == pytest.approx(0.6)


# =============================================================================
# Photos
# =============================================================================


@pytest.mark.unit
def test_get_random_photo_for_animal_scoped(tmp_db: MeowDB) -> None:
    squishy_id = _aid(tmp_db)
    dog_id = tmp_db.add_animal("Rex", "dog")
    tmp_db.add_photo("squishy.jpg", squishy_id)
    tmp_db.add_photo("rex.jpg", dog_id)

    result = tmp_db.get_random_photo_for_animal(squishy_id)
    assert result is not None
    assert result["animal_id"] == squishy_id
    assert result["filename"] == "squishy.jpg"


@pytest.mark.unit
def test_get_random_photo_for_animal_exclude_falls_back(tmp_db: MeowDB) -> None:
    squishy_id = _aid(tmp_db)
    photo_id = tmp_db.add_photo("only.jpg", squishy_id)

    # With only one photo, exclude_id falls back to returning it
    result = tmp_db.get_random_photo_for_animal(squishy_id, exclude_id=photo_id)
    assert result is not None
    assert result["id"] == photo_id


@pytest.mark.unit
def test_get_random_photo_includes_animal_id(tmp_db: MeowDB) -> None:
    squishy_id = _aid(tmp_db)
    tmp_db.add_photo("pic.jpg", squishy_id)

    result = tmp_db.get_random_photo()
    assert result is not None
    assert "animal_id" in result
    assert result["animal_id"] == squishy_id


# =============================================================================
# Stats
# =============================================================================


@pytest.mark.unit
def test_get_stats_empty(tmp_db: MeowDB) -> None:
    stats = tmp_db.get_stats()
    assert stats["total_sounds"] == 0
    assert stats["total_duration_ms"] == 0
    assert stats["avg_duration_ms"] == 0
    assert stats["most_played"] == []
    assert stats["recent"] == []
    assert stats["label_counts"] == {}


@pytest.mark.unit
def test_get_stats_aggregates(tmp_db: MeowDB) -> None:
    aid = _aid(tmp_db)
    tmp_db.add(_sound(aid, duration_ms=1000))
    tmp_db.add(_sound(aid, duration_ms=3000))
    stats = tmp_db.get_stats()
    assert stats["total_sounds"] == 2
    assert stats["total_duration_ms"] == 4000
    assert stats["avg_duration_ms"] == 2000.0


@pytest.mark.unit
def test_get_stats_most_played(tmp_db: MeowDB) -> None:
    aid = _aid(tmp_db)
    ids = [tmp_db.add(_sound(aid)) for _ in range(6)]
    for _ in range(5):
        tmp_db.increment_play_count(ids[0])
    stats = tmp_db.get_stats()
    assert len(stats["most_played"]) == 5
    assert stats["most_played"][0]["id"] == ids[0]


@pytest.mark.unit
def test_get_stats_recent(tmp_db: MeowDB) -> None:
    aid = _aid(tmp_db)
    for i in range(12):
        tmp_db.add(_sound(aid, duration_ms=i * 100))
    stats = tmp_db.get_stats()
    assert len(stats["recent"]) == 10


@pytest.mark.unit
def test_get_stats_label_counts(tmp_db: MeowDB) -> None:
    aid = _aid(tmp_db)
    tmp_db.add(_sound(aid, labels=["morning", "loud"]))
    tmp_db.add(_sound(aid, labels=["morning"]))
    tmp_db.add(_sound(aid, labels=["evening"]))
    stats = tmp_db.get_stats()
    assert stats["label_counts"]["morning"] == 2
    assert stats["label_counts"]["loud"] == 1
    assert stats["label_counts"]["evening"] == 1


@pytest.mark.unit
def test_get_stats_species_counts(tmp_db: MeowDB) -> None:
    squishy_id = _aid(tmp_db)
    dog_id = tmp_db.add_animal("Rex", "dog")
    tmp_db.add(_sound(squishy_id))
    tmp_db.add(_sound(squishy_id))
    tmp_db.add(_sound(dog_id))
    stats = tmp_db.get_stats()
    assert stats["species_counts"]["cat"] == 2
    assert stats["species_counts"]["dog"] == 1


# =============================================================================
# Labels
# =============================================================================


@pytest.mark.unit
def test_get_labels_empty(tmp_db: MeowDB) -> None:
    assert tmp_db.get_labels() == []


@pytest.mark.unit
def test_get_labels_with_sounds(tmp_db: MeowDB) -> None:
    aid = _aid(tmp_db)
    tmp_db.add(_sound(aid, labels=["happy", "loud"]))
    tmp_db.add(_sound(aid, labels=["happy"]))
    labels = tmp_db.get_labels()
    label_map = {item["label"]: item["count"] for item in labels}
    assert label_map["happy"] == 2
    assert label_map["loud"] == 1


@pytest.mark.unit
def test_get_labels_sorted_alphabetically(tmp_db: MeowDB) -> None:
    tmp_db.add(_sound(_aid(tmp_db), labels=["zebra", "apple", "meow"]))
    labels = tmp_db.get_labels()
    names = [item["label"] for item in labels]
    assert names == sorted(names)


@pytest.mark.unit
def test_get_labels_unlabeled_sound_excluded(tmp_db: MeowDB) -> None:
    tmp_db.add(_sound(_aid(tmp_db), labels=[]))
    assert tmp_db.get_labels() == []


# =============================================================================
# Animal fields on sound queries
# =============================================================================


@pytest.mark.unit
def test_get_all_and_get_by_id_include_animal_fields(tmp_db: MeowDB) -> None:
    """get_all() and get_by_id() rows include non-null animal_name and animal_species."""
    sound_id = tmp_db.add(_sound(_aid(tmp_db)))

    rows = tmp_db.get_all()
    assert len(rows) == 1
    assert rows[0]["animal_name"] == "Squishy"
    assert rows[0]["animal_species"] == "cat"

    result = tmp_db.get_by_id(sound_id)
    assert result is not None
    assert result["animal_name"] == "Squishy"
    assert result["animal_species"] == "cat"


# =============================================================================
# commit_job — cross-job segment isolation
# =============================================================================


@pytest.mark.unit
def test_commit_job_ignores_foreign_segment_ids(tmp_db: MeowDB, tmp_path: Path) -> None:
    """Segment IDs that belong to a different job are silently ignored by commit_job."""
    staging_a = tmp_path / "staging_a"
    staging_b = tmp_path / "staging_b"
    staging_a.mkdir(parents=True)
    staging_b.mkdir(parents=True)

    # Minimal WAV/MP3 stubs for each job's segment
    (staging_a / "seg_0.wav").write_bytes(b"RIFF" + b"\x00" * 100)
    (staging_a / "seg_0.mp3").write_bytes(b"\xff\xfb" + b"\x00" * 100)
    (staging_b / "seg_0.wav").write_bytes(b"RIFF" + b"\x00" * 100)
    (staging_b / "seg_0.mp3").write_bytes(b"\xff\xfb" + b"\x00" * 100)

    aid = _aid(tmp_db)
    job_a_id = tmp_db.create_job("a.m4a", aid)
    job_b_id = tmp_db.create_job("b.m4a", aid)

    tmp_db.add_segments(
        job_a_id, [_segment(0, wav_path=str(staging_a / "seg_0.wav"), duration_ms=600)]
    )
    tmp_db.add_segments(
        job_b_id, [_segment(0, wav_path=str(staging_b / "seg_0.wav"), duration_ms=700)]
    )
    tmp_db.update_job_status(job_a_id, "ready")
    tmp_db.update_job_status(job_b_id, "ready")

    job_a = tmp_db.get_job(job_a_id)
    job_b = tmp_db.get_job(job_b_id)
    assert job_a is not None and job_b is not None
    seg_a_id = job_a["segments"][0]["id"]
    seg_b_id = job_b["segments"][0]["id"]

    wav_dir = tmp_path / "wav"
    mp3_dir = tmp_path / "mp3"

    # Commit job A, passing seg_b_id as an accepted ID — it belongs to job B and must be ignored
    new_ids = tmp_db.commit_job(
        job_a_id,
        accepted_ids=[seg_a_id, seg_b_id],
        rejected_ids=[],
        wav_dir=wav_dir,
        mp3_dir=mp3_dir,
    )

    # Only job A's segment produces a sound record
    assert len(new_ids) == 1
    assert tmp_db.get_count() == 1

    # Job B's segment remains in "pending" state — completely untouched
    job_b_after = tmp_db.get_job(job_b_id)
    assert job_b_after is not None
    assert job_b_after["segments"][0]["status"] == "pending"
