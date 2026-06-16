from __future__ import annotations

import logging
import time

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from starlette.concurrency import run_in_threadpool

from meowdb.api.auth import require_auth
from meowdb.api.models import RecalculateResponse
from meowdb.similarity import MeowSimilarity

router = APIRouter()
logger = logging.getLogger(__name__)

_similarity = MeowSimilarity()


def _run_recalculate(db: Any, force: bool = False) -> int:
    """Extract fingerprints (missing ones, or all if force=True), recompute all scores."""
    all_rows = db.get_all_wav_paths()
    existing_fps = db.get_all_fingerprints()

    updated = 0
    for row in all_rows:
        meow_id = row["id"]
        if force or meow_id not in existing_fps:
            try:
                fp = _similarity.extract_fingerprint(Path(row["wav_path"]))
                db.update_fingerprint(meow_id, fp)
                existing_fps[meow_id] = fp
                updated += 1
            except Exception as exc:
                logger.warning("Failed to extract fingerprint for %s: %s", meow_id, exc)

    if existing_fps:
        scores = _similarity.compute_uniqueness_scores(existing_fps)
        db.update_uniqueness_scores_bulk(scores)

    return updated


@router.post("/uniqueness/recalculate", response_model=RecalculateResponse)
async def recalculate_uniqueness(
    request: Request,
    _: None = Depends(require_auth),
    force: bool = Query(False, description="Re-extract all fingerprints even if already computed"),
) -> RecalculateResponse:
    """Recompute MFCC fingerprints and all uniqueness scores.

    By default only extracts fingerprints for meows that don't have one yet.
    Pass ?force=true to re-extract all fingerprints (useful after fixing file issues).
    """
    db = request.app.state.db
    t0 = time.monotonic()
    updated_count = await run_in_threadpool(_run_recalculate, db, force)
    return RecalculateResponse(
        updated_count=updated_count,
        elapsed_seconds=round(time.monotonic() - t0, 2),
    )
