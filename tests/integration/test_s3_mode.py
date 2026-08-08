from __future__ import annotations

import io

import pytest

from PIL import Image

_BUCKET = "test-meowdb"


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "black").save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Audio serve in S3 mode
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_audio_serve_full_body_from_s3(s3_api_client):
    tc, app, s3 = s3_api_client

    content = b"fake-mp3-data" * 50
    mp3_s3_key = "audio/mp3/serve-test.mp3"
    s3.put_object(Bucket=_BUCKET, Key=mp3_s3_key, Body=content)

    meow_id = app.state.db.add(
        {
            "timestamp": "2026-01-01T00:00:00",
            "duration_ms": 1000,
            "labels": [],
            "wav_path": "audio/wav/serve-test.wav",
            "mp3_path": mp3_s3_key,
            "waveform_data": [],
            "peak_dbfs": -10.0,
            "cat_energy_ratio": 2.5,
        }
    )

    resp = tc.get(f"/api/audio/{meow_id}")

    assert resp.status_code == 200
    assert resp.content == content
    assert resp.headers["content-type"] == "audio/mpeg"


@pytest.mark.integration
def test_audio_serve_range_returns_206_with_correct_slice(s3_api_client):
    tc, app, s3 = s3_api_client

    content = bytes(range(256))  # 256 distinct bytes, one per offset
    mp3_s3_key = "audio/mp3/range-test.mp3"
    s3.put_object(Bucket=_BUCKET, Key=mp3_s3_key, Body=content)

    meow_id = app.state.db.add(
        {
            "timestamp": "2026-01-01T00:00:00",
            "duration_ms": 500,
            "labels": [],
            "wav_path": "audio/wav/range-test.wav",
            "mp3_path": mp3_s3_key,
            "waveform_data": [],
            "peak_dbfs": -10.0,
            "cat_energy_ratio": 2.5,
        }
    )

    resp = tc.get(f"/api/audio/{meow_id}", headers={"Range": "bytes=10-19"})

    assert resp.status_code == 206
    assert resp.headers["content-range"] == f"bytes 10-19/{len(content)}"
    assert resp.content == content[10:20]


@pytest.mark.integration
def test_audio_serve_missing_s3_key_returns_404(s3_api_client):
    tc, app, _s3 = s3_api_client

    meow_id = app.state.db.add(
        {
            "timestamp": "2026-01-01T00:00:00",
            "duration_ms": 500,
            "labels": [],
            "wav_path": "audio/wav/ghost.wav",
            "mp3_path": "audio/mp3/ghost.mp3",
            "waveform_data": [],
            "peak_dbfs": -10.0,
            "cat_energy_ratio": 2.5,
        }
    )

    resp = tc.get(f"/api/audio/{meow_id}")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Photo lifecycle in S3 mode
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_photo_upload_stores_in_bucket_and_removes_local(s3_api_client, tmp_path):
    tc, app, s3 = s3_api_client

    resp = tc.post(
        "/api/photos",
        files={"file": ("cat.png", _png_bytes(), "image/png")},
    )
    assert resp.status_code == 201
    photo_id = resp.json()["id"]

    photo = app.state.db.get_photo(photo_id)
    assert photo is not None
    filename = photo["filename"]

    # Object is in the S3 bucket
    bucket_keys = [o["Key"] for o in s3.list_objects_v2(Bucket=_BUCKET).get("Contents", [])]
    assert f"photos/{filename}" in bucket_keys

    # Local file was removed after upload
    photos_dir = tmp_path / "photos"
    assert not (photos_dir / filename).exists()


@pytest.mark.integration
def test_photo_serve_returns_bytes_and_etag_header(s3_api_client):
    tc, app, _s3 = s3_api_client

    resp = tc.post(
        "/api/photos",
        files={"file": ("kitty.png", _png_bytes(), "image/png")},
    )
    assert resp.status_code == 201
    photo_id = resp.json()["id"]

    serve_resp = tc.get(f"/api/photos/{photo_id}/image")

    assert serve_resp.status_code == 200
    assert "etag" in serve_resp.headers
    assert len(serve_resp.content) > 0


@pytest.mark.integration
def test_photo_delete_removes_s3_object(s3_api_client):
    tc, app, s3 = s3_api_client

    resp = tc.post(
        "/api/photos",
        files={"file": ("meow.png", _png_bytes(), "image/png")},
    )
    assert resp.status_code == 201
    photo_id = resp.json()["id"]
    filename = app.state.db.get_photo(photo_id)["filename"]

    del_resp = tc.delete(f"/api/photos/{photo_id}")
    assert del_resp.status_code == 204

    # Object is gone from the bucket
    remaining_keys = [o["Key"] for o in s3.list_objects_v2(Bucket=_BUCKET).get("Contents", [])]
    assert f"photos/{filename}" not in remaining_keys

    # DB record is gone
    assert app.state.db.get_photo(photo_id) is None


# ---------------------------------------------------------------------------
# Ingest commit in S3 mode — files uploaded, DB paths become S3 keys
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_ingest_commit_uploads_to_s3_and_removes_local(s3_api_client, tmp_path, silent_wav_bytes):
    tc, app, s3 = s3_api_client

    wav_dir = tmp_path / "wav"
    mp3_dir = tmp_path / "mp3"
    staging_dir = tmp_path / "staging"

    db = app.state.db
    job_id = db.create_job("test.wav")
    job_staging = staging_dir / job_id
    job_staging.mkdir(parents=True, exist_ok=True)

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
    meow_ids = commit_resp.json()["meow_ids"]
    assert len(meow_ids) == 1
    meow_id = meow_ids[0]

    # Both WAV and MP3 objects landed in the bucket
    bucket_keys = [o["Key"] for o in s3.list_objects_v2(Bucket=_BUCKET).get("Contents", [])]
    assert f"audio/wav/{meow_id}.wav" in bucket_keys
    assert f"audio/mp3/{meow_id}.mp3" in bucket_keys

    # DB row holds S3 keys, not absolute paths
    meow = db.get_by_id(meow_id)
    assert meow is not None
    assert meow["wav_path"] == f"audio/wav/{meow_id}.wav"
    assert meow["mp3_path"] == f"audio/mp3/{meow_id}.mp3"

    # Local copies removed from WAV/MP3 dirs
    assert not (wav_dir / f"{meow_id}.wav").exists()
    assert not (mp3_dir / f"{meow_id}.mp3").exists()


# ---------------------------------------------------------------------------
# Meow delete in S3 mode removes both S3 objects
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_meow_delete_removes_wav_and_mp3_from_s3(s3_api_client):
    tc, app, s3 = s3_api_client

    wav_s3_key = "audio/wav/del-test.wav"
    mp3_s3_key = "audio/mp3/del-test.mp3"
    s3.put_object(Bucket=_BUCKET, Key=wav_s3_key, Body=b"wav")
    s3.put_object(Bucket=_BUCKET, Key=mp3_s3_key, Body=b"mp3")

    meow_id = app.state.db.add(
        {
            "timestamp": "2026-01-01T00:00:00",
            "duration_ms": 1000,
            "labels": [],
            "wav_path": wav_s3_key,
            "mp3_path": mp3_s3_key,
            "waveform_data": [],
            "peak_dbfs": -10.0,
            "cat_energy_ratio": 2.5,
        }
    )

    del_resp = tc.delete(f"/api/meows/{meow_id}")
    assert del_resp.status_code == 204

    remaining_keys = [o["Key"] for o in s3.list_objects_v2(Bucket=_BUCKET).get("Contents", [])]
    assert wav_s3_key not in remaining_keys
    assert mp3_s3_key not in remaining_keys
