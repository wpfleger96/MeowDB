from __future__ import annotations

import io
import json
import platform
import re
import shutil
import sqlite3
import warnings

from pathlib import Path
from unittest.mock import patch

import bcrypt
import pytest

from PIL import Image

import meowdb

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    from starlette.testclient import TestClient

from meowdb.api.app import create_app

_TEST_PASSWORD = "hunter2"
_TEST_HASH = bcrypt.hashpw(_TEST_PASSWORD.encode(), bcrypt.gensalt()).decode()


@pytest.fixture
def tmp_dirs(tmp_path: Path):
    dirs = {
        "db": tmp_path / "test.sqlite",
        "data": tmp_path,
        "wav": tmp_path / "wav",
        "mp3": tmp_path / "mp3",
        "staging": tmp_path / "staging",
        "static": tmp_path / "static",
    }
    dirs["static"].mkdir()
    (dirs["static"] / "index.html").write_text("<html></html>")
    return dirs


@pytest.fixture
def client(tmp_dirs):
    with (
        patch("meowdb.api.app.DB_PATH", tmp_dirs["db"]),
        patch("meowdb.api.app.DATA_DIR", tmp_dirs["data"]),
        patch("meowdb.api.app.WAV_DIR", tmp_dirs["wav"]),
        patch("meowdb.api.app.MP3_DIR", tmp_dirs["mp3"]),
        patch("meowdb.api.app.STAGING_DIR", tmp_dirs["staging"]),
        patch("meowdb.api.app._STATIC_DIR", tmp_dirs["static"]),
        patch("meowdb.api.app._INDEX_HTML", tmp_dirs["static"] / "index.html"),
        patch("meowdb.api.routers.ingest.STAGING_DIR", tmp_dirs["staging"]),
        patch("meowdb.api.routers.ingest.WAV_DIR", tmp_dirs["wav"]),
        patch("meowdb.api.routers.ingest.MP3_DIR", tmp_dirs["mp3"]),
        patch("meowdb.api.routers.audio.MP3_DIR", tmp_dirs["mp3"]),
        patch("meowdb.api.routers.sounds.WAV_DIR", tmp_dirs["wav"]),
        patch("meowdb.api.routers.sounds.MP3_DIR", tmp_dirs["mp3"]),
        patch("meowdb.api.app.SESSION_SECRET", "test-secret-key"),
        patch("meowdb.api.app.IS_LOCALHOST", True),
        patch("meowdb.api.auth.PASSWORD_HASH", ""),
        patch("meowdb.api.auth.IS_LOCALHOST", True),
        warnings.catch_warnings(),
    ):
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        app = create_app()
        with TestClient(app, raise_server_exceptions=True) as tc:
            yield tc


@pytest.fixture
def seeded_client(tmp_dirs, silent_wav_bytes):
    wav_dir = tmp_dirs["wav"]
    mp3_dir = tmp_dirs["mp3"]
    wav_dir.mkdir(parents=True, exist_ok=True)
    mp3_dir.mkdir(parents=True, exist_ok=True)

    wav_file = wav_dir / "test.wav"
    mp3_file = mp3_dir / "test.mp3"
    wav_file.write_bytes(silent_wav_bytes)
    mp3_file.write_bytes(b"ID3" + b"\x00" * 100)

    with (
        patch("meowdb.api.app.DB_PATH", tmp_dirs["db"]),
        patch("meowdb.api.app.DATA_DIR", tmp_dirs["data"]),
        patch("meowdb.api.app.WAV_DIR", wav_dir),
        patch("meowdb.api.app.MP3_DIR", mp3_dir),
        patch("meowdb.api.app.STAGING_DIR", tmp_dirs["staging"]),
        patch("meowdb.api.app._STATIC_DIR", tmp_dirs["static"]),
        patch("meowdb.api.app._INDEX_HTML", tmp_dirs["static"] / "index.html"),
        patch("meowdb.api.routers.ingest.STAGING_DIR", tmp_dirs["staging"]),
        patch("meowdb.api.routers.ingest.WAV_DIR", wav_dir),
        patch("meowdb.api.routers.ingest.MP3_DIR", mp3_dir),
        patch("meowdb.api.routers.audio.MP3_DIR", mp3_dir),
        patch("meowdb.api.routers.audio.WAV_DIR", wav_dir),
        patch("meowdb.api.routers.sounds.WAV_DIR", wav_dir),
        patch("meowdb.api.routers.sounds.MP3_DIR", mp3_dir),
        patch("meowdb.api.app.SESSION_SECRET", "test-secret-key"),
        patch("meowdb.api.app.IS_LOCALHOST", True),
        patch("meowdb.api.auth.PASSWORD_HASH", ""),
        patch("meowdb.api.auth.IS_LOCALHOST", True),
        warnings.catch_warnings(),
    ):
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        app = create_app()
        with TestClient(app, raise_server_exceptions=True) as tc:
            animal_id = app.state.db.get_animals()[0]["id"]
            app.state.db.add(
                {
                    "timestamp": "2026-01-01T00:00:00",
                    "duration_ms": 1000,
                    "labels": [],
                    "wav_path": str(wav_file),
                    "mp3_path": str(mp3_file),
                    "waveform_data": [0.1, 0.2, 0.3],
                    "peak_dbfs": -10.0,
                    "species_energy_ratio": 2.5,
                    "animal_id": animal_id,
                }
            )
            yield tc


@pytest.mark.integration
def test_list_sounds_empty(client):
    resp = client.get("/api/sounds")
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0
    assert data["limit"] == 50
    assert data["offset"] == 0


@pytest.mark.integration
def test_random_sound_empty_returns_404(client):
    resp = client.get("/api/sounds/random")
    assert resp.status_code == 404


@pytest.mark.integration
def test_random_sound_with_data(seeded_client):
    resp = seeded_client.get("/api/sounds/random")
    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data
    assert data["duration_ms"] == 1000


@pytest.mark.integration
def test_list_sounds_with_data(seeded_client):
    resp = seeded_client.get("/api/sounds")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["duration_ms"] == 1000


@pytest.mark.integration
def test_patch_sound_labels(seeded_client):
    list_resp = seeded_client.get("/api/sounds")
    sound_id = list_resp.json()["items"][0]["id"]

    resp = seeded_client.patch(
        f"/api/sounds/{sound_id}",
        json={"labels": ["cute", "loud"]},
    )
    assert resp.status_code == 200
    assert resp.json()["labels"] == ["cute", "loud"]


@pytest.mark.integration
def test_patch_sound_not_found(client):
    resp = client.patch(
        "/api/sounds/nonexistent-id",
        json={"labels": ["test"]},
    )
    assert resp.status_code == 404


@pytest.mark.integration
def test_delete_sound(seeded_client):
    list_resp = seeded_client.get("/api/sounds")
    sound_id = list_resp.json()["items"][0]["id"]

    resp = seeded_client.delete(f"/api/sounds/{sound_id}")
    assert resp.status_code == 204

    list_resp2 = seeded_client.get("/api/sounds")
    assert list_resp2.json()["total"] == 0


@pytest.mark.integration
def test_delete_sound_not_found(client):
    resp = client.delete("/api/sounds/nonexistent-id")
    assert resp.status_code == 404


@pytest.mark.integration
def test_delete_leaving_single_sound_pool_nulls_score(seeded_client, tmp_dirs):
    """Deleting one of two fingerprinted sounds leaves the remaining with null animal score."""
    db = seeded_client.app.state.db
    wav_file = next(tmp_dirs["wav"].glob("*.wav"))
    mp3_file = next(tmp_dirs["mp3"].glob("*.mp3"))
    animal_id = db.get_animals()[0]["id"]

    # Existing sound from the seeded_client fixture
    sound_id_1 = seeded_client.get("/api/sounds").json()["items"][0]["id"]

    # Add a second sound to the same animal to form a 2-sound pool
    sound_id_2 = db.add(
        {
            "timestamp": "2026-01-02T00:00:00",
            "duration_ms": 750,
            "labels": [],
            "wav_path": str(wav_file),
            "mp3_path": str(mp3_file),
            "waveform_data": [],
            "peak_dbfs": -15.0,
            "species_energy_ratio": 1.5,
            "animal_id": animal_id,
        }
    )

    # Seed fingerprints so update_library_uniqueness has scores to recompute on delete
    fingerprint = [0.1] * 120
    db.update_fingerprint(sound_id_1, fingerprint)
    db.update_fingerprint(sound_id_2, fingerprint)

    # Delete the first sound — the router calls update_library_uniqueness(db, [])
    resp = seeded_client.delete(f"/api/sounds/{sound_id_1}")
    assert resp.status_code == 204

    # Single-sound pool: the remaining sound's animal_uniqueness_score must be null
    items = seeded_client.get("/api/sounds").json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == sound_id_2
    assert items[0]["animal_uniqueness_score"] is None


@pytest.mark.integration
def test_play_sound(seeded_client):
    list_resp = seeded_client.get("/api/sounds")
    initial_play_count = list_resp.json()["items"][0]["play_count"]
    sound_id = list_resp.json()["items"][0]["id"]

    resp = seeded_client.post(f"/api/sounds/{sound_id}/play")
    assert resp.status_code == 204

    list_resp2 = seeded_client.get("/api/sounds")
    new_play_count = list_resp2.json()["items"][0]["play_count"]
    assert new_play_count == initial_play_count + 1


@pytest.mark.integration
def test_play_sound_not_found(client):
    response = client.post("/api/sounds/nonexistent-id/play")
    assert response.status_code == 404


@pytest.mark.integration
def test_get_stats_empty(client):
    resp = client.get("/api/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_sounds"] == 0
    assert data["total_duration_ms"] == 0
    assert data["label_counts"] == {}


@pytest.mark.integration
def test_get_stats_with_data(seeded_client):
    resp = seeded_client.get("/api/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_sounds"] == 1
    assert data["total_duration_ms"] == 1000


@pytest.mark.integration
def test_get_labels_empty(client):
    resp = client.get("/api/labels")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.integration
def test_get_labels_with_data(seeded_client):
    list_resp = seeded_client.get("/api/sounds")
    sound_id = list_resp.json()["items"][0]["id"]
    seeded_client.patch(f"/api/sounds/{sound_id}", json={"labels": ["happy"]})

    resp = seeded_client.get("/api/labels")
    assert resp.status_code == 200
    labels = resp.json()
    assert len(labels) == 1
    assert labels[0]["label"] == "happy"
    assert labels[0]["count"] == 1


@pytest.mark.integration
def test_spa_catch_all(client):
    resp = client.get("/some/unknown/path")
    assert resp.status_code == 200
    assert "html" in resp.headers.get("content-type", "")


@pytest.mark.integration
def test_audio_stream_not_found(client):
    resp = client.get("/api/audio/nonexistent-id")
    assert resp.status_code == 404
    assert "cache-control" not in resp.headers


@pytest.mark.integration
def test_audio_stream_with_data(seeded_client):
    list_resp = seeded_client.get("/api/sounds")
    sound_id = list_resp.json()["items"][0]["id"]

    resp = seeded_client.get(f"/api/audio/{sound_id}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/mpeg"


@pytest.mark.integration
def test_audio_wav_stream_with_data(seeded_client):
    sound_id = seeded_client.get("/api/sounds").json()["items"][0]["id"]

    resp = seeded_client.get(f"/api/audio/{sound_id}/wav")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/wav"


@pytest.mark.integration
def test_audio_mp3_cache_control_is_immutable(seeded_client):
    sound_id = seeded_client.get("/api/sounds").json()["items"][0]["id"]

    resp = seeded_client.get(f"/api/audio/{sound_id}")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "public, max-age=31536000, immutable"


@pytest.mark.integration
def test_audio_wav_cache_control_is_immutable(seeded_client):
    sound_id = seeded_client.get("/api/sounds").json()["items"][0]["id"]

    resp = seeded_client.get(f"/api/audio/{sound_id}/wav")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "public, max-age=31536000, immutable"


@pytest.mark.integration
def test_feedback_upvote(seeded_client):
    sound_id = seeded_client.get("/api/sounds").json()["items"][0]["id"]
    resp = seeded_client.post(f"/api/sounds/{sound_id}/feedback", json={"vote": "up"})
    assert resp.status_code == 204
    data = seeded_client.get("/api/sounds").json()["items"][0]
    assert data["upvote_count"] == 1
    assert data["downvote_count"] == 0


@pytest.mark.integration
def test_feedback_downvote(seeded_client):
    sound_id = seeded_client.get("/api/sounds").json()["items"][0]["id"]
    resp = seeded_client.post(f"/api/sounds/{sound_id}/feedback", json={"vote": "down"})
    assert resp.status_code == 204
    data = seeded_client.get("/api/sounds").json()["items"][0]
    assert data["downvote_count"] == 1
    assert data["upvote_count"] == 0


@pytest.mark.integration
def test_feedback_invalid_vote(seeded_client):
    sound_id = seeded_client.get("/api/sounds").json()["items"][0]["id"]
    resp = seeded_client.post(f"/api/sounds/{sound_id}/feedback", json={"vote": "sideways"})
    assert resp.status_code == 422


@pytest.mark.integration
def test_feedback_not_found(client):
    resp = client.post("/api/sounds/nonexistent-id/feedback", json={"vote": "up"})
    assert resp.status_code == 404


@pytest.mark.integration
def test_feedback_switch_vote(seeded_client):
    sound_id = seeded_client.get("/api/sounds").json()["items"][0]["id"]
    seeded_client.post(f"/api/sounds/{sound_id}/feedback", json={"vote": "up"})
    resp = seeded_client.post(
        f"/api/sounds/{sound_id}/feedback", json={"vote": "down", "previous": "up"}
    )
    assert resp.status_code == 204
    data = seeded_client.get("/api/sounds").json()["items"][0]
    assert data["upvote_count"] == 0
    assert data["downvote_count"] == 1


@pytest.mark.integration
def test_list_sounds_sort_most_downvoted(seeded_client, tmp_dirs):
    wav_file = next(tmp_dirs["wav"].glob("*.wav"))
    mp3_file = next(tmp_dirs["mp3"].glob("*.mp3"))
    animal_id = seeded_client.app.state.db.get_animals()[0]["id"]
    sound_id_1 = seeded_client.get("/api/sounds").json()["items"][0]["id"]
    sound_id_2 = seeded_client.app.state.db.add(
        {
            "timestamp": "2026-01-02T00:00:00",
            "duration_ms": 500,
            "labels": [],
            "wav_path": str(wav_file),
            "mp3_path": str(mp3_file),
            "waveform_data": [],
            "peak_dbfs": -10.0,
            "species_energy_ratio": 2.5,
            "animal_id": animal_id,
        }
    )
    seeded_client.post(f"/api/sounds/{sound_id_1}/feedback", json={"vote": "down"})
    seeded_client.post(f"/api/sounds/{sound_id_2}/feedback", json={"vote": "down"})
    seeded_client.post(f"/api/sounds/{sound_id_2}/feedback", json={"vote": "down"})

    resp = seeded_client.get("/api/sounds?sort=most_downvoted")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert items[0]["id"] == sound_id_2
    assert items[0]["downvote_count"] == 2


@pytest.mark.integration
def test_list_sounds_sort_most_upvoted(seeded_client, tmp_dirs):
    wav_file = next(tmp_dirs["wav"].glob("*.wav"))
    mp3_file = next(tmp_dirs["mp3"].glob("*.mp3"))
    animal_id = seeded_client.app.state.db.get_animals()[0]["id"]
    sound_id_1 = seeded_client.get("/api/sounds").json()["items"][0]["id"]
    sound_id_2 = seeded_client.app.state.db.add(
        {
            "timestamp": "2026-01-02T00:00:00",
            "duration_ms": 500,
            "labels": [],
            "wav_path": str(wav_file),
            "mp3_path": str(mp3_file),
            "waveform_data": [],
            "peak_dbfs": -10.0,
            "species_energy_ratio": 2.5,
            "animal_id": animal_id,
        }
    )
    seeded_client.post(f"/api/sounds/{sound_id_1}/feedback", json={"vote": "up"})
    seeded_client.post(f"/api/sounds/{sound_id_1}/feedback", json={"vote": "up"})
    seeded_client.post(f"/api/sounds/{sound_id_2}/feedback", json={"vote": "up"})

    resp = seeded_client.get("/api/sounds?sort=most_upvoted")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert items[0]["id"] == sound_id_1
    assert items[0]["upvote_count"] == 2


@pytest.mark.integration
def test_ingest_job_not_found(client):
    resp = client.get("/api/ingest/nonexistent-job-id")
    assert resp.status_code == 404


@pytest.mark.integration
def test_ingest_delete_not_found(client):
    resp = client.delete("/api/ingest/nonexistent-job-id")
    assert resp.status_code == 404


@pytest.mark.integration
def test_ingest_flow_post_and_poll(tmp_dirs, silent_wav_bytes):
    with (
        patch("meowdb.api.app.DB_PATH", tmp_dirs["db"]),
        patch("meowdb.api.app.DATA_DIR", tmp_dirs["data"]),
        patch("meowdb.api.app.WAV_DIR", tmp_dirs["wav"]),
        patch("meowdb.api.app.MP3_DIR", tmp_dirs["mp3"]),
        patch("meowdb.api.app.STAGING_DIR", tmp_dirs["staging"]),
        patch("meowdb.api.app._STATIC_DIR", tmp_dirs["static"]),
        patch("meowdb.api.app._INDEX_HTML", tmp_dirs["static"] / "index.html"),
        patch("meowdb.api.routers.ingest.STAGING_DIR", tmp_dirs["staging"]),
        patch("meowdb.api.routers.ingest.WAV_DIR", tmp_dirs["wav"]),
        patch("meowdb.api.routers.ingest.MP3_DIR", tmp_dirs["mp3"]),
        patch("meowdb.api.routers.audio.MP3_DIR", tmp_dirs["mp3"]),
        patch("meowdb.api.routers.sounds.WAV_DIR", tmp_dirs["wav"]),
        patch("meowdb.api.routers.sounds.MP3_DIR", tmp_dirs["mp3"]),
        patch("meowdb.api.app.SESSION_SECRET", "test-secret-key"),
        patch("meowdb.api.app.IS_LOCALHOST", True),
        patch("meowdb.api.auth.PASSWORD_HASH", ""),
        patch("meowdb.api.auth.IS_LOCALHOST", True),
        warnings.catch_warnings(),
    ):
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        app = create_app()
        with TestClient(app, raise_server_exceptions=True) as tc:
            animal_id = app.state.db.get_animals()[0]["id"]
            wav_bytes = silent_wav_bytes
            resp = tc.post(
                "/api/ingest",
                files={"file": ("test.wav", wav_bytes, "audio/wav")},
                data={"animal_id": animal_id},
            )
            assert resp.status_code == 202
            data = resp.json()
            assert data["status"] == "uploaded"
            job_id = data["job_id"]
            assert job_id

            assert data["animal_id"] == animal_id

            poll_resp = tc.get(f"/api/ingest/{job_id}")
            assert poll_resp.status_code == 200
            assert poll_resp.json()["job_id"] == job_id


@pytest.mark.integration
def test_ingest_commit(tmp_dirs, silent_wav_bytes):
    wav_dir = tmp_dirs["wav"]
    mp3_dir = tmp_dirs["mp3"]
    staging_dir = tmp_dirs["staging"]
    wav_dir.mkdir(parents=True, exist_ok=True)
    mp3_dir.mkdir(parents=True, exist_ok=True)
    staging_dir.mkdir(parents=True, exist_ok=True)

    with (
        patch("meowdb.api.app.DB_PATH", tmp_dirs["db"]),
        patch("meowdb.api.app.DATA_DIR", tmp_dirs["data"]),
        patch("meowdb.api.app.WAV_DIR", wav_dir),
        patch("meowdb.api.app.MP3_DIR", mp3_dir),
        patch("meowdb.api.app.STAGING_DIR", staging_dir),
        patch("meowdb.api.app._STATIC_DIR", tmp_dirs["static"]),
        patch("meowdb.api.app._INDEX_HTML", tmp_dirs["static"] / "index.html"),
        patch("meowdb.api.routers.ingest.STAGING_DIR", staging_dir),
        patch("meowdb.api.routers.ingest.WAV_DIR", wav_dir),
        patch("meowdb.api.routers.ingest.MP3_DIR", mp3_dir),
        patch("meowdb.api.routers.audio.MP3_DIR", mp3_dir),
        patch("meowdb.api.routers.sounds.WAV_DIR", wav_dir),
        patch("meowdb.api.routers.sounds.MP3_DIR", mp3_dir),
        patch("meowdb.api.app.SESSION_SECRET", "test-secret-key"),
        patch("meowdb.api.app.IS_LOCALHOST", True),
        patch("meowdb.api.auth.PASSWORD_HASH", ""),
        patch("meowdb.api.auth.IS_LOCALHOST", True),
        warnings.catch_warnings(),
    ):
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        app = create_app()
        with TestClient(app, raise_server_exceptions=True) as tc:
            db = app.state.db
            animal_id = db.get_animals()[0]["id"]
            job_id = db.create_job("test.wav", animal_id)
            job_staging = staging_dir / job_id
            job_staging.mkdir(parents=True)
            seg_wav = job_staging / "seg_000.wav"
            seg_mp3 = job_staging / "seg_000.mp3"
            seg_wav.write_bytes(silent_wav_bytes)
            seg_mp3.write_bytes(b"\xff\xfb" + b"\x00" * 100)

            db.add_segments(
                job_id,
                [
                    {
                        "index": 0,
                        "duration_ms": 500,
                        "wav_path": str(seg_wav),
                        "waveform_data": [0.1, 0.2],
                        "peak_dbfs": -12.0,
                        "species_energy_ratio": 2.0,
                    }
                ],
            )
            db.update_job_status(job_id, "ready")

            poll_resp = tc.get(f"/api/ingest/{job_id}")
            assert poll_resp.status_code == 200
            seg_id = poll_resp.json()["segments"][0]["id"]

            commit_resp = tc.post(
                f"/api/ingest/{job_id}/commit",
                json={"accepted_ids": [seg_id], "rejected_ids": []},
            )
            assert commit_resp.status_code == 200
            data = commit_resp.json()
            assert len(data["sound_ids"]) == 1
            assert data["rejected_count"] == 0


@pytest.mark.integration
def test_stream_source_audio(client, silent_wav_bytes):
    animal_id = client.app.state.db.get_animals()[0]["id"]
    wav_bytes = silent_wav_bytes
    resp = client.post(
        "/api/ingest",
        files={"file": ("test.wav", io.BytesIO(wav_bytes), "audio/wav")},
        data={"animal_id": animal_id},
    )
    job_id = resp.json()["job_id"]

    resp = client.get(f"/api/ingest/{job_id}/source")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("audio/")
    assert len(resp.content) > 0


@pytest.mark.integration
def test_ingest_source_traversal_job_id_denied(client):
    with patch.object(
        client.app.state.db, "get_job", return_value={"id": "..", "status": "uploaded"}
    ):
        resp = client.get("/api/ingest/%2e%2e/source")
    assert resp.status_code == 403


@pytest.mark.integration
def test_detect_regions(client, silent_wav_bytes):
    animal_id = client.app.state.db.get_animals()[0]["id"]
    wav_bytes = silent_wav_bytes
    resp = client.post(
        "/api/ingest",
        files={"file": ("test.wav", io.BytesIO(wav_bytes), "audio/wav")},
        data={"animal_id": animal_id},
    )
    job_id = resp.json()["job_id"]

    resp = client.post(f"/api/ingest/{job_id}/detect")
    assert resp.status_code == 200
    data = resp.json()
    assert "regions" in data
    # Silent audio may return 0 regions — that's fine
    assert isinstance(data["regions"], list)


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_clip_and_commit(client, silent_wav_bytes):
    animal_id = client.app.state.db.get_animals()[0]["id"]
    wav_bytes = silent_wav_bytes
    resp = client.post(
        "/api/ingest",
        files={"file": ("test.wav", io.BytesIO(wav_bytes), "audio/wav")},
        data={"animal_id": animal_id},
    )
    job_id = resp.json()["job_id"]

    # Clip a region from the uploaded file (default audio is 1 second)
    resp = client.post(
        f"/api/ingest/{job_id}/clip",
        json={"regions": [{"start_ms": 0, "end_ms": 500}]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["sound_ids"]) == 1
    assert data["rejected_count"] == 0


@pytest.mark.integration
def test_clip_empty_regions_rejected(client, silent_wav_bytes):
    animal_id = client.app.state.db.get_animals()[0]["id"]
    wav_bytes = silent_wav_bytes
    resp = client.post(
        "/api/ingest",
        files={"file": ("test.wav", io.BytesIO(wav_bytes), "audio/wav")},
        data={"animal_id": animal_id},
    )
    job_id = resp.json()["job_id"]

    resp = client.post(
        f"/api/ingest/{job_id}/clip",
        json={"regions": []},
    )
    assert resp.status_code == 400


@pytest.mark.integration
def test_clip_inverted_region_rejected(client, silent_wav_bytes):
    animal_id = client.app.state.db.get_animals()[0]["id"]
    wav_bytes = silent_wav_bytes
    resp = client.post(
        "/api/ingest",
        files={"file": ("test.wav", io.BytesIO(wav_bytes), "audio/wav")},
        data={"animal_id": animal_id},
    )
    job_id = resp.json()["job_id"]

    resp = client.post(
        f"/api/ingest/{job_id}/clip",
        json={"regions": [{"start_ms": 500, "end_ms": 100}]},
    )
    assert resp.status_code == 422


@pytest.mark.integration
def test_clip_negative_region_rejected(client, silent_wav_bytes):
    animal_id = client.app.state.db.get_animals()[0]["id"]
    wav_bytes = silent_wav_bytes
    resp = client.post(
        "/api/ingest",
        files={"file": ("test.wav", io.BytesIO(wav_bytes), "audio/wav")},
        data={"animal_id": animal_id},
    )
    job_id = resp.json()["job_id"]

    resp = client.post(
        f"/api/ingest/{job_id}/clip",
        json={"regions": [{"start_ms": -100, "end_ms": 500}]},
    )
    assert resp.status_code == 422


@pytest.mark.integration
def test_health_returns_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.integration
def test_health_returns_503_when_db_unreachable(client):
    with patch("meowdb.db.MeowDB.ping", return_value=False):
        resp = client.get("/health")
    assert resp.status_code == 503
    assert resp.json() == {"status": "error"}


@pytest.mark.integration
def test_about_returns_expected_fields(client):
    resp = client.get("/api/about")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {
        "version",
        "git_sha",
        "build_time",
        "uptime_seconds",
        "auth_mode",
        "python_version",
        "sqlite_version",
    }
    assert body["version"] == meowdb.__version__
    assert isinstance(body["uptime_seconds"], float)
    assert body["uptime_seconds"] >= 0
    assert body["python_version"] == platform.python_version()
    assert body["sqlite_version"] == sqlite3.sqlite_version


@pytest.mark.integration
def test_about_reads_build_metadata_from_env(client, monkeypatch):
    monkeypatch.setenv("MEOWDB_GIT_SHA", "abc1234")
    monkeypatch.setenv("MEOWDB_BUILD_TIME", "2026-08-08T00:00:00Z")
    body = client.get("/api/about").json()
    assert body["git_sha"] == "abc1234"
    assert body["build_time"] == "2026-08-08T00:00:00Z"


@pytest.mark.integration
def test_about_build_metadata_defaults_when_env_unset(client, monkeypatch):
    monkeypatch.delenv("MEOWDB_GIT_SHA", raising=False)
    monkeypatch.delenv("MEOWDB_BUILD_TIME", raising=False)
    body = client.get("/api/about").json()
    assert body["git_sha"] == "dev"
    assert body["build_time"] == ""


# The about router reads config at request time, so these patch its import site
# per-test rather than in the client fixture (which is at the nested-block limit).
@pytest.mark.integration
def test_about_auth_mode_reflects_password_hash(client):
    with (
        patch("meowdb.api.routers.about.PASSWORD_HASH", ""),
        patch("meowdb.api.routers.about.IS_LOCALHOST", True),
    ):
        assert client.get("/api/about").json()["auth_mode"] == "Open (local)"
    with (
        patch("meowdb.api.routers.about.PASSWORD_HASH", _TEST_HASH),
        patch("meowdb.api.routers.about.IS_LOCALHOST", True),
    ):
        assert client.get("/api/about").json()["auth_mode"] == "Password-protected"


@pytest.mark.integration
def test_about_auth_mode_is_protected_when_not_localhost(client):
    with (
        patch("meowdb.api.routers.about.PASSWORD_HASH", ""),
        patch("meowdb.api.routers.about.IS_LOCALHOST", False),
    ):
        assert client.get("/api/about").json()["auth_mode"] == "Password-protected"


@pytest.mark.integration
def test_about_absent_from_openapi_schema(client):
    schema = client.get("/openapi.json").json()
    assert "/api/about" not in schema["paths"]


@pytest.fixture
def auth_client(tmp_dirs):
    with (
        patch("meowdb.api.app.DB_PATH", tmp_dirs["db"]),
        patch("meowdb.api.app.DATA_DIR", tmp_dirs["data"]),
        patch("meowdb.api.app.WAV_DIR", tmp_dirs["wav"]),
        patch("meowdb.api.app.MP3_DIR", tmp_dirs["mp3"]),
        patch("meowdb.api.app.STAGING_DIR", tmp_dirs["staging"]),
        patch("meowdb.api.app._STATIC_DIR", tmp_dirs["static"]),
        patch("meowdb.api.app._INDEX_HTML", tmp_dirs["static"] / "index.html"),
        patch("meowdb.api.routers.ingest.STAGING_DIR", tmp_dirs["staging"]),
        patch("meowdb.api.routers.ingest.WAV_DIR", tmp_dirs["wav"]),
        patch("meowdb.api.routers.ingest.MP3_DIR", tmp_dirs["mp3"]),
        patch("meowdb.api.routers.audio.MP3_DIR", tmp_dirs["mp3"]),
        patch("meowdb.api.routers.sounds.WAV_DIR", tmp_dirs["wav"]),
        patch("meowdb.api.routers.sounds.MP3_DIR", tmp_dirs["mp3"]),
        patch("meowdb.api.app.SESSION_SECRET", "test-secret-key"),
        patch("meowdb.api.app.IS_LOCALHOST", True),
        patch("meowdb.api.auth.IS_LOCALHOST", False),
        patch("meowdb.api.auth.PASSWORD_HASH", _TEST_HASH),
        warnings.catch_warnings(),
    ):
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        app = create_app()
        with TestClient(app, raise_server_exceptions=True) as tc:
            yield tc


@pytest.mark.integration
def test_auth_status_unauthenticated(auth_client):
    resp = auth_client.get("/api/auth/status")
    assert resp.status_code == 200
    assert resp.json() == {"authenticated": False, "auth_required": True}


@pytest.mark.integration
def test_login_wrong_password(auth_client):
    from meowdb.api import auth as auth_module

    resp = auth_client.post("/api/auth/login", json={"password": "wrongpassword"})
    assert resp.status_code == 401
    auth_module._failed_attempts.clear()


@pytest.mark.integration
def test_login_no_password_configured(tmp_dirs):
    with (
        patch("meowdb.api.app.DB_PATH", tmp_dirs["db"]),
        patch("meowdb.api.app.DATA_DIR", tmp_dirs["data"]),
        patch("meowdb.api.app.WAV_DIR", tmp_dirs["wav"]),
        patch("meowdb.api.app.MP3_DIR", tmp_dirs["mp3"]),
        patch("meowdb.api.app.STAGING_DIR", tmp_dirs["staging"]),
        patch("meowdb.api.app._STATIC_DIR", tmp_dirs["static"]),
        patch("meowdb.api.app._INDEX_HTML", tmp_dirs["static"] / "index.html"),
        patch("meowdb.api.routers.ingest.STAGING_DIR", tmp_dirs["staging"]),
        patch("meowdb.api.routers.ingest.WAV_DIR", tmp_dirs["wav"]),
        patch("meowdb.api.routers.ingest.MP3_DIR", tmp_dirs["mp3"]),
        patch("meowdb.api.routers.audio.MP3_DIR", tmp_dirs["mp3"]),
        patch("meowdb.api.routers.sounds.WAV_DIR", tmp_dirs["wav"]),
        patch("meowdb.api.routers.sounds.MP3_DIR", tmp_dirs["mp3"]),
        patch("meowdb.api.app.SESSION_SECRET", "test-secret-key"),
        patch("meowdb.api.app.IS_LOCALHOST", True),
        patch("meowdb.api.auth.PASSWORD_HASH", ""),
        warnings.catch_warnings(),
    ):
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        app = create_app()
        with TestClient(app, raise_server_exceptions=True) as tc:
            resp = tc.post("/api/auth/login", json={"password": "anything"})
            assert resp.status_code == 503


@pytest.mark.integration
def test_login_success_and_auth_status(auth_client):
    resp = auth_client.post("/api/auth/login", json={"password": _TEST_PASSWORD})
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}

    status_resp = auth_client.get("/api/auth/status")
    assert status_resp.json() == {"authenticated": True, "auth_required": True}


@pytest.mark.integration
def test_delete_sound_requires_auth(auth_client):
    resp = auth_client.delete("/api/sounds/nonexistent-id")
    assert resp.status_code == 401


@pytest.mark.integration
def test_public_endpoint_without_auth(auth_client):
    resp = auth_client.get("/api/sounds")
    assert resp.status_code == 200


@pytest.mark.integration
def test_logout(auth_client):
    auth_client.post("/api/auth/login", json={"password": _TEST_PASSWORD})

    resp = auth_client.post("/api/auth/logout")
    assert resp.status_code == 200

    resp = auth_client.delete("/api/sounds/nonexistent-id")
    assert resp.status_code == 401


@pytest.mark.integration
def test_brute_force_lockout(auth_client):
    from meowdb.api import auth as auth_module

    auth_module._failed_attempts.clear()

    for _ in range(5):
        auth_client.post("/api/auth/login", json={"password": "wrong"})

    resp = auth_client.post("/api/auth/login", json={"password": "wrong"})
    assert resp.status_code == 429

    auth_module._failed_attempts.clear()


@pytest.mark.integration
def test_patch_sound_requires_auth(auth_client):
    resp = auth_client.patch("/api/sounds/nonexistent-id", json={"labels": ["test"]})
    assert resp.status_code == 401


@pytest.mark.integration
def test_login_grants_access_to_protected_endpoint(auth_client):
    auth_client.post("/api/auth/login", json={"password": _TEST_PASSWORD})
    resp = auth_client.patch("/api/sounds/nonexistent-id", json={"labels": ["test"]})
    assert resp.status_code == 404  # 404 not found, not 401 unauthorized


@pytest.mark.integration
def test_ingest_requires_auth(auth_client, silent_wav_bytes):
    wav_bytes = silent_wav_bytes
    resp = auth_client.post(
        "/api/ingest",
        files={"file": ("test.wav", io.BytesIO(wav_bytes), "audio/wav")},
    )
    assert resp.status_code == 401


@pytest.mark.integration
def test_auth_bypass_requires_localhost(tmp_dirs):
    """Empty PASSWORD_HASH with a public HOST still enforces auth."""
    with (
        patch("meowdb.api.app.DB_PATH", tmp_dirs["db"]),
        patch("meowdb.api.app.DATA_DIR", tmp_dirs["data"]),
        patch("meowdb.api.app.WAV_DIR", tmp_dirs["wav"]),
        patch("meowdb.api.app.MP3_DIR", tmp_dirs["mp3"]),
        patch("meowdb.api.app.STAGING_DIR", tmp_dirs["staging"]),
        patch("meowdb.api.app._STATIC_DIR", tmp_dirs["static"]),
        patch("meowdb.api.app._INDEX_HTML", tmp_dirs["static"] / "index.html"),
        patch("meowdb.api.routers.ingest.STAGING_DIR", tmp_dirs["staging"]),
        patch("meowdb.api.routers.ingest.WAV_DIR", tmp_dirs["wav"]),
        patch("meowdb.api.routers.ingest.MP3_DIR", tmp_dirs["mp3"]),
        patch("meowdb.api.routers.audio.MP3_DIR", tmp_dirs["mp3"]),
        patch("meowdb.api.routers.sounds.WAV_DIR", tmp_dirs["wav"]),
        patch("meowdb.api.routers.sounds.MP3_DIR", tmp_dirs["mp3"]),
        patch("meowdb.api.app.SESSION_SECRET", "test-secret-key"),
        patch("meowdb.api.app.IS_LOCALHOST", True),
        patch("meowdb.api.auth.PASSWORD_HASH", ""),
        patch("meowdb.api.auth.IS_LOCALHOST", False),  # public host, bypass should NOT trigger
        warnings.catch_warnings(),
    ):
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        app = create_app()
        with TestClient(app, raise_server_exceptions=True) as tc:
            resp = tc.delete("/api/sounds/nonexistent-id")
            assert resp.status_code == 401


@pytest.mark.integration
def test_brute_force_lockout_expires(auth_client):
    from unittest.mock import patch as mock_patch

    from meowdb.api import auth as auth_module

    auth_module._failed_attempts.clear()

    # Trigger lockout
    for _ in range(5):
        auth_client.post("/api/auth/login", json={"password": "wrong"})

    # Verify locked
    resp = auth_client.post("/api/auth/login", json={"password": "wrong"})
    assert resp.status_code == 429

    # Simulate time advancing past lockout expiry (base is 30s, we jump 31s)
    import time as time_module

    real_time = time_module.time()
    with mock_patch("meowdb.api.auth.time") as mock_time:
        mock_time.time.return_value = real_time + 31
        resp = auth_client.post("/api/auth/login", json={"password": "wrong"})
        # After expiry, attempt counter resets and we get 401 (not 429)
        assert resp.status_code == 401

    auth_module._failed_attempts.clear()


@pytest.mark.integration
def test_auth_status_no_password_localhost(client):
    resp = client.get("/api/auth/status")
    assert resp.status_code == 200
    assert resp.json() == {"authenticated": False, "auth_required": False}


@pytest.mark.integration
def test_no_password_localhost_allows_writes(client):
    resp = client.delete("/api/sounds/nonexistent-id")
    assert resp.status_code == 404  # not 401 — write endpoint accessible without auth


# ---------------------------------------------------------------------------
# Bootstrap injection tests
# ---------------------------------------------------------------------------

_PLACEHOLDER_HTML = (
    "<html><head>"
    "<script>window.__BOOTSTRAP__ = {{BOOTSTRAP_JSON}};</script>"
    "</head><body><!-- {{PHOTO_PRELOAD}} --></body></html>"
)

_BOOTSTRAP_RE = re.compile(r"window\.__BOOTSTRAP__ = (.+?);</script>")


def _bootstrap_from(body: str) -> dict:
    match = _BOOTSTRAP_RE.search(body)
    assert match, "bootstrap script not found in served HTML"
    payload: dict = json.loads(match.group(1))
    return payload


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "black").save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.integration
def test_index_bootstrap_injected(seeded_client, tmp_dirs):
    (tmp_dirs["static"] / "index.html").write_text(_PLACEHOLDER_HTML)

    auth_payload = seeded_client.get("/api/auth/status").json()
    resp = seeded_client.get("/")
    body = resp.text

    assert "window.__BOOTSTRAP__ = {" in body
    payload = _bootstrap_from(body)
    assert isinstance(payload["sound_count"], int)
    assert payload["auth"] == auth_payload
    assert "{{BOOTSTRAP_JSON}}" not in body
    assert "{{PHOTO_PRELOAD}}" not in body


@pytest.mark.integration
def test_index_html_source_contains_placeholders():
    # The fixtures serve a synthetic index.html, so pin the real file here:
    # without its placeholders the server's replace is a silent no-op and the
    # frontend quietly falls back to API calls — no other test would fail.
    html = (Path(__file__).parents[2] / "src" / "meowdb" / "static" / "index.html").read_text()
    assert "window.__BOOTSTRAP__ = {{BOOTSTRAP_JSON}};" in html
    assert "<!-- {{PHOTO_PRELOAD}} -->" in html


@pytest.mark.integration
def test_index_bootstrap_no_photos(client, tmp_dirs):
    (tmp_dirs["static"] / "index.html").write_text(_PLACEHOLDER_HTML)

    resp = client.get("/")
    body = resp.text
    payload = _bootstrap_from(body)

    assert payload["photo"] is None
    assert 'rel="preload"' not in body


@pytest.mark.integration
def test_index_photo_preload_only_on_root(client, tmp_dirs):
    (tmp_dirs["static"] / "index.html").write_text(_PLACEHOLDER_HTML)
    photos_dir = tmp_dirs["data"] / "photos"
    photos_dir.mkdir(parents=True, exist_ok=True)

    animal_id = client.app.state.db.get_animals()[0]["id"]
    with (
        patch("meowdb.api.routers.animals.PHOTOS_DIR", photos_dir),
        patch("meowdb.api.routers.photos.PHOTOS_DIR", photos_dir),
    ):
        upload_resp = client.post(
            f"/api/animals/{animal_id}/photos",
            files={"file": ("cat.png", _png_bytes(), "image/png")},
        )
    assert upload_resp.status_code == 201

    root_resp = client.get("/")
    root_body = root_resp.text
    root_payload = _bootstrap_from(root_body)

    assert root_payload["photo"] is not None
    assert '<link rel="preload" as="image"' in root_body
    image_url = root_payload["photo"]["image_url"]
    assert f'href="{image_url}"' in root_body

    stats_resp = client.get("/stats")
    stats_body = stats_resp.text
    stats_payload = _bootstrap_from(stats_body)

    assert '<link rel="preload"' not in stats_body
    assert stats_payload["photo"] is not None


# ---------------------------------------------------------------------------
# Animals CRUD tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_list_animals_includes_squishy(client):
    resp = client.get("/api/animals")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) >= 1
    squishy = next((a for a in data["items"] if a["name"] == "Squishy"), None)
    assert squishy is not None
    assert squishy["species"] == "cat"
    assert "sound_count" in squishy
    assert "photo_count" in squishy


@pytest.mark.integration
def test_create_animal_requires_auth(auth_client):
    resp = auth_client.post("/api/animals", json={"name": "Rex", "species": "dog"})
    assert resp.status_code == 401


@pytest.mark.integration
def test_create_animal(client):
    resp = client.post("/api/animals", json={"name": "Rex", "species": "dog"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Rex"
    assert data["species"] == "dog"
    assert data["sound_count"] == 0
    assert data["photo_count"] == 0
    assert "id" in data


@pytest.mark.integration
def test_created_animal_appears_in_list(client):
    client.post("/api/animals", json={"name": "Buddy", "species": "dog"})
    resp = client.get("/api/animals")
    names = [a["name"] for a in resp.json()["items"]]
    assert "Buddy" in names


@pytest.mark.integration
def test_delete_animal_cascades_sounds(seeded_client):
    animal_id = seeded_client.app.state.db.get_animals()[0]["id"]
    # Squishy already has 1 sound from the seeded_client fixture
    assert seeded_client.get("/api/sounds").json()["total"] == 1

    resp = seeded_client.delete(f"/api/animals/{animal_id}")
    assert resp.status_code == 204

    # Animal is gone
    assert seeded_client.get("/api/animals").json()["items"] == []
    # Sound cascaded away
    assert seeded_client.get("/api/sounds").json()["total"] == 0


@pytest.mark.integration
def test_delete_animal_not_found(client):
    resp = client.delete("/api/animals/nonexistent-id")
    assert resp.status_code == 404


@pytest.mark.integration
def test_delete_animal_returns_404_after(client):
    resp = client.post("/api/animals", json={"name": "Temp", "species": "cat"})
    animal_id = resp.json()["id"]

    client.delete(f"/api/animals/{animal_id}")
    resp2 = client.delete(f"/api/animals/{animal_id}")
    assert resp2.status_code == 404


# ---------------------------------------------------------------------------
# /sounds/random — photo embedding and cross-animal isolation
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_random_sound_photo_null_when_no_photos(seeded_client):
    # Squishy has a sound but no photos — photo field must be null
    resp = seeded_client.get("/api/sounds/random")
    assert resp.status_code == 200
    data = resp.json()
    assert data["photo"] is None


@pytest.mark.integration
def test_random_sound_embeds_photo_from_own_animal(seeded_client, tmp_dirs):
    photos_dir = tmp_dirs["data"] / "photos"
    photos_dir.mkdir(parents=True, exist_ok=True)
    animal_id = seeded_client.app.state.db.get_animals()[0]["id"]

    with (
        patch("meowdb.api.routers.animals.PHOTOS_DIR", photos_dir),
        patch("meowdb.api.routers.photos.PHOTOS_DIR", photos_dir),
    ):
        upload_resp = seeded_client.post(
            f"/api/animals/{animal_id}/photos",
            files={"file": ("cat.png", _png_bytes(), "image/png")},
        )
    assert upload_resp.status_code == 201

    resp = seeded_client.get("/api/sounds/random")
    assert resp.status_code == 200
    data = resp.json()
    assert data["photo"] is not None
    assert data["photo"]["animal_id"] == animal_id


@pytest.mark.integration
def test_random_sound_no_cross_animal_photo_fallback(seeded_client, tmp_dirs):
    # Squishy has a sound (seeded) but no photos.
    # Rex has a photo but no sounds.
    # Random sound belongs to Squishy → photo must be null, not Rex's photo.
    photos_dir = tmp_dirs["data"] / "photos"
    photos_dir.mkdir(parents=True, exist_ok=True)

    db = seeded_client.app.state.db
    rex_id = db.add_animal("Rex", "dog")

    with (
        patch("meowdb.api.routers.animals.PHOTOS_DIR", photos_dir),
        patch("meowdb.api.routers.photos.PHOTOS_DIR", photos_dir),
    ):
        seeded_client.post(
            f"/api/animals/{rex_id}/photos",
            files={"file": ("dog.png", _png_bytes(), "image/png")},
        )

    resp = seeded_client.get("/api/sounds/random")
    assert resp.status_code == 200
    data = resp.json()
    # Photo is null — no cross-animal fallback to Rex's photo
    assert data["photo"] is None


# ---------------------------------------------------------------------------
# animal_id filter on GET /sounds
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_list_sounds_filter_by_animal_id(seeded_client, tmp_dirs):
    db = seeded_client.app.state.db
    squishy_id = db.get_animals()[0]["id"]
    wav_file = next(tmp_dirs["wav"].glob("*.wav"))
    mp3_file = next(tmp_dirs["mp3"].glob("*.mp3"))

    # Add a second animal with its own sound
    rex_id = db.add_animal("Rex", "dog")
    db.add(
        {
            "timestamp": "2026-01-02T00:00:00",
            "duration_ms": 500,
            "labels": [],
            "wav_path": str(wav_file),
            "mp3_path": str(mp3_file),
            "waveform_data": [],
            "peak_dbfs": -10.0,
            "species_energy_ratio": 2.5,
            "animal_id": rex_id,
        }
    )

    squishy_resp = seeded_client.get(f"/api/sounds?animal_id={squishy_id}")
    assert squishy_resp.status_code == 200
    squishy_data = squishy_resp.json()
    assert squishy_data["total"] == 1
    assert squishy_data["items"][0]["animal_id"] == squishy_id

    rex_resp = seeded_client.get(f"/api/sounds?animal_id={rex_id}")
    assert rex_resp.json()["total"] == 1
    assert rex_resp.json()["items"][0]["animal_id"] == rex_id


# ---------------------------------------------------------------------------
# Ingest animal_id validation
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_ingest_requires_animal_id_field(client, silent_wav_bytes):
    # Missing animal_id form field → 422 Unprocessable Entity
    resp = client.post(
        "/api/ingest",
        files={"file": ("test.wav", io.BytesIO(silent_wav_bytes), "audio/wav")},
    )
    assert resp.status_code == 422


@pytest.mark.integration
def test_ingest_unknown_animal_id_returns_404(client, silent_wav_bytes):
    resp = client.post(
        "/api/ingest",
        files={"file": ("test.wav", io.BytesIO(silent_wav_bytes), "audio/wav")},
        data={"animal_id": "nonexistent-animal-id"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Animal-scoped photo endpoints
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_animal_photo_upload_and_list(client, tmp_dirs):
    photos_dir = tmp_dirs["data"] / "photos"
    photos_dir.mkdir(parents=True, exist_ok=True)
    animal_id = client.app.state.db.get_animals()[0]["id"]

    with (
        patch("meowdb.api.routers.animals.PHOTOS_DIR", photos_dir),
        patch("meowdb.api.routers.photos.PHOTOS_DIR", photos_dir),
    ):
        upload_resp = client.post(
            f"/api/animals/{animal_id}/photos",
            files={"file": ("cat.png", _png_bytes(), "image/png")},
        )
        assert upload_resp.status_code == 201
        photo_data = upload_resp.json()
        assert photo_data["animal_id"] == animal_id

        list_resp = client.get(f"/api/animals/{animal_id}/photos")
    assert list_resp.status_code == 200
    assert len(list_resp.json()["items"]) == 1
    assert list_resp.json()["items"][0]["id"] == photo_data["id"]


@pytest.mark.integration
def test_animal_photo_upload_requires_auth(auth_client, tmp_dirs):
    animal_id = auth_client.app.state.db.get_animals()[0]["id"]
    resp = auth_client.post(
        f"/api/animals/{animal_id}/photos",
        files={"file": ("cat.png", _png_bytes(), "image/png")},
    )
    assert resp.status_code == 401


@pytest.mark.integration
def test_animal_photo_random_empty_returns_404(client):
    animal_id = client.app.state.db.get_animals()[0]["id"]
    resp = client.get(f"/api/animals/{animal_id}/photos/random")
    assert resp.status_code == 404


@pytest.mark.integration
def test_animal_photo_random_with_photo(client, tmp_dirs):
    photos_dir = tmp_dirs["data"] / "photos"
    photos_dir.mkdir(parents=True, exist_ok=True)
    animal_id = client.app.state.db.get_animals()[0]["id"]

    with (
        patch("meowdb.api.routers.animals.PHOTOS_DIR", photos_dir),
        patch("meowdb.api.routers.photos.PHOTOS_DIR", photos_dir),
    ):
        client.post(
            f"/api/animals/{animal_id}/photos",
            files={"file": ("cat.png", _png_bytes(), "image/png")},
        )
        resp = client.get(f"/api/animals/{animal_id}/photos/random")
    assert resp.status_code == 200
    assert resp.json()["animal_id"] == animal_id


@pytest.mark.integration
def test_animal_photo_delete(client, tmp_dirs):
    photos_dir = tmp_dirs["data"] / "photos"
    photos_dir.mkdir(parents=True, exist_ok=True)
    animal_id = client.app.state.db.get_animals()[0]["id"]

    with (
        patch("meowdb.api.routers.animals.PHOTOS_DIR", photos_dir),
        patch("meowdb.api.routers.photos.PHOTOS_DIR", photos_dir),
    ):
        upload_resp = client.post(
            f"/api/animals/{animal_id}/photos",
            files={"file": ("cat.png", _png_bytes(), "image/png")},
        )
        photo_id = upload_resp.json()["id"]

        del_resp = client.delete(f"/api/animals/{animal_id}/photos/{photo_id}")
    assert del_resp.status_code == 204

    list_resp = client.get(f"/api/animals/{animal_id}/photos")
    assert list_resp.json()["items"] == []


@pytest.mark.integration
def test_animal_photo_edit_rotate(client, tmp_dirs):
    photos_dir = tmp_dirs["data"] / "photos"
    photos_dir.mkdir(parents=True, exist_ok=True)
    animal_id = client.app.state.db.get_animals()[0]["id"]

    with (
        patch("meowdb.api.routers.animals.PHOTOS_DIR", photos_dir),
        patch("meowdb.api.routers.photos.PHOTOS_DIR", photos_dir),
    ):
        upload_resp = client.post(
            f"/api/animals/{animal_id}/photos",
            files={"file": ("cat.png", _png_bytes(), "image/png")},
        )
        assert upload_resp.status_code == 201
        photo_id = upload_resp.json()["id"]

        edit_resp = client.post(
            f"/api/animals/{animal_id}/photos/{photo_id}/edit",
            json={"action": "rotate", "direction": "cw"},
        )
    assert edit_resp.status_code == 200
    assert edit_resp.json()["animal_id"] == animal_id


@pytest.mark.integration
def test_animal_photo_upload_heic_accepted_and_converted_to_webp(client, tmp_dirs):
    photos_dir = tmp_dirs["data"] / "photos"
    photos_dir.mkdir(parents=True, exist_ok=True)
    animal_id = client.app.state.db.get_animals()[0]["id"]

    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (200, 100, 50)).save(buf, format="HEIF")
    heic_bytes = buf.getvalue()

    with (
        patch("meowdb.api.routers.animals.PHOTOS_DIR", photos_dir),
        patch("meowdb.api.routers.photos.PHOTOS_DIR", photos_dir),
    ):
        resp = client.post(
            f"/api/animals/{animal_id}/photos",
            files={"file": ("photo.heic", heic_bytes, "image/heic")},
        )
    assert resp.status_code == 201
    data = resp.json()
    assert data["animal_id"] == animal_id
    assert data["filename"].endswith(".webp")


@pytest.mark.integration
def test_animal_photo_upload_unsupported_suffix_returns_400(client):
    animal_id = client.app.state.db.get_animals()[0]["id"]
    resp = client.post(
        f"/api/animals/{animal_id}/photos",
        files={"file": ("doc.bmp", b"fake", "image/bmp")},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Global /photos/random
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_global_random_photo_returns_404_when_empty(client):
    resp = client.get("/api/photos/random")
    assert resp.status_code == 404


@pytest.mark.integration
def test_global_random_photo_includes_animal_id(client, tmp_dirs):
    photos_dir = tmp_dirs["data"] / "photos"
    photos_dir.mkdir(parents=True, exist_ok=True)
    animal_id = client.app.state.db.get_animals()[0]["id"]

    with (
        patch("meowdb.api.routers.animals.PHOTOS_DIR", photos_dir),
        patch("meowdb.api.routers.photos.PHOTOS_DIR", photos_dir),
    ):
        client.post(
            f"/api/animals/{animal_id}/photos",
            files={"file": ("cat.png", _png_bytes(), "image/png")},
        )
        resp = client.get("/api/photos/random")
    assert resp.status_code == 200
    data = resp.json()
    assert "animal_id" in data
    assert data["animal_id"] == animal_id


# ---------------------------------------------------------------------------
# Stats — renamed keys and species_counts
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_stats_has_renamed_keys(client):
    resp = client.get("/api/stats")
    assert resp.status_code == 200
    data = resp.json()
    # Renamed from total_meows
    assert "total_sounds" in data
    assert "total_duration_ms" in data
    assert "first_sound_at" in data
    assert "species_counts" in data
    # Removed key must not be present
    assert "total_meows" not in data


@pytest.mark.integration
def test_stats_species_counts(seeded_client, tmp_dirs):
    db = seeded_client.app.state.db
    rex_id = db.add_animal("Rex", "dog")
    wav_file = next(tmp_dirs["wav"].glob("*.wav"))
    mp3_file = next(tmp_dirs["mp3"].glob("*.mp3"))
    db.add(
        {
            "timestamp": "2026-01-02T00:00:00",
            "duration_ms": 500,
            "labels": [],
            "wav_path": str(wav_file),
            "mp3_path": str(mp3_file),
            "waveform_data": [],
            "peak_dbfs": -10.0,
            "species_energy_ratio": 2.5,
            "animal_id": rex_id,
        }
    )

    resp = seeded_client.get("/api/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_sounds"] == 2
    assert data["species_counts"]["cat"] == 1
    assert data["species_counts"]["dog"] == 1


# ---------------------------------------------------------------------------
# Bootstrap — sound_count and animals list
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_bootstrap_contains_sound_count_and_animals(seeded_client, tmp_dirs):
    (tmp_dirs["static"] / "index.html").write_text(_PLACEHOLDER_HTML)

    resp = seeded_client.get("/")
    assert resp.status_code == 200
    payload = _bootstrap_from(resp.text)

    assert "sound_count" in payload
    assert isinstance(payload["sound_count"], int)
    assert "animals" in payload
    assert isinstance(payload["animals"], list)
    squishy = next((a for a in payload["animals"] if a["name"] == "Squishy"), None)
    assert squishy is not None


# ---------------------------------------------------------------------------
# animal_name / animal_species on sound endpoints
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_list_sounds_include_animal_fields(seeded_client):
    """List endpoint exposes animal_name and animal_species on each sound item."""
    resp = seeded_client.get("/api/sounds")
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["animal_name"] == "Squishy"
    assert item["animal_species"] == "cat"


@pytest.mark.integration
def test_random_sound_includes_animal_fields(seeded_client):
    """Random endpoint exposes animal_name and animal_species."""
    resp = seeded_client.get("/api/sounds/random")
    assert resp.status_code == 200
    data = resp.json()
    assert data["animal_name"] == "Squishy"
    assert data["animal_species"] == "cat"


# ---------------------------------------------------------------------------
# DELETE /api/animals/{id} recomputes species uniqueness scores
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_delete_animal_recomputes_species_scores(seeded_client, tmp_dirs):
    """Deleting one of two same-species animals nulls the surviving sound's species score."""
    db = seeded_client.app.state.db
    wav_file = next(tmp_dirs["wav"].glob("*.wav"))
    mp3_file = next(tmp_dirs["mp3"].glob("*.mp3"))

    # Squishy (cat) already has one sound from the fixture
    sound_id_1 = seeded_client.get("/api/sounds").json()["items"][0]["id"]

    # Second cat animal with one sound — species pool = 2, animal pool = 1 each
    mochi_id = db.add_animal("Mochi", "cat")
    sound_id_2 = db.add(
        {
            "timestamp": "2026-01-02T00:00:00",
            "duration_ms": 750,
            "labels": [],
            "wav_path": str(wav_file),
            "mp3_path": str(mp3_file),
            "waveform_data": [],
            "peak_dbfs": -15.0,
            "species_energy_ratio": 1.5,
            "animal_id": mochi_id,
        }
    )

    # Seed fingerprints so update_library_uniqueness has data to recompute
    fingerprint = [0.1] * 120
    db.update_fingerprint(sound_id_1, fingerprint)
    db.update_fingerprint(sound_id_2, fingerprint)

    # Pre-set non-null species scores to confirm they exist before deletion
    db.update_uniqueness_scores_bulk(
        animal_scores={},
        species_scores={sound_id_1: 50.0, sound_id_2: 50.0},
    )

    # Delete Mochi → species pool shrinks to 1 → Squishy's sound score must become null
    resp = seeded_client.delete(f"/api/animals/{mochi_id}")
    assert resp.status_code == 204

    items = seeded_client.get("/api/sounds").json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == sound_id_1
    assert items[0]["species_uniqueness_score"] is None


# ---------------------------------------------------------------------------
# Stats leaderboard items include mp3_url
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_stats_leaderboard_items_include_mp3_url(seeded_client):
    """Stats leaderboard items carry a non-null mp3_url for sounds that have an mp3."""
    sound_id = seeded_client.get("/api/sounds").json()["items"][0]["id"]

    resp = seeded_client.get("/api/stats")
    assert resp.status_code == 200
    data = resp.json()

    # The seeded sound appears in recent (newest 10 by created_at)
    assert len(data["recent"]) >= 1
    recent_item = next((s for s in data["recent"] if s["id"] == sound_id), None)
    assert recent_item is not None
    assert recent_item["mp3_url"] == f"/api/audio/{sound_id}"


# ---------------------------------------------------------------------------
# POST /api/animals — species validation
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_create_animal_unknown_species_rejected(client):
    """POST /api/animals with an unregistered species returns 400."""
    resp = client.post("/api/animals", json={"name": "Kanga", "species": "kangaroo"})
    assert resp.status_code == 400

    # Mixed-case valid species succeeds and is stored/returned lowercase
    resp = client.post("/api/animals", json={"name": "Rex", "species": "Cat"})
    assert resp.status_code == 201
    assert resp.json()["species"] == "cat"
