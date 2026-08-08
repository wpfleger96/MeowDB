from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from meowdb.api.auth import require_auth
from meowdb.api.models import FeedbackRequest, SoundListResponse, SoundResponse, UpdateMeowRequest
from meowdb.api.streaming import safe_path
from meowdb.config import MP3_DIR, WAV_DIR
from meowdb.similarity import update_library_uniqueness

router = APIRouter()


def _sound_to_response(sound: dict) -> SoundResponse:  # type: ignore[type-arg]
    mp3_path = sound.get("mp3_path", "")
    wav_path = sound.get("wav_path", "")
    mp3_url = f"/api/audio/{sound['id']}" if mp3_path else None
    wav_url = f"/api/audio/{sound['id']}/wav" if wav_path else None
    return SoundResponse(
        id=sound["id"],
        timestamp=sound.get("timestamp") or "",
        duration_ms=sound["duration_ms"],
        labels=sound.get("labels") or [],
        play_count=sound.get("play_count") or 0,
        upvote_count=sound.get("upvote_count") or 0,
        downvote_count=sound.get("downvote_count") or 0,
        created_at=sound.get("created_at") or "",
        wav_url=wav_url,
        mp3_url=mp3_url,
        waveform_data=sound.get("waveform_data") or [],
        recorded_at=sound.get("recorded_at"),
        title=sound.get("title"),
        animal_uniqueness_score=sound.get("animal_uniqueness_score"),
        species_uniqueness_score=sound.get("species_uniqueness_score"),
        animal_id=sound["animal_id"],
        animal_name=sound.get("animal_name"),
        animal_species=sound.get("animal_species"),
        photo=None,
    )


# /sounds/random MUST be registered before /{id} — see Gotcha 2 in PLAN
@router.get("/sounds/random", response_model=SoundResponse)
async def get_random_sound(
    request: Request,
    exclude: str | None = None,
    exclude_photo: str | None = None,
) -> SoundResponse:
    db = request.app.state.db
    sound = db.get_random_sound(exclude_id=exclude)
    if sound is None:
        raise HTTPException(status_code=404, detail="No sounds in library")
    response = _sound_to_response(sound)
    photo_row = db.get_random_photo_for_animal(sound["animal_id"], exclude_id=exclude_photo)
    if photo_row is not None:
        from meowdb.api.routers.photos import photo_to_response

        response = response.model_copy(update={"photo": photo_to_response(photo_row)})
    return response


@router.get("/sounds", response_model=SoundListResponse)
async def list_sounds(
    request: Request,
    sort: str = "newest",
    label: list[str] | None = None,
    animal_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> SoundListResponse:
    db = request.app.state.db
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    label_filter = label[0] if label else None
    rows = db.get_all(
        sort=sort, label_filter=label_filter, animal_id=animal_id, limit=limit, offset=offset
    )
    total = db.get_count(label_filter=label_filter, animal_id=animal_id)
    items = [_sound_to_response(s) for s in rows]
    return SoundListResponse(items=items, total=total, limit=limit, offset=offset)


@router.patch("/sounds/{sound_id}", response_model=SoundResponse)
async def update_sound(
    sound_id: str,
    body: UpdateMeowRequest,
    request: Request,
    _: None = Depends(require_auth),
) -> SoundResponse:
    db = request.app.state.db
    if body.labels is not None:
        if not db.update_labels(sound_id, body.labels):
            raise HTTPException(status_code=404, detail="Sound not found")
    update_fields = {}
    if body.title is not None:
        update_fields["title"] = body.title
    if body.recorded_at is not None:
        update_fields["recorded_at"] = body.recorded_at
    if update_fields:
        if not db.update_sound(sound_id, update_fields):
            raise HTTPException(status_code=404, detail="Sound not found")
    sound = db.get_by_id(sound_id)
    if sound is None:
        raise HTTPException(status_code=404, detail="Sound not found")
    return _sound_to_response(sound)


@router.delete("/sounds/{sound_id}", status_code=204)
async def delete_sound(
    sound_id: str, request: Request, _: None = Depends(require_auth)
) -> Response:
    db = request.app.state.db
    sound = db.get_by_id(sound_id)
    if sound is None:
        raise HTTPException(status_code=404, detail="Sound not found")

    wav_path_str = sound.get("wav_path", "")
    mp3_path_str = sound.get("mp3_path", "")
    if wav_path_str:
        try:
            Path(safe_path(Path(wav_path_str), WAV_DIR)).unlink(missing_ok=True)
        except ValueError:
            pass
    if mp3_path_str:
        try:
            Path(safe_path(Path(mp3_path_str), MP3_DIR)).unlink(missing_ok=True)
        except ValueError:
            pass

    db.delete(sound_id)
    await run_in_threadpool(update_library_uniqueness, db, [])
    return Response(status_code=204)


@router.post("/sounds/{sound_id}/play", status_code=204)
async def play_sound(sound_id: str, request: Request) -> Response:
    db = request.app.state.db
    if not db.increment_play_count(sound_id):
        raise HTTPException(status_code=404, detail="Sound not found")
    return Response(status_code=204)


@router.post("/sounds/{sound_id}/feedback", status_code=204)
async def feedback_sound(sound_id: str, body: FeedbackRequest, request: Request) -> Response:
    db = request.app.state.db
    is_upvote = body.vote == "up"
    if body.previous and body.previous != body.vote:
        ok = db.switch_feedback(sound_id, is_upvote=is_upvote)
    else:
        ok = db.record_feedback(sound_id, is_upvote=is_upvote)
    if not ok:
        raise HTTPException(status_code=404, detail="Sound not found")
    return Response(status_code=204)
