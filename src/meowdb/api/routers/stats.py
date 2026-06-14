from __future__ import annotations

from fastapi import APIRouter, Request

from meowdb.api.models import LabelResponse, MeowSummary, StatsResponse

router = APIRouter()


@router.get("/stats", response_model=StatsResponse)
async def get_stats(request: Request) -> StatsResponse:
    db = request.app.state.db
    data = db.get_stats()
    return StatsResponse(
        total_meows=data["total_meows"],
        total_duration_ms=data["total_duration_ms"],
        avg_duration_ms=data["avg_duration_ms"],
        most_played=[MeowSummary(**m) for m in data["most_played"]],
        recent=[MeowSummary(**m) for m in data["recent"]],
        label_counts=data["label_counts"],
    )


@router.get("/labels", response_model=list[LabelResponse])
async def get_labels(request: Request) -> list[LabelResponse]:
    db = request.app.state.db
    rows = db.get_labels()
    return [LabelResponse(**row) for row in rows]
