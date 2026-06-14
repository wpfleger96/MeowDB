from __future__ import annotations

import logging

from collections.abc import AsyncGenerator
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 65536


def safe_path(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"Path escapes root: {path}")
    return resolved


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


def stream_file(path: Path, request: Request, media_type: str) -> StreamingResponse:
    file_size = path.stat().st_size
    range_header = request.headers.get("range")

    if range_header:
        range_val = range_header.strip().removeprefix("bytes=")
        parts = range_val.split("-", maxsplit=1)
        try:
            start = int(parts[0]) if parts[0] else 0
            end = int(parts[1]) if len(parts) > 1 and parts[1] else file_size - 1
        except ValueError:
            raise HTTPException(status_code=416, detail="Invalid Range header") from None
        end = min(end, file_size - 1)
        if start < 0 or start > end:
            raise HTTPException(status_code=416, detail="Range not satisfiable")
        content_length = end - start + 1
        headers = {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(content_length),
        }
        return StreamingResponse(
            _stream_range(path, start, end),
            status_code=206,
            media_type=media_type,
            headers=headers,
        )

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(file_size),
    }
    return StreamingResponse(
        _stream_range(path, 0, file_size - 1),
        status_code=200,
        media_type=media_type,
        headers=headers,
    )
