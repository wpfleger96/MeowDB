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
        patch("meowdb.api.routers.meows.WAV_DIR", tmp_dirs["wav"]),
        patch("meowdb.api.routers.meows.MP3_DIR", tmp_dirs["mp3"]),
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
        patch("meowdb.api.routers.meows.WAV_DIR", wav_dir),
        patch("meowdb.api.routers.meows.MP3_DIR", mp3_dir),
        patch("meowdb.api.app.SESSION_SECRET", "test-secret-key"),
        patch("meowdb.api.app.IS_LOCALHOST", True),
        patch("meowdb.api.auth.PASSWORD_HASH", ""),
        patch("meowdb.api.auth.IS_LOCALHOST", True),
        warnings.catch_warnings(),
    ):
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        app = create_app()
        with TestClient(app, raise_server_exceptions=True) as tc:
            app.state.db.add(
                {
                    "timestamp": "2026-01-01T00:00:00",
                    "duration_ms": 1000,
                    "labels": [],
                    "wav_path": str(wav_file),
                    "mp3_path": str(mp3_file),
                    "waveform_data": [0.1, 0.2, 0.3],
                    "peak_dbfs": -10.0,
                    "cat_energy_ratio": 2.5,
                }
            )
            yield tc


@pytest.mark.integration
def test_list_meows_empty(client):
    resp = client.get("/api/meows")
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0
    assert data["limit"] == 50
    assert data["offset"] == 0


@pytest.mark.integration
def test_random_meow_empty_returns_404(client):
    resp = client.get("/api/meows/random")
    assert resp.status_code == 404


@pytest.mark.integration
def test_random_meow_with_data(seeded_client):
    resp = seeded_client.get("/api/meows/random")
    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data
    assert data["duration_ms"] == 1000


@pytest.mark.integration
def test_list_meows_with_data(seeded_client):
    resp = seeded_client.get("/api/meows")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["duration_ms"] == 1000


@pytest.mark.integration
def test_patch_meow_labels(seeded_client):
    list_resp = seeded_client.get("/api/meows")
    meow_id = list_resp.json()["items"][0]["id"]

    resp = seeded_client.patch(
        f"/api/meows/{meow_id}",
        json={"labels": ["cute", "loud"]},
    )
    assert resp.status_code == 200
    assert resp.json()["labels"] == ["cute", "loud"]


@pytest.mark.integration
def test_patch_meow_not_found(client):
    resp = client.patch(
        "/api/meows/nonexistent-id",
        json={"labels": ["test"]},
    )
    assert resp.status_code == 404


@pytest.mark.integration
def test_delete_meow(seeded_client):
    list_resp = seeded_client.get("/api/meows")
    meow_id = list_resp.json()["items"][0]["id"]

    resp = seeded_client.delete(f"/api/meows/{meow_id}")
    assert resp.status_code == 204

    list_resp2 = seeded_client.get("/api/meows")
    assert list_resp2.json()["total"] == 0


@pytest.mark.integration
def test_delete_meow_not_found(client):
    resp = client.delete("/api/meows/nonexistent-id")
    assert resp.status_code == 404


@pytest.mark.integration
def test_play_meow(seeded_client):
    list_resp = seeded_client.get("/api/meows")
    initial_play_count = list_resp.json()["items"][0]["play_count"]
    meow_id = list_resp.json()["items"][0]["id"]

    resp = seeded_client.post(f"/api/meows/{meow_id}/play")
    assert resp.status_code == 204

    list_resp2 = seeded_client.get("/api/meows")
    new_play_count = list_resp2.json()["items"][0]["play_count"]
    assert new_play_count == initial_play_count + 1


@pytest.mark.integration
def test_play_meow_not_found(client):
    response = client.post("/api/meows/nonexistent-id/play")
    assert response.status_code == 404


@pytest.mark.integration
def test_get_stats_empty(client):
    resp = client.get("/api/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_meows"] == 0
    assert data["total_duration_ms"] == 0
    assert data["label_counts"] == {}


@pytest.mark.integration
def test_get_stats_with_data(seeded_client):
    resp = seeded_client.get("/api/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_meows"] == 1
    assert data["total_duration_ms"] == 1000


@pytest.mark.integration
def test_get_labels_empty(client):
    resp = client.get("/api/labels")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.integration
def test_get_labels_with_data(seeded_client):
    list_resp = seeded_client.get("/api/meows")
    meow_id = list_resp.json()["items"][0]["id"]
    seeded_client.patch(f"/api/meows/{meow_id}", json={"labels": ["happy"]})

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


@pytest.mark.integration
def test_audio_stream_with_data(seeded_client):
    list_resp = seeded_client.get("/api/meows")
    meow_id = list_resp.json()["items"][0]["id"]

    resp = seeded_client.get(f"/api/audio/{meow_id}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/mpeg"


@pytest.mark.integration
def test_feedback_upvote(seeded_client):
    meow_id = seeded_client.get("/api/meows").json()["items"][0]["id"]
    resp = seeded_client.post(f"/api/meows/{meow_id}/feedback", json={"vote": "up"})
    assert resp.status_code == 204
    data = seeded_client.get("/api/meows").json()["items"][0]
    assert data["upvote_count"] == 1
    assert data["downvote_count"] == 0


@pytest.mark.integration
def test_feedback_downvote(seeded_client):
    meow_id = seeded_client.get("/api/meows").json()["items"][0]["id"]
    resp = seeded_client.post(f"/api/meows/{meow_id}/feedback", json={"vote": "down"})
    assert resp.status_code == 204
    data = seeded_client.get("/api/meows").json()["items"][0]
    assert data["downvote_count"] == 1
    assert data["upvote_count"] == 0


@pytest.mark.integration
def test_feedback_invalid_vote(seeded_client):
    meow_id = seeded_client.get("/api/meows").json()["items"][0]["id"]
    resp = seeded_client.post(f"/api/meows/{meow_id}/feedback", json={"vote": "sideways"})
    assert resp.status_code == 422


@pytest.mark.integration
def test_feedback_not_found(client):
    resp = client.post("/api/meows/nonexistent-id/feedback", json={"vote": "up"})
    assert resp.status_code == 404


@pytest.mark.integration
def test_feedback_switch_vote(seeded_client):
    meow_id = seeded_client.get("/api/meows").json()["items"][0]["id"]
    seeded_client.post(f"/api/meows/{meow_id}/feedback", json={"vote": "up"})
    resp = seeded_client.post(
        f"/api/meows/{meow_id}/feedback", json={"vote": "down", "previous": "up"}
    )
    assert resp.status_code == 204
    data = seeded_client.get("/api/meows").json()["items"][0]
    assert data["upvote_count"] == 0
    assert data["downvote_count"] == 1


@pytest.mark.integration
def test_list_meows_sort_most_downvoted(seeded_client, tmp_dirs):
    # Add a second meow with more downvotes
    wav_file = next(tmp_dirs["wav"].glob("*.wav"))
    mp3_file = next(tmp_dirs["mp3"].glob("*.mp3"))
    meow_id_1 = seeded_client.get("/api/meows").json()["items"][0]["id"]
    meow_id_2 = seeded_client.app.state.db.add(
        {
            "timestamp": "2026-01-02T00:00:00",
            "duration_ms": 500,
            "labels": [],
            "wav_path": str(wav_file),
            "mp3_path": str(mp3_file),
            "waveform_data": [],
            "peak_dbfs": -10.0,
            "cat_energy_ratio": 2.5,
        }
    )
    seeded_client.post(f"/api/meows/{meow_id_1}/feedback", json={"vote": "down"})
    seeded_client.post(f"/api/meows/{meow_id_2}/feedback", json={"vote": "down"})
    seeded_client.post(f"/api/meows/{meow_id_2}/feedback", json={"vote": "down"})

    resp = seeded_client.get("/api/meows?sort=most_downvoted")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert items[0]["id"] == meow_id_2
    assert items[0]["downvote_count"] == 2


@pytest.mark.integration
def test_list_meows_sort_most_upvoted(seeded_client, tmp_dirs):
    wav_file = next(tmp_dirs["wav"].glob("*.wav"))
    mp3_file = next(tmp_dirs["mp3"].glob("*.mp3"))
    meow_id_1 = seeded_client.get("/api/meows").json()["items"][0]["id"]
    meow_id_2 = seeded_client.app.state.db.add(
        {
            "timestamp": "2026-01-02T00:00:00",
            "duration_ms": 500,
            "labels": [],
            "wav_path": str(wav_file),
            "mp3_path": str(mp3_file),
            "waveform_data": [],
            "peak_dbfs": -10.0,
            "cat_energy_ratio": 2.5,
        }
    )
    seeded_client.post(f"/api/meows/{meow_id_1}/feedback", json={"vote": "up"})
    seeded_client.post(f"/api/meows/{meow_id_1}/feedback", json={"vote": "up"})
    seeded_client.post(f"/api/meows/{meow_id_2}/feedback", json={"vote": "up"})

    resp = seeded_client.get("/api/meows?sort=most_upvoted")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert items[0]["id"] == meow_id_1
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
        patch("meowdb.api.routers.meows.WAV_DIR", tmp_dirs["wav"]),
        patch("meowdb.api.routers.meows.MP3_DIR", tmp_dirs["mp3"]),
        patch("meowdb.api.app.SESSION_SECRET", "test-secret-key"),
        patch("meowdb.api.app.IS_LOCALHOST", True),
        patch("meowdb.api.auth.PASSWORD_HASH", ""),
        patch("meowdb.api.auth.IS_LOCALHOST", True),
        warnings.catch_warnings(),
    ):
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        app = create_app()
        with TestClient(app, raise_server_exceptions=True) as tc:
            wav_bytes = silent_wav_bytes
            resp = tc.post(
                "/api/ingest",
                files={"file": ("test.wav", wav_bytes, "audio/wav")},
            )
            assert resp.status_code == 202
            data = resp.json()
            assert data["status"] == "uploaded"
            job_id = data["job_id"]
            assert job_id

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
        patch("meowdb.api.routers.meows.WAV_DIR", wav_dir),
        patch("meowdb.api.routers.meows.MP3_DIR", mp3_dir),
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
            job_id = db.create_job("test.wav")
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
                        "cat_energy_ratio": 2.0,
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
            assert len(data["meow_ids"]) == 1
            assert data["rejected_count"] == 0


@pytest.mark.integration
def test_stream_source_audio(client, silent_wav_bytes):
    wav_bytes = silent_wav_bytes
    resp = client.post(
        "/api/ingest",
        files={"file": ("test.wav", io.BytesIO(wav_bytes), "audio/wav")},
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
    wav_bytes = silent_wav_bytes
    resp = client.post(
        "/api/ingest",
        files={"file": ("test.wav", io.BytesIO(wav_bytes), "audio/wav")},
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
    wav_bytes = silent_wav_bytes
    resp = client.post(
        "/api/ingest",
        files={"file": ("test.wav", io.BytesIO(wav_bytes), "audio/wav")},
    )
    job_id = resp.json()["job_id"]

    # Clip a region from the uploaded file (default audio is 1 second)
    resp = client.post(
        f"/api/ingest/{job_id}/clip",
        json={"regions": [{"start_ms": 0, "end_ms": 500}]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["meow_ids"]) == 1
    assert data["rejected_count"] == 0


@pytest.mark.integration
def test_clip_empty_regions_rejected(client, silent_wav_bytes):
    wav_bytes = silent_wav_bytes
    resp = client.post(
        "/api/ingest",
        files={"file": ("test.wav", io.BytesIO(wav_bytes), "audio/wav")},
    )
    job_id = resp.json()["job_id"]

    resp = client.post(
        f"/api/ingest/{job_id}/clip",
        json={"regions": []},
    )
    assert resp.status_code == 400


@pytest.mark.integration
def test_clip_inverted_region_rejected(client, silent_wav_bytes):
    wav_bytes = silent_wav_bytes
    resp = client.post(
        "/api/ingest",
        files={"file": ("test.wav", io.BytesIO(wav_bytes), "audio/wav")},
    )
    job_id = resp.json()["job_id"]

    resp = client.post(
        f"/api/ingest/{job_id}/clip",
        json={"regions": [{"start_ms": 500, "end_ms": 100}]},
    )
    assert resp.status_code == 422


@pytest.mark.integration
def test_clip_negative_region_rejected(client, silent_wav_bytes):
    wav_bytes = silent_wav_bytes
    resp = client.post(
        "/api/ingest",
        files={"file": ("test.wav", io.BytesIO(wav_bytes), "audio/wav")},
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
        patch("meowdb.api.routers.meows.WAV_DIR", tmp_dirs["wav"]),
        patch("meowdb.api.routers.meows.MP3_DIR", tmp_dirs["mp3"]),
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
        patch("meowdb.api.routers.meows.WAV_DIR", tmp_dirs["wav"]),
        patch("meowdb.api.routers.meows.MP3_DIR", tmp_dirs["mp3"]),
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
def test_delete_meow_requires_auth(auth_client):
    resp = auth_client.delete("/api/meows/nonexistent-id")
    assert resp.status_code == 401


@pytest.mark.integration
def test_public_endpoint_without_auth(auth_client):
    resp = auth_client.get("/api/meows")
    assert resp.status_code == 200


@pytest.mark.integration
def test_logout(auth_client):
    auth_client.post("/api/auth/login", json={"password": _TEST_PASSWORD})

    resp = auth_client.post("/api/auth/logout")
    assert resp.status_code == 200

    resp = auth_client.delete("/api/meows/nonexistent-id")
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
def test_patch_meow_requires_auth(auth_client):
    resp = auth_client.patch("/api/meows/nonexistent-id", json={"labels": ["test"]})
    assert resp.status_code == 401


@pytest.mark.integration
def test_login_grants_access_to_protected_endpoint(auth_client):
    auth_client.post("/api/auth/login", json={"password": _TEST_PASSWORD})
    resp = auth_client.patch("/api/meows/nonexistent-id", json={"labels": ["test"]})
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
        patch("meowdb.api.routers.meows.WAV_DIR", tmp_dirs["wav"]),
        patch("meowdb.api.routers.meows.MP3_DIR", tmp_dirs["mp3"]),
        patch("meowdb.api.app.SESSION_SECRET", "test-secret-key"),
        patch("meowdb.api.app.IS_LOCALHOST", True),
        patch("meowdb.api.auth.PASSWORD_HASH", ""),
        patch("meowdb.api.auth.IS_LOCALHOST", False),  # public host, bypass should NOT trigger
        warnings.catch_warnings(),
    ):
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        app = create_app()
        with TestClient(app, raise_server_exceptions=True) as tc:
            resp = tc.delete("/api/meows/nonexistent-id")
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
    resp = client.delete("/api/meows/nonexistent-id")
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
    assert isinstance(payload["meow_count"], int)
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

    with patch("meowdb.api.routers.photos.PHOTOS_DIR", photos_dir):
        upload_resp = client.post(
            "/api/photos",
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
