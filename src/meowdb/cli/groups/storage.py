from __future__ import annotations

import sys

from pathlib import Path

import click

from meowdb.cli.helpers import build_context
from meowdb.cli.options import db_path_option
from meowdb.config import MP3_DIR, PHOTOS_DIR, WAV_DIR
from meowdb.display import print_error, print_info, print_success, print_warning


@click.group()
def storage() -> None:
    """S3 storage management."""


@storage.command(name="migrate-to-s3")
@click.option(
    "--dry-run", is_flag=True, default=False, help="Print what would be done without doing it."
)
@click.option(
    "--delete-local", is_flag=True, default=False, help="Delete local files after uploading."
)
@db_path_option
def migrate_to_s3(dry_run: bool, delete_local: bool, db_path: str | None) -> None:
    """Upload local media to S3 and update path records."""
    import botocore.exceptions

    from meowdb.storage import (
        is_s3_enabled,
        is_s3_key,
        mp3_key,
        photo_key,
        upload_to_s3_sync,
        wav_key,
    )

    if not is_s3_enabled():
        print_error("S3 is not configured. Set MEOWDB_S3_BUCKET to enable S3 mode.")
        sys.exit(1)

    ctx = build_context(db_path)
    sounds = ctx.db.get_all_for_export()
    photos = ctx.db.get_photos()

    sounds_migrated = 0
    sounds_skipped = 0
    sounds_failed = 0
    photos_migrated = 0
    photos_skipped = 0
    photos_failed = 0

    for sound in sounds:
        sound_id: str = sound["id"]
        wav_path: str | None = sound.get("wav_path")
        mp3_path: str | None = sound.get("mp3_path")

        if not wav_path or is_s3_key(wav_path):
            print_info(f"Sound {sound_id[:8]}: already migrated, skipping")
            sounds_skipped += 1
            continue

        wk = wav_key(sound_id)
        mk = mp3_key(sound_id)

        if dry_run:
            print_info(f"Sound {sound_id[:8]}: would upload {wav_path} → {wk}")
            if mp3_path:
                print_info(f"Sound {sound_id[:8]}: would upload {mp3_path} → {mk}")
            sounds_migrated += 1
            continue

        try:
            upload_to_s3_sync(Path(wav_path), wk)
            if mp3_path:
                upload_to_s3_sync(Path(mp3_path), mk)
            ctx.db.update_sound_paths(sound_id, wk, mk if mp3_path else (mp3_path or ""))
            if delete_local:
                Path(wav_path).unlink(missing_ok=True)
                if mp3_path:
                    Path(mp3_path).unlink(missing_ok=True)
        except (FileNotFoundError, botocore.exceptions.ClientError) as exc:
            print_warning(f"Sound {sound_id[:8]}: migration failed: {exc}")
            sounds_failed += 1
            continue

        print_info(f"Sound {sound_id[:8]}: migrated")
        sounds_migrated += 1

    for photo in photos:
        filename: str = photo["filename"]
        local_file = PHOTOS_DIR / filename

        if not local_file.exists():
            print_info(f"Photo {filename}: local file missing, skipping")
            photos_skipped += 1
            continue

        pk = photo_key(filename)

        if dry_run:
            print_info(f"Photo {filename}: would upload → {pk}")
            photos_migrated += 1
            continue

        try:
            upload_to_s3_sync(local_file, pk)
            if delete_local:
                local_file.unlink(missing_ok=True)
        except (FileNotFoundError, botocore.exceptions.ClientError) as exc:
            print_warning(f"Photo {filename}: migration failed: {exc}")
            photos_failed += 1
            continue

        print_info(f"Photo {filename}: migrated")
        photos_migrated += 1

    ctx.db.close()

    action = "would migrate" if dry_run else "migrated"
    sound_summary = f"{sounds_migrated} sound(s) {action}, {sounds_skipped} skipped"
    if sounds_failed:
        sound_summary += f", {sounds_failed} failed"
    photo_summary = f"{photos_migrated} photo(s) {action}, {photos_skipped} skipped"
    if photos_failed:
        photo_summary += f", {photos_failed} failed"
    print_success(f"{sound_summary} | {photo_summary}")


@storage.command(name="restore-from-s3")
@db_path_option
def restore_from_s3(db_path: str | None) -> None:
    """Download S3 media to local storage and restore path records."""
    import botocore.exceptions

    from meowdb.storage import (
        S3NotFoundError,
        download_from_s3_sync,
        is_s3_enabled,
        is_s3_key,
        mp3_key,
        photo_key,
        wav_key,
    )

    if not is_s3_enabled():
        print_error("S3 is not configured. Set MEOWDB_S3_BUCKET to enable S3 mode.")
        sys.exit(1)

    ctx = build_context(db_path)
    sounds = ctx.db.get_all_for_export()
    photos = ctx.db.get_photos()

    sounds_restored = 0
    sounds_failed = 0
    photos_restored = 0
    photos_failed = 0

    WAV_DIR.mkdir(parents=True, exist_ok=True)
    MP3_DIR.mkdir(parents=True, exist_ok=True)

    for sound in sounds:
        sound_id: str = sound["id"]
        wav_path: str | None = sound.get("wav_path")
        mp3_path: str | None = sound.get("mp3_path")

        wav_is_s3 = is_s3_key(wav_path or "")
        mp3_is_s3 = is_s3_key(mp3_path or "")

        if not wav_is_s3 and not mp3_is_s3:
            continue

        failed = False
        new_wav = wav_path or ""
        new_mp3 = mp3_path or ""

        if wav_is_s3:
            local_wav = WAV_DIR / f"{sound_id}.wav"
            try:
                download_from_s3_sync(wav_key(sound_id), local_wav)
                new_wav = str(local_wav)
            except (S3NotFoundError, botocore.exceptions.ClientError) as exc:
                print_error(f"Sound {sound_id[:8]}: WAV failed: {exc}")
                failed = True

        if mp3_is_s3:
            local_mp3 = MP3_DIR / f"{sound_id}.mp3"
            try:
                download_from_s3_sync(mp3_key(sound_id), local_mp3)
                new_mp3 = str(local_mp3)
            except (S3NotFoundError, botocore.exceptions.ClientError) as exc:
                print_error(f"Sound {sound_id[:8]}: MP3 failed: {exc}")
                failed = True

        if failed:
            sounds_failed += 1
            continue

        ctx.db.update_sound_paths(sound_id, new_wav, new_mp3)
        print_info(f"Sound {sound_id[:8]}: restored")
        sounds_restored += 1

    PHOTOS_DIR.mkdir(parents=True, exist_ok=True)

    for photo in photos:
        filename: str = photo["filename"]
        local_file = PHOTOS_DIR / filename

        if local_file.exists():
            continue

        try:
            download_from_s3_sync(photo_key(filename), local_file)
        except (S3NotFoundError, botocore.exceptions.ClientError) as exc:
            print_error(f"Photo {filename}: failed: {exc}")
            photos_failed += 1
            continue

        print_info(f"Photo {filename}: restored")
        photos_restored += 1

    ctx.db.close()

    print_success(
        f"{sounds_restored} sound(s) restored, {sounds_failed} failed"
        f" | {photos_restored} photo(s) restored, {photos_failed} failed"
    )

    if sounds_failed or photos_failed:
        sys.exit(1)
