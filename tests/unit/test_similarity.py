from __future__ import annotations

import io
import math
import struct
import wave

from pathlib import Path

import pytest

from meowdb.db import MeowDB
from meowdb.similarity import MeowSimilarity, update_library_uniqueness


def _make_sine_wav(freq_hz: float, duration_s: float = 1.0, sr: int = 44100) -> bytes:
    n_samples = int(sr * duration_s)
    samples = [int(32767 * math.sin(2 * math.pi * freq_hz * i / sr)) for i in range(n_samples)]
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(struct.pack(f"<{n_samples}h", *samples))
    return buf.getvalue()


def test_fingerprint_dimension(tmp_path: Path) -> None:
    wav_path = tmp_path / "test.wav"
    wav_path.write_bytes(_make_sine_wav(500.0))
    sim = MeowSimilarity()
    fingerprint = sim.extract_fingerprint(wav_path)
    assert len(fingerprint) == 120


def test_fingerprint_deterministic(tmp_path: Path) -> None:
    wav_path = tmp_path / "test.wav"
    wav_path.write_bytes(_make_sine_wav(500.0))
    sim = MeowSimilarity()
    fp1 = sim.extract_fingerprint(wav_path)
    fp2 = sim.extract_fingerprint(wav_path)
    assert fp1 == fp2


def test_fingerprint_short_audio(tmp_path: Path) -> None:
    # 0.02s ≈ 880 samples — fewer than n_fft=2048, so delta features fall back to zeros
    wav_path = tmp_path / "short.wav"
    wav_path.write_bytes(_make_sine_wav(500.0, duration_s=0.02))
    sim = MeowSimilarity()
    fingerprint = sim.extract_fingerprint(wav_path)
    assert len(fingerprint) == 120


def test_scores_empty() -> None:
    sim = MeowSimilarity()
    assert sim.compute_uniqueness_scores({}) == {}


def test_scores_single() -> None:
    sim = MeowSimilarity()
    result = sim.compute_uniqueness_scores({"a": [0.0] * 120})
    assert result == {"a": None}


def test_scores_two_identical() -> None:
    sim = MeowSimilarity()
    fingerprints = {
        "a": [0.0] * 120,
        "b": [0.0] * 120,
    }
    result = sim.compute_uniqueness_scores(fingerprints)
    assert result["a"] == pytest.approx(0.0)
    assert result["b"] == pytest.approx(0.0)


def test_scores_percentile_range() -> None:
    sim = MeowSimilarity()
    # 4 identical cluster vectors + 1 antiparallel outlier guarantees the outlier
    # scores 100.0 (most unique) and the cluster members score 0.0 (least unique),
    # covering the full range. Constant-magnitude vectors like [5]*120 vs [10]*120
    # must NOT be used — they're colinear after z-score and all get cos_sim=1.0.
    fingerprints = {
        "a": [1.0, 0.0] * 60,
        "b": [1.0, 0.0] * 60,
        "c": [1.0, 0.0] * 60,
        "d": [1.0, 0.0] * 60,
        "e": [0.0, 1.0] * 60,
    }
    result = sim.compute_uniqueness_scores(fingerprints)
    assert all(s is not None for s in result.values())
    scores = [s for s in result.values() if s is not None]
    assert all(0.0 <= s <= 100.0 for s in scores)
    assert min(scores) == pytest.approx(0.0)
    assert max(scores) == pytest.approx(100.0)


def test_scores_knn_degrades_gracefully() -> None:
    sim = MeowSimilarity(k_neighbors=5)
    fingerprints = {
        "a": [0.0] * 120,
        "b": [1.0] * 120,
    }
    result = sim.compute_uniqueness_scores(fingerprints)
    assert all(s is not None for s in result.values())
    for score in (s for s in result.values() if s is not None):
        assert 0.0 <= score <= 100.0


def test_fingerprint_different_audio(tmp_path: Path) -> None:
    low_path = tmp_path / "low.wav"
    high_path = tmp_path / "high.wav"
    low_path.write_bytes(_make_sine_wav(500.0))
    high_path.write_bytes(_make_sine_wav(3000.0))
    sim = MeowSimilarity()
    fp_low = sim.extract_fingerprint(low_path)
    fp_high = sim.extract_fingerprint(high_path)
    assert fp_low != fp_high


# ---------------------------------------------------------------------------
# Helpers for update_library_uniqueness tests
# ---------------------------------------------------------------------------


def _add_sound(db: MeowDB, animal_id: str, wav_path: Path) -> str:
    """Insert a minimal sound record into the DB pointing at wav_path."""
    return db.add(
        {
            "animal_id": animal_id,
            "timestamp": "",
            "duration_ms": 1000,
            "wav_path": str(wav_path),
            "mp3_path": str(wav_path),  # placeholder — tests don't decode mp3
            "waveform_data": [],
            "peak_dbfs": -10.0,
            "species_energy_ratio": 5.0,
        }
    )


# ---------------------------------------------------------------------------
# update_library_uniqueness tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_update_library_two_score_flow(tmp_path: Path) -> None:
    """2 animals of the same species × 3 sounds each → all 6 sounds receive both
    uniqueness scores, and each animal's scores match a solo-pool recompute."""
    db = MeowDB(tmp_path / "meow.db")
    squishy_id = db.get_animals()[0]["id"]  # auto-seeded cat
    fluffy_id = db.add_animal("Fluffy", "cat")

    wav_dir = tmp_path / "wavs"
    wav_dir.mkdir()

    squishy_ids: list[str] = []
    for i, freq in enumerate([400.0, 600.0, 800.0]):
        p = wav_dir / f"s_{i}.wav"
        p.write_bytes(_make_sine_wav(freq))
        squishy_ids.append(_add_sound(db, squishy_id, p))

    fluffy_ids: list[str] = []
    for i, freq in enumerate([1000.0, 1200.0, 1400.0]):
        p = wav_dir / f"f_{i}.wav"
        p.write_bytes(_make_sine_wav(freq))
        fluffy_ids.append(_add_sound(db, fluffy_id, p))

    update_library_uniqueness(db, squishy_ids + fluffy_ids)

    # All 6 sounds must have both scores populated.
    for sid in squishy_ids + fluffy_ids:
        row = db.get_by_id(sid)
        assert row is not None
        assert row["animal_uniqueness_score"] is not None
        assert row["species_uniqueness_score"] is not None

    # Each animal's stored scores must match a solo compute_uniqueness_scores call.
    sim = MeowSimilarity()
    fps = db.get_all_fingerprints()
    for pool_ids in (squishy_ids, fluffy_ids):
        pool = {sid: fps[sid] for sid in pool_ids}
        expected = sim.compute_uniqueness_scores(pool)
        for sid in pool_ids:
            row = db.get_by_id(sid)
            assert row is not None
            assert row["animal_uniqueness_score"] == pytest.approx(expected[sid], abs=0.01)

    db.close()


@pytest.mark.unit
def test_cross_species_isolation(tmp_path: Path) -> None:
    """Species pools are disjoint: dog species scores equal a solo dog-pool recompute
    regardless of how many cat sounds are in the DB."""
    db = MeowDB(tmp_path / "meow.db")
    squishy_id = db.get_animals()[0]["id"]
    rex_id = db.add_animal("Rex", "dog")

    wav_dir = tmp_path / "wavs"
    wav_dir.mkdir()

    cat_ids: list[str] = []
    for i, freq in enumerate([500.0, 700.0, 900.0]):
        p = wav_dir / f"cat_{i}.wav"
        p.write_bytes(_make_sine_wav(freq))
        cat_ids.append(_add_sound(db, squishy_id, p))

    dog_ids: list[str] = []
    for i, freq in enumerate([400.0, 600.0, 800.0]):
        p = wav_dir / f"dog_{i}.wav"
        p.write_bytes(_make_sine_wav(freq))
        dog_ids.append(_add_sound(db, rex_id, p))

    update_library_uniqueness(db, cat_ids + dog_ids)

    # Dog species scores must equal solo-pool recompute (cat sounds were not mixed in).
    fps = db.get_all_fingerprints()
    dog_pool = {sid: fps[sid] for sid in dog_ids}
    expected = MeowSimilarity().compute_uniqueness_scores(dog_pool)

    for sid in dog_ids:
        row = db.get_by_id(sid)
        assert row is not None
        assert row["species_uniqueness_score"] == pytest.approx(expected[sid], abs=0.01)

    db.close()


@pytest.mark.unit
def test_single_sound_animal_scores_none(tmp_path: Path) -> None:
    """A sole sound in a sole-animal, sole-species DB gets None for both scores
    because a pool of one has no peers to rank against."""
    db = MeowDB(tmp_path / "meow.db")
    squishy_id = db.get_animals()[0]["id"]

    wav_path = tmp_path / "solo.wav"
    wav_path.write_bytes(_make_sine_wav(500.0))
    solo_id = _add_sound(db, squishy_id, wav_path)

    update_library_uniqueness(db, [solo_id])

    row = db.get_by_id(solo_id)
    assert row is not None
    assert row["animal_uniqueness_score"] is None
    assert row["species_uniqueness_score"] is None

    db.close()


@pytest.mark.unit
def test_force_true_restores_corrupted_fingerprint(tmp_path: Path) -> None:
    """force=True re-extracts fingerprints from source WAV files, overwriting any
    corrupted values previously written to the DB."""
    db = MeowDB(tmp_path / "meow.db")
    squishy_id = db.get_animals()[0]["id"]

    wav_dir = tmp_path / "wavs"
    wav_dir.mkdir()

    sound_ids: list[str] = []
    for i, freq in enumerate([400.0, 600.0, 800.0]):
        p = wav_dir / f"sound_{i}.wav"
        p.write_bytes(_make_sine_wav(freq))
        sound_ids.append(_add_sound(db, squishy_id, p))

    # First pass: extract correct fingerprints.
    update_library_uniqueness(db, sound_ids)
    correct_fp = db.get_all_fingerprints()[sound_ids[0]]

    # Corrupt the first sound's fingerprint.
    db.update_fingerprint(sound_ids[0], [0.0] * 120)
    assert db.get_all_fingerprints()[sound_ids[0]] == [0.0] * 120

    # force=True must re-extract from the WAV file.
    update_library_uniqueness(db, [], force=True)

    restored_fp = db.get_all_fingerprints()[sound_ids[0]]
    assert restored_fp == pytest.approx(correct_fp, abs=1e-9)

    db.close()
