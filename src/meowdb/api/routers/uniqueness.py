from __future__ import annotations

import time

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from starlette.concurrency import run_in_threadpool

from meowdb.api.auth import require_auth
from meowdb.api.models import RecalculateResponse
from meowdb.similarity import update_library_uniqueness

router = APIRouter()


def _run_recalculate(db: Any, force: bool = False) -> int:
    """Delegate fingerprint extraction and uniqueness recomputation to update_library_uniqueness."""
    if force:
        all_ids = [r["id"] for r in db.get_all_wav_paths()]
        update_library_uniqueness(db, [], force=True)
        return len(all_ids)
    else:
        all_fps = db.get_all_fingerprints()
        missing_ids = [r["id"] for r in db.get_all_wav_paths() if r["id"] not in all_fps]
        update_library_uniqueness(db, missing_ids, fingerprints=all_fps)
        return len(missing_ids)


@router.post("/uniqueness/recalculate", response_model=RecalculateResponse)
async def recalculate_uniqueness(
    request: Request,
    _: None = Depends(require_auth),
    force: bool = Query(False, description="Re-extract all fingerprints even if already computed"),
) -> RecalculateResponse:
    """Recompute MFCC fingerprints and all uniqueness scores.

    By default only extracts fingerprints for sounds that don't have one yet.
    Pass ?force=true to re-extract all fingerprints (useful after fixing file issues).
    """
    db = request.app.state.db
    t0 = time.monotonic()
    updated_count = await run_in_threadpool(_run_recalculate, db, force)
    return RecalculateResponse(
        updated_count=updated_count,
        elapsed_seconds=round(time.monotonic() - t0, 2),
    )
