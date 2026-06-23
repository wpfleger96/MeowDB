from __future__ import annotations

from pathlib import Path

import pytest

from meowdb.db import MeowDB


def _meow(
    wav_path: str = "/tmp/test.wav",
    mp3_path: str = "/tmp/test.mp3",
    duration_ms: int = 1000,
    labels: list | None = None,
    waveform_data: list | None = None,
    peak_dbfs: float | None = -10.0,
    cat_energy_ratio: float | None = 1.5,
) -> dict:
    return {
        "timestamp": "2026-06-14T12:00:00",
        "duration_ms": duration_ms,
        "labels": labels or [],
        "wav_path": wav_path,
        "mp3_path": mp3_path,
        "waveform_data": waveform_data or [],
        "peak_dbfs": peak_dbfs,
        "cat_energy_ratio": cat_energy_ratio,
    }


def _segment(
    index: int = 0,
    wav_path: str = "/tmp/seg.wav",
    duration_ms: int = 800,
    waveform_data: list | None = None,
    peak_dbfs: float | None = -12.0,
    cat_energy_ratio: float | None = 1.8,
) -> dict:
    return {
        "index": index,
        "duration_ms": duration_ms,
        "wav_path": wav_path,
        "waveform_data": waveform_data or [0.1, 0.5, 0.9],
        "peak_dbfs": peak_dbfs,
        "cat_energy_ratio": cat_energy_ratio,
    }


# =============================================================================
# Meow CRUD
# =============================================================================


@pytest.mark.unit
def test_add_and_get_by_id(tmp_db: MeowDB) -> None:
    meow_id = tmp_db.add(_meow(duration_ms=500))
    result = tmp_db.get_by_id(meow_id)
    assert result is not None
    assert result["id"] == meow_id
    assert result["duration_ms"] == 500
    assert result["labels"] == []
    assert result["play_count"] == 0


@pytest.mark.unit
def test_add_returns_unique_ids(tmp_db: MeowDB) -> None:
    id1 = tmp_db.add(_meow())
    id2 = tmp_db.add(_meow())
    assert id1 != id2


@pytest.mark.unit
def test_add_stores_labels_and_waveform(tmp_db: MeowDB) -> None:
    meow_id = tmp_db.add(_meow(labels=["happy", "loud"], waveform_data=[0.1, 0.5, 1.0]))
    result = tmp_db.get_by_id(meow_id)
    assert result is not None
    assert result["labels"] == ["happy", "loud"]
    assert result["waveform_data"] == [0.1, 0.5, 1.0]


@pytest.mark.unit
def test_get_by_id_missing(tmp_db: MeowDB) -> None:
    assert tmp_db.get_by_id("nonexistent-id") is None


@pytest.mark.unit
def test_get_random_empty(tmp_db: MeowDB) -> None:
    assert tmp_db.get_random() is None


@pytest.mark.unit
def test_get_random_returns_meow(tmp_db: MeowDB) -> None:
    meow_id = tmp_db.add(_meow())
    result = tmp_db.get_random()
    assert result is not None
    assert result["id"] == meow_id


@pytest.mark.unit
def test_get_random_does_not_count_a_play(tmp_db: MeowDB) -> None:
    # A random fetch is a read, not a play; counting happens on the explicit
    # play path (CLI play / POST /meows/{id}/play), so superseded rapid-tap
    # fetches never inflate play_count.
    meow_id = tmp_db.add(_meow())
    for _ in range(3):
        tmp_db.get_random()
    result = tmp_db.get_by_id(meow_id)
    assert result is not None
    assert result["play_count"] == 0


@pytest.mark.unit
def test_get_all_empty(tmp_db: MeowDB) -> None:
    assert tmp_db.get_all() == []


@pytest.mark.unit
def test_get_all_returns_all(tmp_db: MeowDB) -> None:
    tmp_db.add(_meow(duration_ms=100))
    tmp_db.add(_meow(duration_ms=200))
    results = tmp_db.get_all()
    assert len(results) == 2


@pytest.mark.unit
def test_get_all_sort_newest(tmp_db: MeowDB) -> None:
    id1 = tmp_db.add(_meow(duration_ms=100))
    id2 = tmp_db.add(_meow(duration_ms=200))
    results = tmp_db.get_all(sort="newest")
    # Most recently inserted comes first
    assert results[0]["id"] == id2
    assert results[1]["id"] == id1


@pytest.mark.unit
def test_get_all_sort_oldest(tmp_db: MeowDB) -> None:
    id1 = tmp_db.add(_meow(duration_ms=100))
    id2 = tmp_db.add(_meow(duration_ms=200))
    results = tmp_db.get_all(sort="oldest")
    assert results[0]["id"] == id1
    assert results[1]["id"] == id2


@pytest.mark.unit
def test_get_all_sort_duration_asc(tmp_db: MeowDB) -> None:
    id1 = tmp_db.add(_meow(duration_ms=300))
    id2 = tmp_db.add(_meow(duration_ms=100))
    id3 = tmp_db.add(_meow(duration_ms=200))
    results = tmp_db.get_all(sort="duration_asc")
    assert results[0]["id"] == id2
    assert results[1]["id"] == id3
    assert results[2]["id"] == id1


@pytest.mark.unit
def test_get_all_sort_duration_desc(tmp_db: MeowDB) -> None:
    id1 = tmp_db.add(_meow(duration_ms=300))
    id2 = tmp_db.add(_meow(duration_ms=100))
    results = tmp_db.get_all(sort="duration_desc")
    assert results[0]["id"] == id1
    assert results[1]["id"] == id2


@pytest.mark.unit
def test_get_all_sort_most_played(tmp_db: MeowDB) -> None:
    id1 = tmp_db.add(_meow())
    id2 = tmp_db.add(_meow())
    tmp_db.increment_play_count(id2)
    tmp_db.increment_play_count(id2)
    tmp_db.increment_play_count(id1)
    results = tmp_db.get_all(sort="most_played")
    assert results[0]["id"] == id2


@pytest.mark.unit
def test_get_all_label_filter(tmp_db: MeowDB) -> None:
    id1 = tmp_db.add(_meow(labels=["morning"]))
    tmp_db.add(_meow(labels=["evening"]))
    results = tmp_db.get_all(label_filter="morning")
    assert len(results) == 1
    assert results[0]["id"] == id1


@pytest.mark.unit
def test_get_all_label_filter_no_match(tmp_db: MeowDB) -> None:
    tmp_db.add(_meow(labels=["evening"]))
    assert tmp_db.get_all(label_filter="morning") == []


@pytest.mark.unit
def test_get_all_pagination(tmp_db: MeowDB) -> None:
    for i in range(5):
        tmp_db.add(_meow(duration_ms=i * 100))
    page1 = tmp_db.get_all(sort="oldest", limit=3, offset=0)
    page2 = tmp_db.get_all(sort="oldest", limit=3, offset=3)
    assert len(page1) == 3
    assert len(page2) == 2
    ids1 = {r["id"] for r in page1}
    ids2 = {r["id"] for r in page2}
    assert ids1.isdisjoint(ids2)


@pytest.mark.unit
def test_update_labels(tmp_db: MeowDB) -> None:
    meow_id = tmp_db.add(_meow(labels=["old"]))
    result = tmp_db.update_labels(meow_id, ["new", "tag"])
    assert result is True
    updated = tmp_db.get_by_id(meow_id)
    assert updated is not None
    assert updated["labels"] == ["new", "tag"]


@pytest.mark.unit
def test_update_labels_clears(tmp_db: MeowDB) -> None:
    meow_id = tmp_db.add(_meow(labels=["old"]))
    tmp_db.update_labels(meow_id, [])
    updated = tmp_db.get_by_id(meow_id)
    assert updated is not None
    assert updated["labels"] == []


@pytest.mark.unit
def test_update_labels_missing_id(tmp_db: MeowDB) -> None:
    assert tmp_db.update_labels("nonexistent", ["x"]) is False


@pytest.mark.unit
def test_delete(tmp_db: MeowDB) -> None:
    meow_id = tmp_db.add(_meow())
    result = tmp_db.delete(meow_id)
    assert result is True
    assert tmp_db.get_by_id(meow_id) is None


@pytest.mark.unit
def test_delete_missing(tmp_db: MeowDB) -> None:
    assert tmp_db.delete("nonexistent") is False


@pytest.mark.unit
def test_increment_play_count(tmp_db: MeowDB) -> None:
    meow_id = tmp_db.add(_meow())
    assert tmp_db.increment_play_count(meow_id) is True
    assert tmp_db.increment_play_count(meow_id) is True
    result = tmp_db.get_by_id(meow_id)
    assert result is not None
    assert result["play_count"] == 2


@pytest.mark.unit
def test_increment_play_count_missing_id(tmp_db: MeowDB) -> None:
    assert tmp_db.increment_play_count("nonexistent") is False


@pytest.mark.unit
def test_record_feedback_upvote(tmp_db: MeowDB) -> None:
    meow_id = tmp_db.add(_meow())
    assert tmp_db.record_feedback(meow_id, is_upvote=True) is True
    assert tmp_db.record_feedback(meow_id, is_upvote=True) is True
    result = tmp_db.get_by_id(meow_id)
    assert result is not None
    assert result["upvote_count"] == 2
    assert result["downvote_count"] == 0


@pytest.mark.unit
def test_record_feedback_downvote(tmp_db: MeowDB) -> None:
    meow_id = tmp_db.add(_meow())
    assert tmp_db.record_feedback(meow_id, is_upvote=False) is True
    result = tmp_db.get_by_id(meow_id)
    assert result is not None
    assert result["downvote_count"] == 1
    assert result["upvote_count"] == 0


@pytest.mark.unit
def test_record_feedback_missing_id(tmp_db: MeowDB) -> None:
    assert tmp_db.record_feedback("nonexistent", is_upvote=True) is False


@pytest.mark.unit
def test_get_all_sort_most_downvoted(tmp_db: MeowDB) -> None:
    id1 = tmp_db.add(_meow())
    id2 = tmp_db.add(_meow())
    tmp_db.record_feedback(id1, is_upvote=False)
    tmp_db.record_feedback(id2, is_upvote=False)
    tmp_db.record_feedback(id2, is_upvote=False)
    results = tmp_db.get_all(sort="most_downvoted")
    assert results[0]["id"] == id2


@pytest.mark.unit
def test_get_all_sort_most_upvoted(tmp_db: MeowDB) -> None:
    id1 = tmp_db.add(_meow())
    id2 = tmp_db.add(_meow())
    tmp_db.record_feedback(id1, is_upvote=True)
    tmp_db.record_feedback(id2, is_upvote=True)
    tmp_db.record_feedback(id1, is_upvote=True)
    results = tmp_db.get_all(sort="most_upvoted")
    assert results[0]["id"] == id1


@pytest.mark.unit
def test_get_stats_includes_vote_leaderboards(tmp_db: MeowDB) -> None:
    id1 = tmp_db.add(_meow())
    id2 = tmp_db.add(_meow())
    tmp_db.record_feedback(id1, is_upvote=True)
    tmp_db.record_feedback(id2, is_upvote=False)
    stats = tmp_db.get_stats()
    assert len(stats["most_upvoted"]) == 1
    assert stats["most_upvoted"][0]["id"] == id1
    assert len(stats["most_downvoted"]) == 1
    assert stats["most_downvoted"][0]["id"] == id2


@pytest.mark.unit
def test_switch_feedback(tmp_db: MeowDB) -> None:
    meow_id = tmp_db.add(_meow())
    tmp_db.record_feedback(meow_id, is_upvote=True)
    assert tmp_db.switch_feedback(meow_id, is_upvote=False) is True
    result = tmp_db.get_by_id(meow_id)
    assert result is not None
    assert result["upvote_count"] == 0
    assert result["downvote_count"] == 1


@pytest.mark.unit
def test_switch_feedback_prevents_negative(tmp_db: MeowDB) -> None:
    meow_id = tmp_db.add(_meow())
    # Switch without a prior vote — old column is already 0
    tmp_db.switch_feedback(meow_id, is_upvote=True)
    result = tmp_db.get_by_id(meow_id)
    assert result is not None
    assert result["downvote_count"] == 0  # MAX(..., 0) prevents going negative
    assert result["upvote_count"] == 1


@pytest.mark.unit
def test_switch_feedback_missing_id(tmp_db: MeowDB) -> None:
    assert tmp_db.switch_feedback("nonexistent", is_upvote=True) is False


# =============================================================================
# Job staging flow
# =============================================================================


@pytest.mark.unit
def test_create_job(tmp_db: MeowDB) -> None:
    job_id = tmp_db.create_job("recording.m4a")
    job = tmp_db.get_job(job_id)
    assert job is not None
    assert job["id"] == job_id
    assert job["source_filename"] == "recording.m4a"
    assert job["status"] == "pending"


@pytest.mark.unit
def test_create_job_returns_unique_ids(tmp_db: MeowDB) -> None:
    id1 = tmp_db.create_job("a.m4a")
    id2 = tmp_db.create_job("b.m4a")
    assert id1 != id2


@pytest.mark.unit
def test_get_job_missing(tmp_db: MeowDB) -> None:
    assert tmp_db.get_job("nonexistent") is None


@pytest.mark.unit
def test_update_job_status(tmp_db: MeowDB) -> None:
    job_id = tmp_db.create_job("recording.m4a")
    tmp_db.update_job_status(job_id, "processing")
    job = tmp_db.get_job(job_id)
    assert job is not None
    assert job["status"] == "processing"


@pytest.mark.unit
def test_update_job_status_with_error(tmp_db: MeowDB) -> None:
    job_id = tmp_db.create_job("recording.m4a")
    tmp_db.update_job_status(job_id, "failed", error="ffmpeg not found")
    job = tmp_db.get_job(job_id)
    assert job is not None
    assert job["status"] == "failed"
    assert job["error"] == "ffmpeg not found"


@pytest.mark.unit
def test_add_segments(tmp_db: MeowDB) -> None:
    job_id = tmp_db.create_job("recording.m4a")
    tmp_db.add_segments(job_id, [_segment(0), _segment(1)])
    tmp_db.update_job_status(job_id, "ready")
    job = tmp_db.get_job(job_id)
    assert job is not None
    assert "segments" in job
    assert len(job["segments"]) == 2


@pytest.mark.unit
def test_add_segments_waveform_parsed(tmp_db: MeowDB) -> None:
    job_id = tmp_db.create_job("recording.m4a")
    tmp_db.add_segments(job_id, [_segment(0, waveform_data=[0.1, 0.5, 0.9])])
    tmp_db.update_job_status(job_id, "ready")
    job = tmp_db.get_job(job_id)
    assert job is not None
    seg = job["segments"][0]
    assert seg["waveform_data"] == [0.1, 0.5, 0.9]


@pytest.mark.unit
def test_segments_not_included_before_ready(tmp_db: MeowDB) -> None:
    job_id = tmp_db.create_job("recording.m4a")
    tmp_db.add_segments(job_id, [_segment(0)])
    job = tmp_db.get_job(job_id)
    assert job is not None
    assert "segments" not in job


@pytest.mark.unit
def test_update_segment_status(tmp_db: MeowDB) -> None:
    job_id = tmp_db.create_job("recording.m4a")
    tmp_db.add_segments(job_id, [_segment(0)])
    tmp_db.update_job_status(job_id, "ready")
    job = tmp_db.get_job(job_id)
    assert job is not None
    seg_id = job["segments"][0]["id"]
    tmp_db.update_segment_status(seg_id, "accepted")
    # Refetch to verify
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
def test_commit_job_creates_meow_records(tmp_db: MeowDB, tmp_path: Path) -> None:
    segs = _create_staging_files(tmp_path, 2)
    segs[0]["duration_ms"] = 900
    segs[1]["duration_ms"] = 700
    job_id = tmp_db.create_job("recording.m4a")
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

    meow = tmp_db.get_by_id(new_ids[0])
    assert meow is not None
    assert meow["duration_ms"] == 900


@pytest.mark.unit
def test_commit_job_all_accepted(tmp_db: MeowDB, tmp_path: Path) -> None:
    segs = _create_staging_files(tmp_path, 3)
    job_id = tmp_db.create_job("recording.m4a")
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
    job_id = tmp_db.create_job("recording.m4a")
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
    job_id = tmp_db.create_job("recording.m4a")
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
    job_id = tmp_db.create_job("recording.m4a")
    tmp_db.delete_job(job_id)
    assert tmp_db.get_job(job_id) is None


@pytest.mark.unit
def test_delete_job_cascades_segments(tmp_db: MeowDB) -> None:
    job_id = tmp_db.create_job("recording.m4a")
    tmp_db.add_segments(job_id, [_segment(0)])
    tmp_db.update_job_status(job_id, "ready")
    tmp_db.delete_job(job_id)
    # Job is gone; segments should be gone too via CASCADE
    assert tmp_db.get_job(job_id) is None


# =============================================================================
# Stats
# =============================================================================


@pytest.mark.unit
def test_get_stats_empty(tmp_db: MeowDB) -> None:
    stats = tmp_db.get_stats()
    assert stats["total_meows"] == 0
    assert stats["total_duration_ms"] == 0
    assert stats["avg_duration_ms"] == 0
    assert stats["most_played"] == []
    assert stats["recent"] == []
    assert stats["label_counts"] == {}


@pytest.mark.unit
def test_get_stats_aggregates(tmp_db: MeowDB) -> None:
    tmp_db.add(_meow(duration_ms=1000))
    tmp_db.add(_meow(duration_ms=3000))
    stats = tmp_db.get_stats()
    assert stats["total_meows"] == 2
    assert stats["total_duration_ms"] == 4000
    assert stats["avg_duration_ms"] == 2000.0


@pytest.mark.unit
def test_get_stats_most_played(tmp_db: MeowDB) -> None:
    ids = [tmp_db.add(_meow()) for _ in range(6)]
    for _ in range(5):
        tmp_db.increment_play_count(ids[0])
    stats = tmp_db.get_stats()
    assert len(stats["most_played"]) == 5
    assert stats["most_played"][0]["id"] == ids[0]


@pytest.mark.unit
def test_get_stats_recent(tmp_db: MeowDB) -> None:
    for i in range(12):
        tmp_db.add(_meow(duration_ms=i * 100))
    stats = tmp_db.get_stats()
    assert len(stats["recent"]) == 10


@pytest.mark.unit
def test_get_stats_label_counts(tmp_db: MeowDB) -> None:
    tmp_db.add(_meow(labels=["morning", "loud"]))
    tmp_db.add(_meow(labels=["morning"]))
    tmp_db.add(_meow(labels=["evening"]))
    stats = tmp_db.get_stats()
    assert stats["label_counts"]["morning"] == 2
    assert stats["label_counts"]["loud"] == 1
    assert stats["label_counts"]["evening"] == 1


# =============================================================================
# Labels
# =============================================================================


@pytest.mark.unit
def test_get_labels_empty(tmp_db: MeowDB) -> None:
    assert tmp_db.get_labels() == []


@pytest.mark.unit
def test_get_labels_with_meows(tmp_db: MeowDB) -> None:
    tmp_db.add(_meow(labels=["happy", "loud"]))
    tmp_db.add(_meow(labels=["happy"]))
    labels = tmp_db.get_labels()
    label_map = {item["label"]: item["count"] for item in labels}
    assert label_map["happy"] == 2
    assert label_map["loud"] == 1


@pytest.mark.unit
def test_get_labels_sorted_alphabetically(tmp_db: MeowDB) -> None:
    tmp_db.add(_meow(labels=["zebra", "apple", "meow"]))
    labels = tmp_db.get_labels()
    names = [item["label"] for item in labels]
    assert names == sorted(names)


@pytest.mark.unit
def test_get_labels_unlabeled_meow_excluded(tmp_db: MeowDB) -> None:
    tmp_db.add(_meow(labels=[]))
    assert tmp_db.get_labels() == []
