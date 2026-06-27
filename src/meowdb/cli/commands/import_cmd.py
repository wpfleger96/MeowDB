from __future__ import annotations

import json
import sys
import uuid
import zipfile

from pathlib import Path

import click

from pydub import AudioSegment

from meowdb.cli.helpers import build_context
from meowdb.cli.options import db_path_option
from meowdb.config import MP3_DIR, PHOTOS_DIR, WAV_DIR
from meowdb.display import print_error, print_info, print_success, print_warning
from meowdb.similarity import update_library_uniqueness

_MANIFEST_PATH = "meowdb-export/manifest.json"
_SUPPORTED_FORMAT_VERSIONS = {1}


@click.command(name="import")
@click.argument("archive", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--on-conflict",
    type=click.Choice(["skip", "replace", "new-ids"]),
    default="skip",
    show_default=True,
    help="How to handle meows/photos whose ID already exists in the library.",
)
@click.option(
    "--include-photos", is_flag=True, default=False, help="Import cat photos from the archive."
)
@db_path_option
def import_meows(archive: str, on_conflict: str, include_photos: bool, db_path: str | None) -> None:
    """Import meows from an export archive."""
    ctx = build_context(Path(db_path) if db_path else None)

    try:
        zf = zipfile.ZipFile(archive, "r")
    except zipfile.BadZipFile:
        print_error(f"Not a valid zip archive: {archive}")
        ctx.db.close()
        sys.exit(1)

    with zf:
        try:
            manifest = json.loads(zf.read(_MANIFEST_PATH))
        except KeyError:
            print_error("Archive is missing manifest.json — not a meowdb export.")
            ctx.db.close()
            sys.exit(1)

        if manifest.get("format_version") not in _SUPPORTED_FORMAT_VERSIONS:
            print_error(f"Unsupported archive format version: {manifest.get('format_version')!r}")
            ctx.db.close()
            sys.exit(1)

        WAV_DIR.mkdir(parents=True, exist_ok=True)
        MP3_DIR.mkdir(parents=True, exist_ok=True)

        imported_meows = 0
        skipped_meows = 0
        replaced_meows = 0
        new_ids: list[str] = []

        for meow in manifest.get("meows", []):
            archive_id: str = meow["id"]
            arc_wav = f"meowdb-export/audio/{archive_id}.wav"

            if arc_wav not in zf.namelist():
                print_warning(f"WAV missing in archive for {archive_id[:8]}, skipping")
                skipped_meows += 1
                continue

            existing = ctx.db.get_by_id(archive_id)
            if existing:
                if on_conflict == "skip":
                    skipped_meows += 1
                    continue
                elif on_conflict == "replace":
                    for field in ("wav_path", "mp3_path"):
                        p = Path(existing.get(field) or "")
                        if p.exists():
                            p.unlink()
                    ctx.db.delete(archive_id)
                    replaced_meows += 1

            meow_id = str(uuid.uuid4()) if on_conflict == "new-ids" else archive_id

            wav_path = WAV_DIR / f"{meow_id}.wav"
            mp3_path = MP3_DIR / f"{meow_id}.mp3"

            with zf.open(arc_wav) as src, wav_path.open("wb") as dst:
                dst.write(src.read())

            audio = AudioSegment.from_wav(str(wav_path))
            audio.export(str(mp3_path), format="mp3", bitrate="192k")

            ctx.db.import_meow(meow_id, meow, str(wav_path), str(mp3_path))
            new_ids.append(meow_id)
            imported_meows += 1

        # Import photos if requested and present in the archive
        imported_photos = 0
        skipped_photos = 0
        replaced_photos = 0

        if include_photos:
            archive_photos = manifest.get("photos")
            if archive_photos is None:
                print_warning(
                    "Archive does not contain photos (was not exported with --include-photos)"
                )
            else:
                PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
                for photo in archive_photos:
                    original_id: str = photo["id"]
                    original_filename: str = photo["filename"]
                    arc_photo = f"meowdb-export/photos/{original_filename}"

                    if arc_photo not in zf.namelist():
                        print_warning(
                            f"Photo file missing in archive for {original_id[:8]}, skipping"
                        )
                        skipped_photos += 1
                        continue

                    existing_photo = ctx.db.get_photo(original_id)
                    if existing_photo:
                        if on_conflict == "skip":
                            skipped_photos += 1
                            continue
                        elif on_conflict == "replace":
                            old_file = PHOTOS_DIR / existing_photo["filename"]
                            if old_file.exists():
                                old_file.unlink()
                            ctx.db.delete_photo(original_id)
                            replaced_photos += 1

                    if on_conflict == "new-ids":
                        photo_id = str(uuid.uuid4())
                        filename = f"{photo_id}.webp"
                    else:
                        photo_id = original_id
                        filename = original_filename

                    dest = PHOTOS_DIR / filename
                    with zf.open(arc_photo) as src, dest.open("wb") as dst:
                        dst.write(src.read())

                    ctx.db.import_photo(
                        photo_id,
                        filename,
                        photo.get("created_at"),
                        bool(photo.get("is_default")),
                        photo.get("updated_at"),
                    )
                    imported_photos += 1

    if new_ids:
        print_info("Recomputing fingerprints and uniqueness scores...")
        update_library_uniqueness(ctx.db, new_ids)

    ctx.db.close()

    meow_parts = [f"Imported {imported_meows} meow(s)"]
    if replaced_meows:
        meow_parts.append(f"{replaced_meows} replaced")
    if skipped_meows:
        meow_parts.append(f"{skipped_meows} skipped")

    if include_photos and manifest.get("photos") is not None:
        photo_parts = [f"{imported_photos} photo(s)"]
        if replaced_photos:
            photo_parts.append(f"{replaced_photos} replaced")
        if skipped_photos:
            photo_parts.append(f"{skipped_photos} skipped")
        print_success(", ".join(meow_parts) + " | photos: " + ", ".join(photo_parts))
    else:
        print_success(", ".join(meow_parts))
