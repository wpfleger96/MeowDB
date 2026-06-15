from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response

from meowdb.api.models import MeowListResponse, MeowResponse, UpdateMeowRequest
from meowdb.api.streaming import safe_path
from meowdb.config import MP3_DIR, WAV_DIR

router = APIRouter()


def _meow_to_response(meow: dict) -> MeowResponse:  # type: ignore[type-arg]
    mp3_path = meow.get("mp3_path", "")
    wav_path = meow.get("wav_path", "")
    mp3_url = f"/api/audio/{meow['id']}" if mp3_path else None
    wav_url = f"/api/audio/{meow['id']}/wav" if wav_path else None
    return MeowResponse(
        id=meow["id"],
        timestamp=meow.get("timestamp") or "",
        duration_ms=meow["duration_ms"],
        labels=meow.get("labels") or [],
        play_count=meow.get("play_count") or 0,
        created_at=meow.get("created_at") or "",
        wav_url=wav_url,
        mp3_url=mp3_url,
        waveform_data=meow.get("waveform_data") or [],
        recorded_at=meow.get("recorded_at"),
        title=meow.get("title"),
    )


# /meows/random MUST be registered before /{id} — see Gotcha 2 in PLAN
@router.get("/meows/random", response_model=MeowResponse)
async def get_random_meow(request: Request) -> MeowResponse:
    db = request.app.state.db
    meow = db.get_random()
    if meow is None:
        raise HTTPException(status_code=404, detail="No meows in library")
    return _meow_to_response(meow)


@router.get("/meows", response_model=MeowListResponse)
async def list_meows(
    request: Request,
    sort: str = "newest",
    label: list[str] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> MeowListResponse:
    db = request.app.state.db
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    label_filter = label[0] if label else None
    rows = db.get_all(sort=sort, label_filter=label_filter, limit=limit, offset=offset)
    total = db.get_count(label_filter=label_filter)
    items = [_meow_to_response(m) for m in rows]
    return MeowListResponse(items=items, total=total, limit=limit, offset=offset)


@router.patch("/meows/{meow_id}", response_model=MeowResponse)
async def update_meow(
    meow_id: str,
    body: UpdateMeowRequest,
    request: Request,
) -> MeowResponse:
    db = request.app.state.db
    if body.labels is not None:
        if not db.update_labels(meow_id, body.labels):
            raise HTTPException(status_code=404, detail="Meow not found")
    update_fields = {}
    if body.title is not None:
        update_fields["title"] = body.title
    if body.recorded_at is not None:
        update_fields["recorded_at"] = body.recorded_at
    if update_fields:
        if not db.update_meow(meow_id, update_fields):
            raise HTTPException(status_code=404, detail="Meow not found")
    meow = db.get_by_id(meow_id)
    if meow is None:
        raise HTTPException(status_code=404, detail="Meow not found")
    return _meow_to_response(meow)


@router.delete("/meows/{meow_id}", status_code=204)
async def delete_meow(meow_id: str, request: Request) -> Response:
    db = request.app.state.db
    meow = db.get_by_id(meow_id)
    if meow is None:
        raise HTTPException(status_code=404, detail="Meow not found")

    wav_path_str = meow.get("wav_path", "")
    mp3_path_str = meow.get("mp3_path", "")
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

    db.delete(meow_id)
    return Response(status_code=204)


@router.post("/meows/{meow_id}/play", status_code=204)
async def play_meow(meow_id: str, request: Request) -> Response:
    db = request.app.state.db
    meow = db.get_by_id(meow_id)
    if meow is None:
        raise HTTPException(status_code=404, detail="Meow not found")
    db.increment_play_count(meow_id)
    return Response(status_code=204)
