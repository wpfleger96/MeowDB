from __future__ import annotations

import logging

from collections.abc import AsyncGenerator
from pathlib import Path

from fastapi import HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from meowdb import storage
from meowdb.storage import S3InvalidRangeError, S3NotFoundError

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 65536  # 64 KB — local file reads and upload buffering


def safe_path(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"Path escapes root: {path}")
    return resolved


async def save_upload(file: UploadFile, dest: Path, max_bytes: int, detail: str) -> int:
    total = 0
    with dest.open("wb") as f:
        while True:
            chunk = await file.read(_CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise HTTPException(status_code=413, detail=detail)
            f.write(chunk)
    return total


async def _stream_range(path: Path, start: int, end: int) -> AsyncGenerator[bytes]:
    with path.open("rb") as f:
        f.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = f.read(min(_CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def _parse_range(
    range_header: str | None,
    file_size: int,
) -> tuple[int, int, bool]:
    """Parse a Range header and return (start, end, is_range_request).

    Requires file size to resolve suffix ranges and clamp end.
    Raises HTTPException(416) on invalid or unsatisfiable ranges.
    """
    if not range_header:
        return 0, file_size - 1, False

    range_val = range_header.strip().removeprefix("bytes=")
    parts = range_val.split("-", maxsplit=1)
    try:
        suffix_only = len(parts) > 1 and not parts[0] and parts[1]
        if suffix_only:
            # RFC 9110 suffix-range: bytes=-N means last N bytes
            n = int(parts[1])
            if n == 0:
                raise HTTPException(status_code=416, detail="Range not satisfiable")
            start = max(0, file_size - n)
            end = file_size - 1
        else:
            start = int(parts[0]) if parts[0] else 0
            end = int(parts[1]) if len(parts) > 1 and parts[1] else file_size - 1
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=416, detail="Invalid Range header") from None

    end = min(end, file_size - 1)
    if start < 0 or start > end:
        raise HTTPException(status_code=416, detail="Range not satisfiable")

    return start, end, True


def _validate_range_header(range_header: str | None) -> str | None:
    """Syntactically validate a Range header without knowing file size.

    Returns the header value verbatim when valid, or None when absent.
    Raises HTTPException(416) for malformed specs or obviously unsatisfiable
    ranges (bytes=-0, start>end). Suffix ranges (bytes=-N, N>0) and open-ended
    ranges (bytes=N-) are accepted and forwarded to S3 verbatim so S3 applies
    the size-dependent clamping itself.
    """
    if not range_header:
        return None

    range_val = range_header.strip()
    if not range_val.startswith("bytes="):
        raise HTTPException(status_code=416, detail="Invalid Range header")

    spec = range_val.removeprefix("bytes=")
    parts = spec.split("-", maxsplit=1)
    if len(parts) != 2:
        raise HTTPException(status_code=416, detail="Invalid Range header")

    raw_start, raw_end = parts[0], parts[1]
    try:
        if not raw_start:
            # Suffix range: bytes=-N
            if not raw_end:
                raise HTTPException(status_code=416, detail="Invalid Range header")
            n = int(raw_end)
            if n == 0:
                raise HTTPException(status_code=416, detail="Range not satisfiable")
        else:
            start = int(raw_start)
            if start < 0:
                raise HTTPException(status_code=416, detail="Range not satisfiable")
            if raw_end:
                end = int(raw_end)
                if start > end:
                    raise HTTPException(status_code=416, detail="Range not satisfiable")
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=416, detail="Invalid Range header") from None

    return range_val


def stream_file(
    path: Path,
    request: Request,
    media_type: str,
    extra_headers: dict[str, str] | None = None,
) -> StreamingResponse:
    file_size = path.stat().st_size
    start, end, is_range = _parse_range(request.headers.get("range"), file_size)
    content_length = end - start + 1

    headers: dict[str, str] = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(content_length),
    }
    if is_range:
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
    if extra_headers:
        headers.update(extra_headers)

    return StreamingResponse(
        _stream_range(path, start, end),
        status_code=206 if is_range else 200,
        media_type=media_type,
        headers=headers,
    )


async def stream_s3_object(
    key: str,
    request: Request,
    media_type: str,
    extra_headers: dict[str, str] | None = None,
) -> StreamingResponse:
    """Stream an S3 object in a single GET request, honouring RFC 9110 Range requests.

    Issues exactly one S3 API call per response. Content-Range, Content-Length,
    and ETag come directly from the GET response — no prior HEAD is needed.
    extra_headers may override any header including ETag.
    """
    range_spec = _validate_range_header(request.headers.get("range"))
    try:
        result = await storage.get_s3_object(key, range_spec)
    except S3NotFoundError:
        raise HTTPException(status_code=404, detail="File not found") from None
    except S3InvalidRangeError:
        raise HTTPException(status_code=416, detail="Range not satisfiable") from None

    headers: dict[str, str] = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(result.content_length),
        "ETag": result.etag,
    }
    if result.content_range is not None:
        headers["Content-Range"] = result.content_range
    if extra_headers:
        headers.update(extra_headers)

    return StreamingResponse(
        storage.stream_s3_body(result.body),
        status_code=result.status_code,
        media_type=media_type,
        headers=headers,
    )
