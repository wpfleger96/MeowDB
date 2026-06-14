from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from meowdb.api.streaming import safe_path, stream_file
from meowdb.config import MP3_DIR

router = APIRouter()


@router.get("/audio/{meow_id}")
async def stream_audio(meow_id: str, request: Request) -> StreamingResponse:
    db = request.app.state.db
    meow = db.get_by_id(meow_id)
    if meow is None:
        raise HTTPException(status_code=404, detail="Meow not found")

    mp3_path_str = meow.get("mp3_path", "")
    if not mp3_path_str:
        raise HTTPException(status_code=404, detail="Audio file not available")

    path = Path(mp3_path_str)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found on disk")

    try:
        path = safe_path(path, MP3_DIR)
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied") from None

    return stream_file(path, request, "audio/mpeg")
