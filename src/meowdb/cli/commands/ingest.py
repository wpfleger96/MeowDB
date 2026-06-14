from __future__ import annotations

import sys

from pathlib import Path

import click

from meowdb.cli.context import Context
from meowdb.cli.helpers import build_context, format_duration, play_audio
from meowdb.cli.options import db_path_option
from meowdb.config import MP3_DIR, STAGING_DIR, WAV_DIR
from meowdb.display import console, print_error, print_hint, print_info, print_success
from meowdb.models import ProcessingResult

_AUDIO_EXTENSIONS = {".m4a", ".mp3", ".wav"}

# Files shorter than this are treated as single-meow clips
_SINGLE_MEOW_THRESHOLD_MS = 8000


@click.command()
@click.argument("path", type=click.Path(exists=True))
@click.option(
    "--segment/--no-segment",
    default=None,
    help="Force segmentation on or off. Default: auto-detect.",
)
@click.option(
    "--review/--no-review",
    default=True,
    show_default=True,
    help="Interactive review loop before committing.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Show what would be extracted without writing anything.",
)
@db_path_option
def ingest(
    path: str,
    segment: bool | None,
    review: bool,
    dry_run: bool,
    db_path: str | None,
) -> None:
    """Ingest an audio file or directory into the meow library."""
    ctx = build_context(Path(db_path) if db_path else None)

    source = Path(path)
    if source.is_dir():
        audio_files = sorted(f for f in source.iterdir() if f.suffix.lower() in _AUDIO_EXTENSIONS)
        if not audio_files:
            print_error(f"No audio files found in {source}")
            ctx.db.close()
            sys.exit(1)
        for audio_file in audio_files:
            _ingest_file(audio_file, segment, review, dry_run, ctx)
    else:
        _ingest_file(source, segment, review, dry_run, ctx)

    ctx.db.close()


def _ingest_file(
    path: Path,
    segment: bool | None,
    review: bool,
    dry_run: bool,
    ctx: Context,
) -> None:

    print_info(f"Processing {path.name} …")

    if dry_run:
        _dry_run_file(path, segment, ctx)
        return

    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    job_id = ctx.db.create_job(path.name)
    ctx.db.update_job_status(job_id, "processing")

    try:
        result = _run_processor(path, segment, ctx)
    except Exception as exc:
        ctx.db.update_job_status(job_id, "error", str(exc))
        print_error(f"Processing failed: {exc}")
        ctx.db.delete_job(job_id)
        return

    if not result.segments:
        print_error("No meow segments detected.")
        ctx.db.delete_job(job_id)
        return

    seg_dicts = [
        {
            "index": seg.index,
            "duration_ms": seg.duration_ms,
            "wav_path": str(seg.wav_path),
            "waveform_data": seg.waveform_data,
            "peak_dbfs": seg.peak_dbfs,
            "cat_energy_ratio": seg.cat_energy_ratio,
        }
        for seg in result.segments
    ]
    ctx.db.add_segments(job_id, seg_dicts)
    ctx.db.update_job_status(job_id, "ready")

    job = ctx.db.get_job(job_id)
    if job is None:
        print_error("Job disappeared unexpectedly")
        sys.exit(1)
    segments = job["segments"]

    if review:
        accepted_ids, rejected_ids = _review_loop(segments, result)
    else:
        accepted_ids = [s["id"] for s in segments]
        rejected_ids = []

    new_ids = ctx.db.commit_job(job_id, accepted_ids, rejected_ids, WAV_DIR, MP3_DIR)
    ctx.db.delete_job(job_id)

    _print_summary(path, result, len(new_ids), len(rejected_ids))


def _detect_mode(path: Path, segment: bool | None) -> tuple[bool, int]:
    from pydub import AudioSegment as PydubSegment

    audio = PydubSegment.from_file(str(path))
    duration_ms = len(audio)
    del audio
    use_single = segment is False or (segment is None and duration_ms < _SINGLE_MEOW_THRESHOLD_MS)
    return use_single, duration_ms


def _run_processor(path: Path, segment: bool | None, ctx: Context) -> ProcessingResult:
    use_single, _ = _detect_mode(path, segment)

    if use_single:
        seg = ctx.processor.process_single(path, staging_dir=STAGING_DIR)
        return ProcessingResult(
            source_path=path,
            segments=[seg],
            rejected_count=0,
            total_candidates=1,
            elapsed_seconds=0.0,
        )
    return ctx.processor.process_file(path, staging_dir=STAGING_DIR)


def _dry_run_file(path: Path, segment: bool | None, ctx: Context) -> None:
    use_single, duration_ms = _detect_mode(path, segment)

    mode = "single meow" if use_single else "multi-segment"
    console.print(
        f"  [dim]dry-run:[/dim] {path.name} — {format_duration(duration_ms)} — mode: {mode}"
    )
    if not use_single:
        print_hint("Run without --dry-run to extract and review segments.")


def _review_loop(
    segments: list[dict],  # type: ignore[type-arg]
    result: object,
) -> tuple[list[str], list[str]]:
    accepted: list[str] = []
    rejected: list[str] = []

    console.print(f"\nReviewing [bold]{len(segments)}[/bold] segment(s) — y/n/r/q\n")

    i = 0
    while i < len(segments):
        seg = segments[i]
        seg_id = seg["id"]
        duration = format_duration(seg["duration_ms"])
        console.print(f"  [{i + 1}/{len(segments)}] {duration}")

        wav_path = Path(seg["wav_path"])
        play_audio(wav_path)

        while True:
            choice = click.prompt(
                "  Keep?",
                type=click.Choice(["y", "n", "r", "q"]),
                default="y",
                show_default=True,
            )
            if choice == "r":
                play_audio(wav_path)
                continue
            elif choice == "q":
                # Reject all remaining (including current)
                rejected.extend(s["id"] for s in segments[i:])
                console.print("\n[yellow]Quit — discarding remaining segments.[/yellow]")
                return accepted, rejected
            elif choice == "y":
                accepted.append(seg_id)
            else:
                rejected.append(seg_id)
            break

        i += 1

    return accepted, rejected


def _print_summary(
    path: Path,
    result: ProcessingResult,
    accepted_count: int,
    rejected_count: int,
) -> None:
    console.print()
    print_success(
        f"{path.name}: {accepted_count} meow(s) added"
        + (f", {rejected_count} rejected" if rejected_count else "")
    )
    if result.elapsed_seconds:
        print_info(f"Processed in {result.elapsed_seconds:.1f}s")
