from __future__ import annotations

import logging
import os
import shutil

from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from meowdb.api.auth import require_auth
from meowdb.api.models import (
    ClipRequest,
    CommitRequest,
    CommitResponse,
    DetectRegion,
    DetectResponse,
    IngestJobResponse,
    IngestSegmentResponse,
)
from meowdb.api.streaming import safe_path, stream_file
from meowdb.config import MP3_DIR, STAGING_DIR, WAV_DIR
from meowdb.similarity import MeowSimilarity

_similarity = MeowSimilarity()


def _update_uniqueness_after_ingest(db: Any, new_meow_ids: list[str]) -> None:
    """Extract fingerprints for newly committed meows, then recompute all scores."""
    all_rows = {r["id"]: r["wav_path"] for r in db.get_all_wav_paths()}
    fingerprints = db.get_all_fingerprints()

    for meow_id in new_meow_ids:
        if meow_id not in fingerprints and meow_id in all_rows:
            try:
                fp = _similarity.extract_fingerprint(all_rows[meow_id])
                db.update_fingerprint(meow_id, fp)
                fingerprints[meow_id] = fp
            except Exception as exc:
                logger.warning("Failed to extract fingerprint for %s: %s", meow_id, exc)

    if fingerprints:
        scores = _similarity.compute_uniqueness_scores(fingerprints)
        db.update_uniqueness_scores_bulk(scores)


router = APIRouter(dependencies=[Depends(require_auth)])
logger = logging.getLogger(__name__)

_MAX_UPLOAD_BYTES = 500 * 1024 * 1024
_ALLOWED_SUFFIXES = {".m4a", ".mp3", ".wav", ".ogg", ".flac", ".aac", ".webm"}


def _seg_to_response(seg: dict, job_id: str) -> IngestSegmentResponse:  # type: ignore[type-arg]
    return IngestSegmentResponse(
        id=seg["id"],
        index=seg["index_in_job"],
        duration_ms=seg["duration_ms"],
        url=f"/api/ingest/{job_id}/audio/{seg['id']}",
        waveform=seg.get("waveform_data") or [],
        status=seg.get("status") or "pending",
    )


def _job_to_response(job: dict) -> IngestJobResponse:  # type: ignore[type-arg]
    segments = None
    if job.get("segments"):
        segments = [_seg_to_response(s, job["id"]) for s in job["segments"]]
    return IngestJobResponse(
        job_id=job["id"],
        status=job["status"],
        segments=segments,
        source_filename=job.get("source_filename"),
        error=job.get("error"),
    )


def _resolve_source(job_id: str) -> Path:
    """Locate the source audio file for an ingest job, with path-traversal guard."""
    candidate = (STAGING_DIR / job_id).resolve()
    if not str(candidate).startswith(str(STAGING_DIR.resolve())):
        raise HTTPException(status_code=403, detail="Access denied")
    source_files = list(candidate.glob("source.*"))
    if not source_files:
        raise HTTPException(status_code=404, detail="Source file not found")
    return source_files[0]


@router.post("/ingest", response_model=IngestJobResponse, status_code=202)
async def create_ingest_job(
    request: Request,
    file: UploadFile,
) -> IngestJobResponse:
    db = request.app.state.db

    source_filename = file.filename or "upload"
    suffix = Path(source_filename).suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix!r}")

    job_id = db.create_job(source_filename)

    job_staging_dir = STAGING_DIR / job_id
    job_staging_dir.mkdir(parents=True, exist_ok=True)

    temp_path = job_staging_dir / f"source{suffix}"
    total = 0
    with temp_path.open("wb") as dest:
        while True:
            chunk = await file.read(65536)
            if not chunk:
                break
            total += len(chunk)
            if total > _MAX_UPLOAD_BYTES:
                temp_path.unlink(missing_ok=True)
                shutil.rmtree(job_staging_dir, ignore_errors=True)
                db.delete_job(job_id)
                raise HTTPException(status_code=413, detail="Upload exceeds 500 MB limit")
            dest.write(chunk)

    db.update_job_status(job_id, "uploaded")

    return IngestJobResponse(
        job_id=job_id,
        status="uploaded",
        source_filename=source_filename,
    )


@router.get("/ingest/{job_id}", response_model=IngestJobResponse)
async def get_ingest_job(job_id: str, request: Request) -> IngestJobResponse:
    db = request.app.state.db
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_to_response(job)


@router.get("/ingest/{job_id}/audio/{segment_id}")
async def stream_segment_audio(
    job_id: str,
    segment_id: str,
    request: Request,
) -> StreamingResponse:
    db = request.app.state.db
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    seg_row = db.get_segment(segment_id, job_id)
    if seg_row is None:
        raise HTTPException(status_code=404, detail="Segment not found")

    wav_path_str = seg_row.get("wav_path", "")
    if not wav_path_str:
        raise HTTPException(status_code=404, detail="Segment audio not available")

    # Serve MP3 if it exists alongside WAV, else fall back to WAV
    wav_path = Path(wav_path_str)
    mp3_path = wav_path.with_suffix(".mp3")
    if mp3_path.exists():
        serve_path = mp3_path
        media_type = "audio/mpeg"
    elif wav_path.exists():
        serve_path = wav_path
        media_type = "audio/wav"
    else:
        raise HTTPException(status_code=404, detail="Segment audio file not found on disk")

    try:
        serve_path = safe_path(serve_path, STAGING_DIR)
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied") from None

    return stream_file(serve_path, request, media_type)


@router.post("/ingest/{job_id}/commit", response_model=CommitResponse)
async def commit_ingest_job(
    job_id: str,
    body: CommitRequest,
    request: Request,
) -> CommitResponse:
    db = request.app.state.db
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    meow_ids = db.commit_job(job_id, body.accepted_ids, body.rejected_ids, WAV_DIR, MP3_DIR)

    # Clean up rejected staging files
    for seg_id in body.rejected_ids:
        seg = db.get_segment(seg_id, job_id)
        if seg:
            wav_p = Path(seg.get("wav_path") or "")
            if wav_p.exists():
                wav_p.unlink(missing_ok=True)
            mp3_p = wav_p.with_suffix(".mp3")
            if mp3_p.exists():
                mp3_p.unlink(missing_ok=True)

    job_staging_dir = STAGING_DIR / job_id
    if job_staging_dir.exists():
        try:
            shutil.rmtree(str(job_staging_dir))
        except OSError:
            logger.warning("Failed to remove staging dir %s", job_staging_dir)

    if meow_ids:
        await run_in_threadpool(_update_uniqueness_after_ingest, db, meow_ids)

    return CommitResponse(meow_ids=meow_ids, rejected_count=len(body.rejected_ids))


@router.delete("/ingest/{job_id}", status_code=204)
async def delete_ingest_job(job_id: str, request: Request) -> None:
    db = request.app.state.db
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    job_staging_dir = STAGING_DIR / job_id
    if job_staging_dir.exists():
        try:
            shutil.rmtree(str(job_staging_dir))
        except OSError:
            logger.warning("Failed to remove staging dir %s", job_staging_dir)

    db.delete_job(job_id)


_SOURCE_MEDIA_TYPES = {
    ".m4a": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
    ".aac": "audio/aac",
    ".webm": "audio/webm",
}


@router.get("/ingest/{job_id}/source")
async def stream_source_audio(job_id: str, request: Request) -> StreamingResponse:
    db = request.app.state.db
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    source_path = _resolve_source(job_id)
    media_type = _SOURCE_MEDIA_TYPES.get(source_path.suffix.lower(), "application/octet-stream")
    return stream_file(source_path, request, media_type)


@router.post("/ingest/{job_id}/detect", response_model=DetectResponse)
async def detect_regions(job_id: str, request: Request) -> DetectResponse:
    from meowdb.processor import MeowProcessor

    db = request.app.state.db
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    source_path = _resolve_source(job_id)
    result = await run_in_threadpool(MeowProcessor().detect_only, source_path)
    return DetectResponse(regions=[DetectRegion(start_ms=s, end_ms=e) for s, e in result])


@router.post("/ingest/{job_id}/clip", response_model=CommitResponse)
async def clip_and_commit(job_id: str, body: ClipRequest, request: Request) -> CommitResponse:
    from meowdb.processor import MeowProcessor

    db = request.app.state.db
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if not body.regions:
        raise HTTPException(status_code=400, detail="At least one region is required")

    source_path = _resolve_source(job_id)
    try:
        mtime = os.path.getmtime(str(source_path))
        recorded_at: str | None = datetime.fromtimestamp(mtime).isoformat()
    except OSError:
        recorded_at = None
    staging_dir = STAGING_DIR / job_id

    regions = [(r.start_ms, r.end_ms) for r in body.regions]
    segments = await run_in_threadpool(
        MeowProcessor().process_clips, source_path, regions, staging_dir
    )

    seg_dicts = [
        {
            "index": seg.index,
            "duration_ms": seg.duration_ms,
            "wav_path": str(seg.wav_path) if seg.wav_path else "",
            "waveform_data": seg.waveform_data,
            "peak_dbfs": seg.peak_dbfs,
            "cat_energy_ratio": seg.cat_energy_ratio,
        }
        for seg in segments
    ]
    db.add_segments(job_id, seg_dicts)
    segment_ids = db.get_segment_ids(job_id)
    meow_ids = db.commit_job(job_id, segment_ids, [], WAV_DIR, MP3_DIR, recorded_at=recorded_at)
    shutil.rmtree(staging_dir, ignore_errors=True)

    if meow_ids:
        await run_in_threadpool(_update_uniqueness_after_ingest, db, meow_ids)

    return CommitResponse(meow_ids=meow_ids, rejected_count=0)
