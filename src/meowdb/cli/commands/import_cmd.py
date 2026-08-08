from __future__ import annotations

import json
import uuid
import zipfile

from collections.abc import Callable
from pathlib import Path

import click

from pydub import AudioSegment

from meowdb.cli.archive import AUDIO_PREFIX, MANIFEST_PATH, PHOTOS_PREFIX, SUPPORTED_FORMAT_VERSIONS
from meowdb.cli.helpers import build_context, die
from meowdb.cli.options import db_path_option
from meowdb.config import MP3_DIR, PHOTOS_DIR, WAV_DIR
from meowdb.display import print_info, print_success, print_warning
from meowdb.similarity import update_library_uniqueness


@click.command(name="import")
@click.argument("archive", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--on-conflict",
    type=click.Choice(["skip", "replace", "new-ids"]),
    default="skip",
    show_default=True,
    help="How to handle sounds/photos whose ID already exists in the library.",
)
@click.option(
    "--include-photos", is_flag=True, default=False, help="Import animal photos from the archive."
)
@db_path_option
def import_sounds(
    archive: str, on_conflict: str, include_photos: bool, db_path: str | None
) -> None:
    """Import sounds from an export archive."""
    ctx = build_context(db_path)

    try:
        zf = zipfile.ZipFile(archive, "r")
    except zipfile.BadZipFile:
        die(ctx, f"Not a valid zip archive: {archive}")

    with zf:
        try:
            manifest = json.loads(zf.read(MANIFEST_PATH))
        except KeyError:
            die(ctx, "Archive is missing manifest.json — not a meowdb export.")

        fmt_version = manifest.get("format_version")
        if fmt_version not in SUPPORTED_FORMAT_VERSIONS:
            die(ctx, f"Unsupported archive format version: {fmt_version!r}")

        WAV_DIR.mkdir(parents=True, exist_ok=True)
        MP3_DIR.mkdir(parents=True, exist_ok=True)

        # --- Resolve animal IDs ---
        # resolve_animal_id(archive_animal_id) → local animal id to use
        resolve_animal_id: Callable[[str | None], str]

        if fmt_version >= 2:
            animal_id_map: dict[str, str] = {}
            for animal in manifest.get("animals", []):
                archive_id: str = animal["id"]
                if ctx.db.get_animal(archive_id):
                    animal_id_map[archive_id] = archive_id
                else:
                    existing_local = next(
                        (
                            a
                            for a in ctx.db.get_animals()
                            if a["name"] == animal["name"] and a["species"] == animal["species"]
                        ),
                        None,
                    )
                    if existing_local:
                        animal_id_map[archive_id] = existing_local["id"]
                    else:
                        animal_id_map[archive_id] = ctx.db.add_animal(
                            animal["name"], animal["species"]
                        )

            all_animals = ctx.db.get_animals()
            fallback_animal_id: str = (
                all_animals[0]["id"] if all_animals else ctx.db.add_animal("Squishy", "cat")
            )

            def resolve_animal_id(archive_animal_id: str | None) -> str:
                # A missing or unmapped id means a malformed manifest; fall back to
                # the default animal rather than violating the sounds FK.
                if archive_animal_id is None:
                    return fallback_animal_id
                return animal_id_map.get(archive_animal_id, fallback_animal_id)

            sounds = manifest.get("sounds", [])

        else:
            # v1: all sounds belong to the first/default animal
            all_animals = ctx.db.get_animals()
            default_animal_id = (
                all_animals[0]["id"] if all_animals else ctx.db.add_animal("Squishy", "cat")
            )

            def resolve_animal_id(_: str | None) -> str:
                return default_animal_id

            # Normalize v1 field names before processing
            sounds = manifest.get("meows", [])
            for sound in sounds:
                if "cat_energy_ratio" in sound and "species_energy_ratio" not in sound:
                    sound["species_energy_ratio"] = sound.pop("cat_energy_ratio")

        # --- Import sounds ---
        imported_sounds = 0
        skipped_sounds = 0
        replaced_sounds = 0
        new_ids: list[str] = []

        for sound in sounds:
            archive_id = sound["id"]
            arc_wav = f"{AUDIO_PREFIX}{archive_id}.wav"

            if arc_wav not in zf.namelist():
                print_warning(f"WAV missing in archive for {archive_id[:8]}, skipping")
                skipped_sounds += 1
                continue

            existing = ctx.db.get_by_id(archive_id)
            if existing:
                if on_conflict == "skip":
                    skipped_sounds += 1
                    continue
                elif on_conflict == "replace":
                    for field in ("wav_path", "mp3_path"):
                        p = Path(existing.get(field) or "")
                        if p.exists():
                            p.unlink()
                    ctx.db.delete(archive_id)
                    replaced_sounds += 1

            sound_id = str(uuid.uuid4()) if on_conflict == "new-ids" else archive_id

            wav_path = WAV_DIR / f"{sound_id}.wav"
            mp3_path = MP3_DIR / f"{sound_id}.mp3"

            with zf.open(arc_wav) as src, wav_path.open("wb") as dst:
                dst.write(src.read())

            audio = AudioSegment.from_wav(str(wav_path))
            audio.export(str(mp3_path), format="mp3", bitrate="192k")

            resolved_animal_id = resolve_animal_id(sound.get("animal_id"))
            ctx.db.import_sound(sound_id, sound, str(wav_path), str(mp3_path), resolved_animal_id)
            new_ids.append(sound_id)
            imported_sounds += 1

        # --- Import photos if requested and present in the archive ---
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
                    arc_photo = f"{PHOTOS_PREFIX}{original_filename}"

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

                    resolved_photo_animal_id = resolve_animal_id(photo.get("animal_id"))
                    ctx.db.import_photo(
                        photo_id,
                        filename,
                        resolved_photo_animal_id,
                        photo.get("created_at"),
                        bool(photo.get("is_default")),
                        photo.get("updated_at"),
                    )
                    imported_photos += 1

    if new_ids:
        print_info("Recomputing fingerprints and uniqueness scores...")
        update_library_uniqueness(ctx.db, new_ids)

    ctx.db.close()

    sound_parts = [f"Imported {imported_sounds} sound(s)"]
    if replaced_sounds:
        sound_parts.append(f"{replaced_sounds} replaced")
    if skipped_sounds:
        sound_parts.append(f"{skipped_sounds} skipped")

    if include_photos and manifest.get("photos") is not None:
        photo_parts = [f"{imported_photos} photo(s)"]
        if replaced_photos:
            photo_parts.append(f"{replaced_photos} replaced")
        if skipped_photos:
            photo_parts.append(f"{skipped_photos} skipped")
        print_success(", ".join(sound_parts) + " | photos: " + ", ".join(photo_parts))
    else:
        print_success(", ".join(sound_parts))
