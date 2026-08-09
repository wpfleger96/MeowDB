from __future__ import annotations

import asyncio

import boto3
import pytest

from moto import mock_aws

from meowdb import config
from meowdb.storage import (
    S3NotFoundError,
    _reset_s3_client,
    delete_from_s3_sync,
    download_from_s3_sync,
    is_s3_enabled,
    mp3_key,
    photo_key,
    s3_head_object,
    upload_to_s3_sync,
    wav_key,
)

_BUCKET = "test-meowdb"
_REGION = "us-east-1"


# ---------------------------------------------------------------------------
# Key helpers — pure string formatting, no I/O
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_wav_key_format():
    assert wav_key("abc-123") == "audio/wav/abc-123.wav"


@pytest.mark.unit
def test_mp3_key_format():
    assert mp3_key("abc-123") == "audio/mp3/abc-123.mp3"


@pytest.mark.unit
def test_photo_key_format():
    assert photo_key("fluffy.jpg") == "photos/fluffy.jpg"


# ---------------------------------------------------------------------------
# is_s3_enabled
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_is_s3_enabled_false_when_bucket_unset(monkeypatch):
    monkeypatch.setattr(config, "S3_BUCKET", None)
    assert is_s3_enabled() is False


@pytest.mark.unit
def test_is_s3_enabled_true_when_bucket_set(monkeypatch):
    monkeypatch.setattr(config, "S3_BUCKET", _BUCKET)
    assert is_s3_enabled() is True


# ---------------------------------------------------------------------------
# Moto fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def s3_bucket(monkeypatch):
    """Activate moto mock_aws, patch config for S3 mode, create test bucket."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", _REGION)
    monkeypatch.setattr(config, "S3_BUCKET", _BUCKET)
    monkeypatch.setattr(config, "S3_REGION", _REGION)
    monkeypatch.setattr(config, "S3_ACCESS_KEY_ID", None)
    monkeypatch.setattr(config, "S3_SECRET_ACCESS_KEY", None)
    monkeypatch.setattr(config, "S3_ENDPOINT_URL", None)

    with mock_aws():
        _reset_s3_client()
        boto3.client("s3", region_name=_REGION).create_bucket(Bucket=_BUCKET)
        yield _BUCKET
    _reset_s3_client()


# ---------------------------------------------------------------------------
# S3NotFoundError — missing key raises on head and download
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_download_missing_key_raises_s3_not_found(s3_bucket, tmp_path):
    with pytest.raises(S3NotFoundError):
        download_from_s3_sync("audio/wav/ghost.wav", tmp_path / "out.wav")


@pytest.mark.unit
def test_head_missing_key_raises_s3_not_found(s3_bucket):
    with pytest.raises(S3NotFoundError):
        asyncio.run(s3_head_object("audio/wav/ghost.wav"))


# ---------------------------------------------------------------------------
# Delete of missing key is a no-op
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_delete_missing_key_does_not_raise(s3_bucket):
    delete_from_s3_sync("audio/wav/ghost.wav")  # must not raise


# ---------------------------------------------------------------------------
# Upload / download / head round-trip
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_upload_download_roundtrip(s3_bucket, tmp_path):
    content = b"meow meow meow"
    src = tmp_path / "clip.wav"
    src.write_bytes(content)

    key = wav_key("roundtrip-id")
    upload_to_s3_sync(src, key)

    dest = tmp_path / "downloaded.wav"
    download_from_s3_sync(key, dest)

    assert dest.read_bytes() == content


@pytest.mark.unit
def test_head_object_returns_correct_size_and_etag(s3_bucket, tmp_path):
    content = b"a" * 1234
    src = tmp_path / "sized.wav"
    src.write_bytes(content)

    key = wav_key("head-test-id")
    upload_to_s3_sync(src, key)

    meta = asyncio.run(s3_head_object(key))

    assert meta["size"] == 1234
    assert "etag" in meta
    assert len(str(meta["etag"])) > 0


@pytest.mark.unit
def test_upload_delete_then_download_raises(s3_bucket, tmp_path):
    content = b"ephemeral"
    src = tmp_path / "temp.wav"
    src.write_bytes(content)

    key = wav_key("ephemeral-id")
    upload_to_s3_sync(src, key)
    delete_from_s3_sync(key)

    with pytest.raises(S3NotFoundError):
        download_from_s3_sync(key, tmp_path / "never.wav")


# ---------------------------------------------------------------------------
# Bucket misconfiguration: NoSuchBucket must not be swallowed as S3NotFoundError
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_nonexistent_bucket_propagates_client_error_not_s3_not_found(monkeypatch):
    """_is_not_found_error does not match NoSuchBucket; the ClientError re-raises."""
    import botocore.exceptions

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", _REGION)
    monkeypatch.setattr(config, "S3_BUCKET", "bucket-that-was-never-created")
    monkeypatch.setattr(config, "S3_REGION", _REGION)
    monkeypatch.setattr(config, "S3_ACCESS_KEY_ID", None)
    monkeypatch.setattr(config, "S3_SECRET_ACCESS_KEY", None)
    monkeypatch.setattr(config, "S3_ENDPOINT_URL", None)

    with mock_aws():
        _reset_s3_client()
        # Intentionally do NOT create any bucket
        with pytest.raises(botocore.exceptions.ClientError) as exc_info:
            asyncio.run(s3_head_object("audio/wav/probe.wav"))

        # Must be a bucket-level error, not silently converted to S3NotFoundError
        code = exc_info.value.response["Error"]["Code"]
        assert code not in ("404", "NoSuchKey"), (
            f"Expected NoSuchBucket/AccessDenied, got {code!r} — "
            "bucket misconfiguration should not be treated as a missing key"
        )
    _reset_s3_client()
