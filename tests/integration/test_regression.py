"""Regression tests for behaviours fixed after initial review.

Covers:
  1. Suffix Range requests (bytes=-N semantics via audio serve endpoint)
  2. Mixed-mode S3: absolute-path rows served/deleted from disk when S3 is active
  3. Ingest batch resilience: meow with missing MP3 kept local; rest of batch migrates
  4. Photo upload atomicity: S3 failure before db.add_photo leaves no DB record
  5. edit_photo in S3 mode (in-place webp + format-converting jpg→webp)
  6. upload_photo: DB failure rolls back S3 object and local file
"""

from __future__ import annotations

import asyncio
import io
import uuid

from unittest.mock import patch

import pytest

from PIL import Image

from meowdb.api.routers.ingest import _upload_committed_to_s3
from meowdb.db import MeowDB
from meowdb.storage import mp3_key

_BUCKET = "test-meowdb"


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "black").save(buf, format="PNG")
    return buf.getvalue()


def _webp_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buf, format="WEBP")
    return buf.getvalue()


def _jpg_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "blue").save(buf, format="JPEG")
    return buf.getvalue()


def _meow_row(wav_path: str = "audio/wav/x.wav", mp3_path: str = "audio/mp3/x.mp3") -> dict:
    return {
        "timestamp": "2026-01-01T00:00:00",
        "duration_ms": 500,
        "labels": [],
        "wav_path": wav_path,
        "mp3_path": mp3_path,
        "waveform_data": [],
        "peak_dbfs": -10.0,
        "cat_energy_ratio": 2.5,
    }


# ===========================================================================
# 1. Suffix Range requests
# ===========================================================================


@pytest.mark.integration
def test_suffix_range_returns_last_n_bytes(s3_api_client):
    """bytes=-50 on a 100-byte object → 206, last 50 bytes, correct Content-Range."""
    tc, app, s3 = s3_api_client

    content = bytes(range(100))
    meow_id = app.state.db.add(_meow_row())
    s3.put_object(Bucket=_BUCKET, Key=mp3_key(meow_id), Body=content)

    resp = tc.get(f"/api/audio/{meow_id}", headers={"Range": "bytes=-50"})

    assert resp.status_code == 206
    assert resp.headers["content-range"] == "bytes 50-99/100"
    assert resp.content == content[50:]


@pytest.mark.integration
def test_suffix_range_zero_returns_416(s3_api_client):
    """bytes=-0 is unsatisfiable → 416."""
    tc, app, s3 = s3_api_client

    meow_id = app.state.db.add(_meow_row())
    s3.put_object(Bucket=_BUCKET, Key=mp3_key(meow_id), Body=bytes(range(100)))

    resp = tc.get(f"/api/audio/{meow_id}", headers={"Range": "bytes=-0"})
    assert resp.status_code == 416


@pytest.mark.integration
def test_suffix_range_larger_than_file_returns_whole_file(s3_api_client):
    """bytes=-200 on a 100-byte object → 206, whole file, Content-Range starts at 0."""
    tc, app, s3 = s3_api_client

    content = bytes(range(100))
    meow_id = app.state.db.add(_meow_row())
    s3.put_object(Bucket=_BUCKET, Key=mp3_key(meow_id), Body=content)

    resp = tc.get(f"/api/audio/{meow_id}", headers={"Range": "bytes=-200"})

    assert resp.status_code == 206
    assert resp.headers["content-range"] == "bytes 0-99/100"
    assert resp.content == content


# ===========================================================================
# 2. Mixed-mode S3: absolute-path rows still served / deleted from disk
# ===========================================================================


@pytest.mark.integration
def test_audio_serve_absolute_path_in_s3_mode_serves_from_disk(s3_api_client, tmp_path):
    """A meow row with an absolute local MP3 path is served from disk (not 404) in S3 mode."""
    tc, app, _s3 = s3_api_client

    mp3_dir = tmp_path / "mp3"
    mp3_dir.mkdir(exist_ok=True)
    content = b"local-mp3-bytes"
    mp3_file = mp3_dir / "local.mp3"
    mp3_file.write_bytes(content)

    meow_id = app.state.db.add(
        _meow_row(wav_path=str(tmp_path / "wav" / "x.wav"), mp3_path=str(mp3_file))
    )

    resp = tc.get(f"/api/audio/{meow_id}")

    assert resp.status_code == 200
    assert resp.content == content


@pytest.mark.integration
def test_meow_delete_absolute_path_in_s3_mode_unlinks_local_files(s3_api_client, tmp_path):
    """Deleting a meow with absolute local paths in S3 mode removes the local files."""
    tc, app, _s3 = s3_api_client

    wav_dir = tmp_path / "wav"
    mp3_dir = tmp_path / "mp3"
    wav_dir.mkdir(exist_ok=True)
    mp3_dir.mkdir(exist_ok=True)

    wav_file = wav_dir / "local.wav"
    mp3_file = mp3_dir / "local.mp3"
    wav_file.write_bytes(b"wav-data")
    mp3_file.write_bytes(b"mp3-data")

    meow_id = app.state.db.add(_meow_row(wav_path=str(wav_file), mp3_path=str(mp3_file)))

    resp = tc.delete(f"/api/meows/{meow_id}")

    assert resp.status_code == 204
    assert not wav_file.exists()
    assert not mp3_file.exists()


@pytest.mark.integration
def test_photo_serve_uses_local_file_when_present_in_s3_mode(s3_api_client, tmp_path):
    """In S3 mode, if PHOTOS_DIR/filename exists locally it is served from disk."""
    tc, app, _s3 = s3_api_client

    photos_dir = tmp_path / "photos"
    photos_dir.mkdir(exist_ok=True)
    filename = "local-photo.webp"
    content = b"webp-local-bytes"
    (photos_dir / filename).write_bytes(content)

    app.state.db.add_photo(filename)
    photo_id = app.state.db.get_photos()[0]["id"]

    resp = tc.get(f"/api/photos/{photo_id}/image")

    assert resp.status_code == 200
    assert resp.content == content


@pytest.mark.integration
def test_photo_serve_falls_back_to_s3_when_local_absent(s3_api_client, tmp_path):
    """In S3 mode, if local file is absent the photo is served from S3."""
    tc, app, s3 = s3_api_client

    filename = "s3-only-photo.webp"
    content = b"webp-s3-bytes"
    s3.put_object(Bucket=_BUCKET, Key=f"photos/{filename}", Body=content)

    app.state.db.add_photo(filename)
    photo_id = app.state.db.get_photos()[0]["id"]

    photos_dir = tmp_path / "photos"
    assert not (photos_dir / filename).exists()

    resp = tc.get(f"/api/photos/{photo_id}/image")

    assert resp.status_code == 200
    assert resp.content == content


@pytest.mark.integration
def test_photo_delete_removes_local_file_and_s3_object(s3_api_client, tmp_path):
    """Deleting a photo in S3 mode removes both the local file and the S3 object."""
    tc, app, s3 = s3_api_client

    photos_dir = tmp_path / "photos"
    photos_dir.mkdir(exist_ok=True)
    filename = "double-photo.webp"
    local_file = photos_dir / filename
    local_file.write_bytes(b"photo-content")
    s3.put_object(Bucket=_BUCKET, Key=f"photos/{filename}", Body=b"photo-content")

    app.state.db.add_photo(filename)
    photo_id = app.state.db.get_photos()[0]["id"]

    resp = tc.delete(f"/api/photos/{photo_id}")

    assert resp.status_code == 204
    assert not local_file.exists()
    remaining = [o["Key"] for o in s3.list_objects_v2(Bucket=_BUCKET).get("Contents", [])]
    assert f"photos/{filename}" not in remaining


# ===========================================================================
# 3. Ingest batch resilience: missing MP3 → meow keeps local paths; rest migrates
# ===========================================================================


@pytest.mark.integration
def test_upload_committed_to_s3_skips_meow_with_missing_mp3(s3_state, tmp_path):
    """_upload_committed_to_s3 skips a meow whose local MP3 is absent.

    The skipped meow retains its original DB paths; the complete meow migrates.
    """
    wav_dir = tmp_path / "wav"
    mp3_dir = tmp_path / "mp3"
    wav_dir.mkdir()
    mp3_dir.mkdir()
    db = MeowDB(tmp_path / "test.sqlite")

    meow1_id = db.add(_meow_row())
    meow2_id = db.add(_meow_row())

    # meow1 has both WAV and MP3 local files
    (wav_dir / f"{meow1_id}.wav").write_bytes(b"wav-1")
    (mp3_dir / f"{meow1_id}.mp3").write_bytes(b"mp3-1")

    # meow2 has only WAV — MP3 is missing
    (wav_dir / f"{meow2_id}.wav").write_bytes(b"wav-2")

    with (
        patch("meowdb.api.routers.ingest.WAV_DIR", wav_dir),
        patch("meowdb.api.routers.ingest.MP3_DIR", mp3_dir),
    ):
        asyncio.run(_upload_committed_to_s3(db, [meow1_id, meow2_id]))

    bucket_keys = [o["Key"] for o in s3_state.list_objects_v2(Bucket=_BUCKET).get("Contents", [])]

    # meow1 fully migrated
    assert f"audio/wav/{meow1_id}.wav" in bucket_keys
    assert f"audio/mp3/{meow1_id}.mp3" in bucket_keys
    m1 = db.get_by_id(meow1_id)
    assert m1 is not None
    assert m1["wav_path"] == f"audio/wav/{meow1_id}.wav"
    assert not (wav_dir / f"{meow1_id}.wav").exists()

    # meow2 skipped — no S3 objects, local WAV still present, DB path NOT changed
    assert f"audio/wav/{meow2_id}.wav" not in bucket_keys
    m2 = db.get_by_id(meow2_id)
    assert m2 is not None
    assert m2["wav_path"] == "audio/wav/x.wav"  # unchanged from initial seed value
    assert (wav_dir / f"{meow2_id}.wav").exists()

    db.close()


# ===========================================================================
# 4. Photo upload atomicity: S3 failure → no DB record
# ===========================================================================


@pytest.mark.integration
def test_photo_upload_s3_failure_leaves_no_db_record(s3_api_client):
    """If upload_to_s3 raises during photo upload, no DB record is created."""
    tc, app, _s3 = s3_api_client

    with patch(
        "meowdb.api.routers.photos.upload_to_s3", side_effect=RuntimeError("S3 unavailable")
    ):
        with pytest.raises(RuntimeError):
            tc.post(
                "/api/photos",
                files={"file": ("cat.png", _png_bytes(), "image/png")},
            )

    assert app.state.db.get_photos() == []


# ===========================================================================
# 5. edit_photo in S3 mode
# ===========================================================================


@pytest.mark.integration
def test_edit_photo_s3_in_place_webp(s3_api_client, tmp_path):
    """Rotating a WebP photo re-uploads under the SAME key; DB updated_at bumped."""
    tc, app, s3 = s3_api_client

    photos_dir = tmp_path / "photos"
    photos_dir.mkdir(exist_ok=True)
    photo_id = str(uuid.uuid4())
    filename = f"{photo_id}.webp"

    original_bytes = _webp_bytes()
    s3.put_object(Bucket=_BUCKET, Key=f"photos/{filename}", Body=original_bytes)
    app.state.db.add_photo(filename, photo_id=photo_id)

    resp = tc.post(
        f"/api/photos/{photo_id}/edit",
        json={"action": "rotate", "direction": "cw"},
    )
    assert resp.status_code == 200
    assert resp.json()["filename"] == filename  # same filename (in-place)

    # Object still exists under the same key
    bucket_keys = [o["Key"] for o in s3.list_objects_v2(Bucket=_BUCKET).get("Contents", [])]
    assert f"photos/{filename}" in bucket_keys

    # Bytes changed (rotation produced different content)
    new_bytes = s3.get_object(Bucket=_BUCKET, Key=f"photos/{filename}")["Body"].read()
    assert new_bytes != original_bytes

    # No temp files left in PHOTOS_DIR
    temp_files = list(photos_dir.glob("_edit_*")) + list(photos_dir.glob("tmp*"))
    assert temp_files == [], f"Temp files not cleaned up: {temp_files}"

    # DB updated_at was bumped (touch_photo)
    photo = app.state.db.get_photo(photo_id)
    assert photo is not None
    assert photo["updated_at"] is not None


@pytest.mark.integration
def test_edit_photo_s3_format_converting_jpg_to_webp(s3_api_client, tmp_path):
    """Editing a JPEG photo uploads under a new .webp key, deletes the old .jpg key."""
    tc, app, s3 = s3_api_client

    photos_dir = tmp_path / "photos"
    photos_dir.mkdir(exist_ok=True)
    photo_id = str(uuid.uuid4())
    jpg_filename = f"{photo_id}.jpg"
    webp_filename = f"{photo_id}.webp"

    s3.put_object(Bucket=_BUCKET, Key=f"photos/{jpg_filename}", Body=_jpg_bytes())
    app.state.db.add_photo(jpg_filename, photo_id=photo_id)

    resp = tc.post(
        f"/api/photos/{photo_id}/edit",
        json={"action": "rotate", "direction": "cw"},
    )
    assert resp.status_code == 200
    result = resp.json()
    assert result["filename"] == webp_filename  # converted to webp

    # New key present, old key gone
    bucket_keys = [o["Key"] for o in s3.list_objects_v2(Bucket=_BUCKET).get("Contents", [])]
    assert f"photos/{webp_filename}" in bucket_keys
    assert f"photos/{jpg_filename}" not in bucket_keys

    # DB filename updated
    photo = app.state.db.get_photo(photo_id)
    assert photo is not None
    assert photo["filename"] == webp_filename

    # No temp files left in PHOTOS_DIR
    temp_files = list(photos_dir.glob("_edit_*")) + list(photos_dir.glob("tmp*"))
    assert temp_files == [], f"Temp files not cleaned up: {temp_files}"


# ===========================================================================
# 6. upload_photo: DB failure rolls back S3 object and local file
# ===========================================================================


@pytest.mark.integration
def test_photo_upload_db_failure_cleans_up_s3_and_local(s3_api_client, tmp_path):
    """If db.add_photo raises after a successful S3 upload, the S3 object is deleted
    and no local file is left in PHOTOS_DIR."""
    tc, app, s3 = s3_api_client

    photos_dir = tmp_path / "photos"

    with patch.object(app.state.db, "add_photo", side_effect=RuntimeError("DB full")):
        with pytest.raises(RuntimeError):
            tc.post(
                "/api/photos",
                files={"file": ("cat.png", _png_bytes(), "image/png")},
            )

    # No S3 objects left from the failed upload
    objects = s3.list_objects_v2(Bucket=_BUCKET).get("Contents", [])
    assert objects == [], f"Orphaned S3 objects: {[o['Key'] for o in objects]}"

    # No local files left in PHOTOS_DIR
    photos_dir.mkdir(exist_ok=True)  # may not have been created yet — that's fine
    local_files = [f for f in photos_dir.iterdir() if f.is_file()]
    assert local_files == [], f"Orphaned local files: {local_files}"
