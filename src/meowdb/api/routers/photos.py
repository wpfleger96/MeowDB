from __future__ import annotations

import uuid

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from meowdb.api.auth import require_auth
from meowdb.api.models import PhotoListResponse, PhotoResponse
from meowdb.api.streaming import safe_path, stream_file
from meowdb.config import PHOTOS_DIR

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
    return stream_file(path, request, media_type)


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
