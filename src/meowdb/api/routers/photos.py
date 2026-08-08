from __future__ import annotations

import logging

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from meowdb.api.models import PhotoResponse
from meowdb.api.streaming import safe_path, stream_file
from meowdb.config import PHOTOS_DIR

_logger = logging.getLogger(__name__)

router = APIRouter()

_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def _cache_version(dt_str: str) -> int:
    try:
        return int(datetime.fromisoformat(dt_str).replace(tzinfo=UTC).timestamp())
    except (ValueError, TypeError):
        return 0


def photo_to_response(photo: dict) -> PhotoResponse:  # type: ignore[type-arg]
    v = _cache_version(photo.get("updated_at") or photo.get("created_at", ""))
    return PhotoResponse(
        id=photo["id"],
        filename=photo["filename"],
        created_at=photo.get("created_at", ""),
        updated_at=photo.get("updated_at") or "",
        image_url=f"/api/photos/{photo['id']}/image?v={v}",
        is_default=bool(photo.get("is_default", False)),
        animal_id=photo.get("animal_id", ""),
    )


@router.get("/photos/random", response_model=PhotoResponse)
async def get_random_photo(request: Request, exclude: str | None = None) -> PhotoResponse:
    db = request.app.state.db
    photo = db.get_random_photo(exclude_id=exclude)
    if photo is None:
        raise HTTPException(status_code=404, detail="No photos available")
    return photo_to_response(photo)


@router.get("/photos/{photo_id}/image")
async def serve_photo(photo_id: str, request: Request) -> StreamingResponse:
    db = request.app.state.db
    photo = db.get_photo(photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")

    path = PHOTOS_DIR / photo["filename"]
    if not path.exists():
        raise HTTPException(status_code=404, detail="Photo file not found on disk")

    try:
        path = safe_path(path, PHOTOS_DIR)
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied") from None

    media_type = _MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
    stat = path.stat()
    etag = f'"{stat.st_mtime_ns}-{stat.st_size}"'
    return stream_file(
        path,
        request,
        media_type,
        extra_headers={"Cache-Control": "public, max-age=86400", "ETag": etag},
    )
