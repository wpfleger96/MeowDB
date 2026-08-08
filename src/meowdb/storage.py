from __future__ import annotations

import threading

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import TYPE_CHECKING

import boto3
import botocore.exceptions
import botocore.response

from starlette.concurrency import run_in_threadpool

from meowdb import config

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

_CHUNK_SIZE = 65536

_s3_client: S3Client | None = None
_s3_lock = threading.Lock()


class S3NotFoundError(Exception):
    """Raised when a requested S3 key does not exist."""


def is_s3_enabled() -> bool:
    """Return True when S3 mode is active (MEOWDB_S3_BUCKET is set)."""
    return bool(config.S3_BUCKET)


def wav_key(meow_id: str) -> str:
    return f"audio/wav/{meow_id}.wav"


def mp3_key(meow_id: str) -> str:
    return f"audio/mp3/{meow_id}.mp3"


def photo_key(filename: str) -> str:
    return f"photos/{filename}"


def get_s3_client() -> S3Client:
    """Return the module-level S3 client singleton, creating it on first call."""
    global _s3_client
    if _s3_client is None:
        with _s3_lock:
            if _s3_client is None:
                kwargs: dict[str, str] = {"region_name": config.S3_REGION}
                if config.S3_ENDPOINT_URL:
                    kwargs["endpoint_url"] = config.S3_ENDPOINT_URL
                if config.S3_ACCESS_KEY_ID:
                    kwargs["aws_access_key_id"] = config.S3_ACCESS_KEY_ID
                if config.S3_SECRET_ACCESS_KEY:
                    kwargs["aws_secret_access_key"] = config.S3_SECRET_ACCESS_KEY
                _s3_client = boto3.client("s3", **kwargs)  # type: ignore[call-overload]
    return _s3_client


def reset_s3_client() -> None:
    """Reset the S3 client singleton (for use in tests)."""
    global _s3_client
    with _s3_lock:
        _s3_client = None


def _is_not_found_error(exc: botocore.exceptions.ClientError) -> bool:
    code = exc.response["Error"]["Code"]
    return code in ("404", "NoSuchKey")


# ---------------------------------------------------------------------------
# Sync API (CLI callers)
# ---------------------------------------------------------------------------


def upload_to_s3_sync(local_path: Path, key: str) -> None:
    """Upload a local file to S3 under *key*."""
    client = get_s3_client()
    bucket = config.S3_BUCKET
    assert bucket is not None, "S3 not configured"
    client.upload_file(str(local_path), bucket, key)


def delete_from_s3_sync(key: str) -> None:
    """Delete *key* from S3; a missing key is not an error."""
    client = get_s3_client()
    bucket = config.S3_BUCKET
    assert bucket is not None, "S3 not configured"
    try:
        client.delete_object(Bucket=bucket, Key=key)
    except botocore.exceptions.ClientError as exc:
        if not _is_not_found_error(exc):
            raise


def download_from_s3_sync(key: str, local_path: Path) -> None:
    """Download *key* from S3 to *local_path*; raises S3NotFoundError if missing."""
    client = get_s3_client()
    bucket = config.S3_BUCKET
    assert bucket is not None, "S3 not configured"
    try:
        client.download_file(bucket, key, str(local_path))
    except botocore.exceptions.ClientError as exc:
        if _is_not_found_error(exc):
            raise S3NotFoundError(key) from exc
        raise


# ---------------------------------------------------------------------------
# Async API (FastAPI callers) — threadpool wrappers
# ---------------------------------------------------------------------------


async def upload_to_s3(local_path: Path, key: str) -> None:
    await run_in_threadpool(upload_to_s3_sync, local_path, key)


async def delete_from_s3(key: str) -> None:
    await run_in_threadpool(delete_from_s3_sync, key)


async def download_from_s3(key: str, local_path: Path) -> None:
    await run_in_threadpool(download_from_s3_sync, key, local_path)


async def s3_head_object(key: str) -> dict[str, int | str]:
    """Return {"size": int, "etag": str} for *key*; raises S3NotFoundError on 404/NoSuchKey."""

    def _head() -> dict[str, int | str]:
        client = get_s3_client()
        bucket = config.S3_BUCKET
        assert bucket is not None, "S3 not configured"
        try:
            resp = client.head_object(Bucket=bucket, Key=key)
        except botocore.exceptions.ClientError as exc:
            if _is_not_found_error(exc):
                raise S3NotFoundError(key) from exc
            raise
        return {"size": resp["ContentLength"], "etag": resp["ETag"]}

    return await run_in_threadpool(_head)


async def stream_s3_range(key: str, start: int, end: int) -> AsyncGenerator[bytes]:
    """Async generator that streams bytes [start, end] (inclusive) from S3."""

    def _get_body() -> botocore.response.StreamingBody:
        client = get_s3_client()
        bucket = config.S3_BUCKET
        assert bucket is not None, "S3 not configured"
        resp = client.get_object(Bucket=bucket, Key=key, Range=f"bytes={start}-{end}")
        return resp["Body"]

    body = await run_in_threadpool(_get_body)
    try:
        while True:
            chunk: bytes = await run_in_threadpool(body.read, _CHUNK_SIZE)
            if not chunk:
                break
            yield chunk
    finally:
        await run_in_threadpool(body.close)
