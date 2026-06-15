from __future__ import annotations

import io
import shutil
import struct
import warnings
import wave

from pathlib import Path
from unittest.mock import patch

import pytest

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    from starlette.testclient import TestClient

from meowdb.api.app import create_app


def _make_silent_wav_bytes() -> bytes:
    sample_rate = 44100
    num_frames = sample_rate
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack("<" + "h" * num_frames, *([0] * num_frames)))
    return buf.getvalue()


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
        warnings.catch_warnings(),
    ):
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        app = create_app()
        with TestClient(app, raise_server_exceptions=True) as tc:
            yield tc


@pytest.fixture
def seeded_client(tmp_dirs):
    wav_dir = tmp_dirs["wav"]
    mp3_dir = tmp_dirs["mp3"]
    wav_dir.mkdir(parents=True, exist_ok=True)
    mp3_dir.mkdir(parents=True, exist_ok=True)

    wav_file = wav_dir / "test.wav"
    mp3_file = mp3_dir / "test.mp3"
    wav_file.write_bytes(_make_silent_wav_bytes())
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
def test_ingest_job_not_found(client):
    resp = client.get("/api/ingest/nonexistent-job-id")
    assert resp.status_code == 404


@pytest.mark.integration
def test_ingest_delete_not_found(client):
    resp = client.delete("/api/ingest/nonexistent-job-id")
    assert resp.status_code == 404


@pytest.mark.integration
def test_ingest_flow_post_and_poll(tmp_dirs):
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
        warnings.catch_warnings(),
    ):
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        app = create_app()
        with TestClient(app, raise_server_exceptions=True) as tc:
            wav_bytes = _make_silent_wav_bytes()
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
def test_ingest_commit(tmp_dirs):
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
            seg_wav.write_bytes(_make_silent_wav_bytes())
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
def test_stream_source_audio(client):
    wav_bytes = _make_silent_wav_bytes()
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
def test_detect_regions(client):
    wav_bytes = _make_silent_wav_bytes()
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
def test_clip_and_commit(client):
    wav_bytes = _make_silent_wav_bytes()
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
def test_clip_empty_regions_rejected(client):
    wav_bytes = _make_silent_wav_bytes()
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
def test_clip_inverted_region_rejected(client):
    wav_bytes = _make_silent_wav_bytes()
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
def test_clip_negative_region_rejected(client):
    wav_bytes = _make_silent_wav_bytes()
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
