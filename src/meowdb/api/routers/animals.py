from __future__ import annotations

import logging
import os
import tempfile
import uuid

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from PIL import Image, ImageOps
from starlette.concurrency import run_in_threadpool

from meowdb.api.auth import require_auth
from meowdb.api.converters import photo_to_response
from meowdb.api.models import (
    AnimalListResponse,
    AnimalResponse,
    CreateAnimalRequest,
    PhotoEditRequest,
    PhotoListResponse,
    PhotoResponse,
)
from meowdb.api.streaming import safe_path, save_upload
from meowdb.config import MP3_DIR, PHOTOS_DIR, WAV_DIR
from meowdb.photos import optimize_photo

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/animals", tags=["animals"])

_MAX_PHOTO_BYTES = 20 * 1024 * 1024
_ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def _animal_to_response(animal: dict) -> AnimalResponse:  # type: ignore[type-arg]
    return AnimalResponse(
        id=animal["id"],
        name=animal["name"],
        species=animal["species"],
        created_at=animal["created_at"],
        sound_count=animal.get("sound_count", 0),
        photo_count=animal.get("photo_count", 0),
    )


@router.get("", response_model=AnimalListResponse)
async def list_animals(request: Request) -> AnimalListResponse:
    db = request.app.state.db
    animals = db.get_animals()
    return AnimalListResponse(items=[_animal_to_response(a) for a in animals])


@router.post("", response_model=AnimalResponse, status_code=201)
async def create_animal(
    body: CreateAnimalRequest,
    request: Request,
    _: None = Depends(require_auth),
) -> AnimalResponse:
    if not body.name or not body.name.strip():
        raise HTTPException(status_code=400, detail="name must not be empty")
    if not body.species or not body.species.strip():
        raise HTTPException(status_code=400, detail="species must not be empty")

    db = request.app.state.db
    animal_id = db.add_animal(body.name.strip(), body.species.strip())
    animal = db.get_animal(animal_id)
    return _animal_to_response(animal)


@router.delete("/{animal_id}", status_code=204)
async def delete_animal(
    animal_id: str,
    request: Request,
    _: None = Depends(require_auth),
) -> None:
    db = request.app.state.db
    result = db.delete_animal(animal_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Animal not found")

    for audio_path in result.get("audio_paths", []):
        p = Path(audio_path)
        base = MP3_DIR if p.suffix.lower() == ".mp3" else WAV_DIR
        try:
            safe_path(p, base).unlink(missing_ok=True)
        except ValueError:
            _logger.warning("Skipping out-of-bounds audio file %s", audio_path)
        except OSError:
            _logger.warning("Failed to remove audio file %s", audio_path)

    for photo_filename in result.get("photo_filenames", []):
        try:
            safe_path(PHOTOS_DIR / photo_filename, PHOTOS_DIR).unlink(missing_ok=True)
        except ValueError:
            _logger.warning("Skipping out-of-bounds photo file %s", photo_filename)
        except OSError:
            _logger.warning("Failed to remove photo file %s", photo_filename)


@router.get("/{animal_id}/photos", response_model=PhotoListResponse)
async def list_animal_photos(animal_id: str, request: Request) -> PhotoListResponse:
    db = request.app.state.db
    if not db.animal_exists(animal_id):
        raise HTTPException(status_code=404, detail="Animal not found")
    photos = db.get_photos(animal_id=animal_id)
    return PhotoListResponse(items=[photo_to_response(p) for p in photos])


@router.post("/{animal_id}/photos", response_model=PhotoResponse, status_code=201)
async def upload_animal_photo(
    animal_id: str,
    request: Request,
    file: UploadFile,
    _: None = Depends(require_auth),
) -> PhotoResponse:
    db = request.app.state.db
    if not db.animal_exists(animal_id):
        raise HTTPException(status_code=404, detail="Animal not found")

    source_filename = file.filename or "photo"
    suffix = Path(source_filename).suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail=f"Unsupported image type: {suffix!r}")

    PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    photo_id = str(uuid.uuid4())
    dest_filename = f"{photo_id}{suffix}"
    dest_path = PHOTOS_DIR / dest_filename

    try:
        await save_upload(file, dest_path, _MAX_PHOTO_BYTES, "Photo exceeds 20 MB limit")
    except HTTPException:
        dest_path.unlink(missing_ok=True)
        raise

    try:
        optimized_path = optimize_photo(dest_path)
        dest_filename = optimized_path.name
        if dest_path != optimized_path:
            dest_path.unlink(missing_ok=True)
    except Exception:
        _logger.warning("Photo optimization failed for %s, using original", dest_filename)

    db.add_photo(dest_filename, animal_id, photo_id=photo_id)
    photo = db.get_photo(photo_id)
    return photo_to_response(photo)


@router.get("/{animal_id}/photos/random", response_model=PhotoResponse)
async def get_random_animal_photo(
    animal_id: str,
    request: Request,
    exclude: str | None = None,
) -> PhotoResponse:
    db = request.app.state.db
    if db.get_animal(animal_id) is None:
        raise HTTPException(status_code=404, detail="Animal not found")
    photo = db.get_random_photo_for_animal(animal_id, exclude_id=exclude)
    if photo is None:
        raise HTTPException(status_code=404, detail="No photos available for this animal")
    return photo_to_response(photo)


@router.delete("/{animal_id}/photos/{photo_id}", status_code=204)
async def delete_animal_photo(
    animal_id: str,
    photo_id: str,
    request: Request,
    _: None = Depends(require_auth),
) -> None:
    db = request.app.state.db
    photo = db.get_photo(photo_id)
    if photo is None or photo.get("animal_id") != animal_id:
        raise HTTPException(status_code=404, detail="Photo not found")

    path = PHOTOS_DIR / photo["filename"]
    if path.exists():
        try:
            safe_path(path, PHOTOS_DIR)
            path.unlink(missing_ok=True)
        except ValueError:
            pass

    db.delete_photo(photo_id)


def _apply_edit(path: Path, body: PhotoEditRequest) -> tuple[Path, str | None]:
    """Returns (final_path, new_filename_if_changed)."""
    with Image.open(path) as raw:
        img = ImageOps.exif_transpose(raw)
        if body.action == "rotate":
            method = (
                Image.Transpose.ROTATE_270 if body.direction == "cw" else Image.Transpose.ROTATE_90
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
            w, h = img.size
            left = round(body.x * w)  # type: ignore[operator]
            upper = round(body.y * h)  # type: ignore[operator]
            right = round((body.x + body.width) * w)  # type: ignore[operator]
            lower = round((body.y + body.height) * h)  # type: ignore[operator]
            result = img.crop((left, upper, right, lower))

    if path.suffix.lower() != ".webp":
        new_path = path.with_suffix(".webp")
        result.save(new_path, format="WEBP", quality=85)
        path.unlink(missing_ok=True)
        return new_path, new_path.name
    else:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".webp", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        result.save(tmp_path, format="WEBP", quality=85)
        os.replace(tmp_path, path)
        return path, None


@router.post("/{animal_id}/photos/{photo_id}/edit", response_model=PhotoResponse)
async def edit_animal_photo(
    animal_id: str,
    photo_id: str,
    body: PhotoEditRequest,
    request: Request,
    _: None = Depends(require_auth),
) -> PhotoResponse:
    db = request.app.state.db
    photo = db.get_photo(photo_id)
    if photo is None or photo.get("animal_id") != animal_id:
        raise HTTPException(status_code=404, detail="Photo not found")

    path = PHOTOS_DIR / photo["filename"]
    if not path.exists():
        raise HTTPException(status_code=404, detail="Photo file not found on disk")

    try:
        path = safe_path(path, PHOTOS_DIR)
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied") from None

    try:
        _final_path, new_filename = await run_in_threadpool(_apply_edit, path, body)
    except (OSError, ValueError) as exc:
        _logger.warning("Photo edit failed for %s: %s", photo_id, exc)
        raise HTTPException(status_code=500, detail="Failed to edit photo") from exc

    if new_filename is not None:
        db.update_photo_filename(photo_id, new_filename)
    else:
        db.touch_photo(photo_id)
    return photo_to_response(db.get_photo(photo_id))
