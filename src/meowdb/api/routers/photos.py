from __future__ import annotations

import logging
import uuid

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from PIL import Image

from meowdb.api.auth import require_auth
from meowdb.api.models import PhotoEditRequest, PhotoListResponse, PhotoResponse
from meowdb.api.streaming import safe_path, stream_file
from meowdb.config import PHOTOS_DIR
from meowdb.photos import optimize_photo

_logger = logging.getLogger(__name__)

router = APIRouter()

_MAX_PHOTO_BYTES = 20 * 1024 * 1024
_ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def _photo_to_response(photo: dict) -> PhotoResponse:  # type: ignore[type-arg]
    return PhotoResponse(
        id=photo["id"],
        filename=photo["filename"],
        created_at=photo.get("created_at", ""),
        image_url=f"/api/photos/{photo['id']}/image",
        is_default=bool(photo.get("is_default", False)),
    )


@router.get("/photos", response_model=PhotoListResponse)
async def list_photos(request: Request) -> PhotoListResponse:
    db = request.app.state.db
    photos = db.get_photos()
    return PhotoListResponse(items=[_photo_to_response(p) for p in photos])


@router.get("/photos/random", response_model=PhotoResponse)
async def get_random_photo(request: Request, exclude: str | None = None) -> PhotoResponse:
    db = request.app.state.db
    photo = db.get_random_photo(exclude_id=exclude)
    if photo is None:
        raise HTTPException(status_code=404, detail="No photos available")
    return _photo_to_response(photo)


@router.post("/photos", response_model=PhotoResponse, status_code=201)
async def upload_photo(
    request: Request,
    file: UploadFile,
    _: None = Depends(require_auth),
) -> PhotoResponse:
    db = request.app.state.db

    source_filename = file.filename or "photo"
    suffix = Path(source_filename).suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail=f"Unsupported image type: {suffix!r}")

    PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    photo_id = str(uuid.uuid4())
    dest_filename = f"{photo_id}{suffix}"
    dest_path = PHOTOS_DIR / dest_filename

    total = 0
    with dest_path.open("wb") as dest:
        while True:
            chunk = await file.read(65536)
            if not chunk:
                break
            total += len(chunk)
            if total > _MAX_PHOTO_BYTES:
                dest_path.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="Photo exceeds 20 MB limit")
            dest.write(chunk)

    try:
        optimized_path = optimize_photo(dest_path)
        dest_filename = optimized_path.name
        if dest_path != optimized_path:
            dest_path.unlink(missing_ok=True)
    except Exception:
        _logger.warning("Photo optimization failed for %s, using original", dest_filename)

    db.add_photo(dest_filename, photo_id=photo_id)
    photo = db.get_photo(photo_id)
    return _photo_to_response(photo)


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


@router.delete("/photos/{photo_id}", status_code=204)
async def delete_photo(
    photo_id: str,
    request: Request,
    _: None = Depends(require_auth),
) -> None:
    db = request.app.state.db
    photo = db.get_photo(photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")

    path = PHOTOS_DIR / photo["filename"]
    if path.exists():
        try:
            safe_path(path, PHOTOS_DIR)
            path.unlink(missing_ok=True)
        except ValueError:
            pass

    db.delete_photo(photo_id)


@router.post("/photos/{photo_id}/edit", response_model=PhotoResponse)
async def edit_photo(
    photo_id: str,
    body: PhotoEditRequest,
    request: Request,
    _: None = Depends(require_auth),
) -> PhotoResponse:
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

    try:
        with Image.open(path) as img:
            if body.action == "rotate":
                method = (
                    Image.Transpose.ROTATE_270
                    if body.direction == "cw"
                    else Image.Transpose.ROTATE_90
                )
                result = img.transpose(method)
            elif body.action == "flip":
                method = (
                    Image.Transpose.FLIP_LEFT_RIGHT
                    if body.axis == "horizontal"
                    else Image.Transpose.FLIP_TOP_BOTTOM
                )
                result = img.transpose(method)
            else:  # crop
                assert body.x is not None and body.y is not None
                assert body.width is not None and body.height is not None
                w, h = img.size
                left = int(body.x * w)
                upper = int(body.y * h)
                right = int((body.x + body.width) * w)
                lower = int((body.y + body.height) * h)
                result = img.crop((left, upper, right, lower))
            result.save(path, format="WEBP", quality=85)
    except Exception as exc:
        _logger.warning("Photo edit failed for %s: %s", photo_id, exc)
        raise HTTPException(status_code=500, detail="Failed to edit photo") from exc

    photo = db.get_photo(photo_id)
    return _photo_to_response(photo)
