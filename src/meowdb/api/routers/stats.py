from __future__ import annotations

from fastapi import APIRouter, Request

from meowdb.api.models import LabelResponse, SoundSummary, StatsResponse

router = APIRouter()


def _to_summary(m: dict) -> SoundSummary:  # type: ignore[type-arg]
    mp3_url = f"/api/audio/{m['id']}" if m.get("mp3_path") else None
    return SoundSummary(**m, mp3_url=mp3_url)


@router.get("/stats", response_model=StatsResponse)
async def get_stats(request: Request) -> StatsResponse:
    db = request.app.state.db
    data = db.get_stats()
    summary_lists = {
        "most_played": [_to_summary(m) for m in data["most_played"]],
        "recent": [_to_summary(m) for m in data["recent"]],
        "most_upvoted": [_to_summary(m) for m in data.get("most_upvoted", [])],
        "most_downvoted": [_to_summary(m) for m in data.get("most_downvoted", [])],
    }
    return StatsResponse(**{**data, **summary_lists})


@router.get("/labels", response_model=list[LabelResponse])
async def get_labels(request: Request) -> list[LabelResponse]:
    db = request.app.state.db
    rows = db.get_labels()
    return [LabelResponse(**row) for row in rows]
