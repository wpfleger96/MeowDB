from __future__ import annotations

import logging
import os
import shutil

from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from meowdb.api.auth import require_auth
from meowdb.api.models import (
    ClipRegion,
    ClipRequest,
    CommitRequest,
    CommitResponse,
    DetectResponse,
    IngestJobResponse,
    IngestSegmentResponse,
)
from meowdb.api.streaming import safe_path, save_upload, stream_file
from meowdb.config import ALLOWED_MEDIA_SUFFIXES, MP3_DIR, STAGING_DIR, VIDEO_SUFFIXES, WAV_DIR
from meowdb.similarity import update_library_uniqueness
from meowdb.storage import is_s3_enabled, mp3_key, upload_to_s3, wav_key

router = APIRouter(dependencies=[Depends(require_auth)])
logger = logging.getLogger(__name__)

_MAX_UPLOAD_BYTES = 500 * 1024 * 1024


async def _upload_committed_to_s3(db: Any, sound_ids: list[str]) -> None:
    for sound_id in sound_ids:
        wav_local = WAV_DIR / f"{sound_id}.wav"
        mp3_local = MP3_DIR / f"{sound_id}.mp3"
        try:
            if not wav_local.exists() or not mp3_local.exists():
                logger.warning("Missing audio files for sound %s; skipping S3 upload", sound_id)
                continue
            await upload_to_s3(wav_local, wav_key(sound_id))
            await upload_to_s3(mp3_local, mp3_key(sound_id))
            db.update_sound_paths(sound_id, wav_key(sound_id), mp3_key(sound_id))
            wav_local.unlink(missing_ok=True)
            mp3_local.unlink(missing_ok=True)
        except Exception:
            logger.warning("S3 upload failed for sound %s; keeping local files", sound_id)


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
        animal_id=job.get("animal_id"),
    )


def _resolve_staging_path(job_id: str, prefer_audio: bool = False) -> Path:
    try:
        job_dir = safe_path(STAGING_DIR / job_id, STAGING_DIR)
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied") from None
    if prefer_audio:
        audio_path = job_dir / "source_audio.wav"
        if audio_path.exists():
            return audio_path
    source_files = list(job_dir.glob("source.*"))
    if not source_files:
        raise HTTPException(status_code=404, detail="Source file not found")
    return source_files[0]


def _extract_audio_from_video(source_path: Path, staging_dir: Path) -> None:
    from pydub import AudioSegment

    audio_path = staging_dir / "source_audio.wav"
    try:
        audio = AudioSegment.from_file(str(source_path))
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail="Could not extract audio from video file"
        ) from exc
    if len(audio) == 0:
        raise HTTPException(status_code=400, detail="Video file contains no audio track")
    audio.export(str(audio_path), format="wav")


@router.post("/ingest", response_model=IngestJobResponse, status_code=202)
async def create_ingest_job(
    request: Request,
    file: UploadFile,
    animal_id: str = Form(...),
) -> IngestJobResponse:
    db = request.app.state.db

    animal = db.get_animal(animal_id)
    if animal is None:
        raise HTTPException(status_code=404, detail="Animal not found")

    source_filename = file.filename or "upload"
    suffix = Path(source_filename).suffix.lower()
    if suffix not in ALLOWED_MEDIA_SUFFIXES:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix!r}")

    job_id = db.create_job(source_filename, animal_id)

    job_staging_dir = STAGING_DIR / job_id
    job_staging_dir.mkdir(parents=True, exist_ok=True)

    temp_path = job_staging_dir / f"source{suffix}"
    try:
        await save_upload(file, temp_path, _MAX_UPLOAD_BYTES, "Upload exceeds 500 MB limit")
    except HTTPException:
        temp_path.unlink(missing_ok=True)
        shutil.rmtree(job_staging_dir, ignore_errors=True)
        db.delete_job(job_id)
        raise
    except OSError as err:
        temp_path.unlink(missing_ok=True)
        shutil.rmtree(job_staging_dir, ignore_errors=True)
        db.delete_job(job_id)
        raise HTTPException(status_code=500, detail="Failed to store upload") from err

    db.update_job_status(job_id, "uploaded")

    if suffix in VIDEO_SUFFIXES:
        try:
            await run_in_threadpool(_extract_audio_from_video, temp_path, job_staging_dir)
        except HTTPException:
            shutil.rmtree(job_staging_dir, ignore_errors=True)
            db.delete_job(job_id)
            raise

    return IngestJobResponse(
        job_id=job_id,
        status="uploaded",
        source_filename=source_filename,
        animal_id=animal_id,
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

    sound_ids = db.commit_job(job_id, body.accepted_ids, body.rejected_ids, WAV_DIR, MP3_DIR)

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

    if sound_ids:
        await run_in_threadpool(update_library_uniqueness, db, sound_ids)
        if is_s3_enabled():
            await _upload_committed_to_s3(db, sound_ids)

    return CommitResponse(sound_ids=sound_ids, rejected_count=len(body.rejected_ids))


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

    source_path = _resolve_staging_path(job_id, prefer_audio=True)
    media_type = _SOURCE_MEDIA_TYPES.get(source_path.suffix.lower(), "application/octet-stream")
    return stream_file(source_path, request, media_type)


def _processor_for_job(db: Any, job: dict) -> Any:  # type: ignore[type-arg]
    from meowdb.processor import SoundProcessor
    from meowdb.species import DEFAULT_SPECIES, processor_config_for_species

    animal = db.get_animal(job["animal_id"])
    species = animal["species"] if animal else DEFAULT_SPECIES
    return SoundProcessor(processor_config_for_species(species))


@router.post("/ingest/{job_id}/detect", response_model=DetectResponse)
async def detect_regions(job_id: str, request: Request) -> DetectResponse:
    db = request.app.state.db
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    source_path = _resolve_staging_path(job_id)
    try:
        processor = _processor_for_job(db, job)
        result = await run_in_threadpool(processor.detect_only, source_path)
    except HTTPException:
        raise
    except ValueError as exc:
        # Config and unsupported-recording errors carry a message the user can act on
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Could not process audio file") from exc
    return DetectResponse(regions=[ClipRegion(start_ms=s, end_ms=e) for s, e in result])


@router.post("/ingest/{job_id}/clip", response_model=CommitResponse)
async def clip_and_commit(job_id: str, body: ClipRequest, request: Request) -> CommitResponse:
    db = request.app.state.db
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if not body.regions:
        raise HTTPException(status_code=400, detail="At least one region is required")

    source_path = _resolve_staging_path(job_id)
    try:
        mtime = os.path.getmtime(str(source_path))
        recorded_at: str | None = datetime.fromtimestamp(mtime).isoformat()
    except OSError:
        recorded_at = None
    staging_dir = STAGING_DIR / job_id

    regions = [(r.start_ms, r.end_ms) for r in body.regions]
    try:
        processor = _processor_for_job(db, job)
        segments = await run_in_threadpool(
            processor.process_clips, source_path, regions, staging_dir
        )
    except HTTPException:
        raise
    except ValueError as exc:
        # Config and unsupported-recording errors carry a message the user can act on
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Could not process audio file") from exc

    seg_dicts = [seg.to_db_dict() for seg in segments]
    db.add_segments(job_id, seg_dicts)
    segment_ids = db.get_segment_ids(job_id)
    sound_ids = db.commit_job(job_id, segment_ids, [], WAV_DIR, MP3_DIR, recorded_at=recorded_at)
    shutil.rmtree(staging_dir, ignore_errors=True)

    if sound_ids:
        await run_in_threadpool(update_library_uniqueness, db, sound_ids)
        if is_s3_enabled():
            await _upload_committed_to_s3(db, sound_ids)

    return CommitResponse(sound_ids=sound_ids, rejected_count=0)
