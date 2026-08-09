from __future__ import annotations

import logging

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from meowdb.api.converters import photo_to_response
from meowdb.api.models import PhotoResponse
from meowdb.api.streaming import safe_path, stream_file, stream_s3_object
from meowdb.config import PHOTOS_DIR
from meowdb.storage import is_s3_enabled, photo_key

_logger = logging.getLogger(__name__)

router = APIRouter()

_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".heic": "image/heic",
    ".heif": "image/heif",
}


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

    filename = photo["filename"]
    media_type = _MEDIA_TYPES.get(Path(filename).suffix.lower(), "application/octet-stream")

    if is_s3_enabled():
        local_path = PHOTOS_DIR / filename
        # Migration fallback: photos have no path column, so local-file existence marks
        # an unmigrated photo that has not yet been moved to S3.
        if local_path.exists():
            try:
                local_path = safe_path(local_path, PHOTOS_DIR)
            except ValueError:
                raise HTTPException(status_code=403, detail="Access denied") from None
            stat = local_path.stat()
            etag = f'"{stat.st_mtime_ns}-{stat.st_size}"'
            return stream_file(
                local_path,
                request,
                media_type,
                extra_headers={"Cache-Control": "public, max-age=86400", "ETag": etag},
            )
        # ETag comes from the GET response inside stream_s3_object; no prior HEAD needed.
        return await stream_s3_object(
            photo_key(filename),
            request,
            media_type,
            extra_headers={"Cache-Control": "public, max-age=86400"},
        )

    path = PHOTOS_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Photo file not found on disk")

    try:
        path = safe_path(path, PHOTOS_DIR)
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied") from None

    stat = path.stat()
    etag = f'"{stat.st_mtime_ns}-{stat.st_size}"'
    return stream_file(
        path,
        request,
        media_type,
        extra_headers={"Cache-Control": "public, max-age=86400", "ETag": etag},
    )
