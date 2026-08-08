from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from meowdb.api.streaming import safe_path, stream_file, stream_s3_object
from meowdb.config import MP3_DIR, WAV_DIR
from meowdb.storage import is_s3_enabled, is_s3_key, mp3_key, wav_key

router = APIRouter()


@router.get("/audio/{meow_id}/wav")
async def stream_wav_audio(meow_id: str, request: Request) -> StreamingResponse:
    db = request.app.state.db
    meow = db.get_by_id(meow_id)
    if meow is None:
        raise HTTPException(status_code=404, detail="Meow not found")

    wav_path_str = meow.get("wav_path", "")
    if not wav_path_str:
        raise HTTPException(status_code=404, detail="WAV file not available")

    if is_s3_enabled() and is_s3_key(wav_path_str):
        return await stream_s3_object(wav_key(meow_id), request, "audio/wav")

    path = Path(wav_path_str)
    if not path.exists():
        raise HTTPException(status_code=404, detail="WAV file not found on disk")

    try:
        path = safe_path(path, WAV_DIR)
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied") from None

    return stream_file(path, request, "audio/wav")


@router.get("/audio/{meow_id}")
async def stream_audio(meow_id: str, request: Request) -> StreamingResponse:
    db = request.app.state.db
    meow = db.get_by_id(meow_id)
    if meow is None:
        raise HTTPException(status_code=404, detail="Meow not found")

    mp3_path_str = meow.get("mp3_path", "")
    if not mp3_path_str:
        raise HTTPException(status_code=404, detail="Audio file not available")

    if is_s3_enabled() and is_s3_key(mp3_path_str):
        return await stream_s3_object(mp3_key(meow_id), request, "audio/mpeg")

    path = Path(mp3_path_str)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found on disk")

    try:
        path = safe_path(path, MP3_DIR)
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied") from None

    return stream_file(path, request, "audio/mpeg")
