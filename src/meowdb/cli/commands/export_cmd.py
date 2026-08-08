from __future__ import annotations

import json
import zipfile

from datetime import date
from pathlib import Path

import click

from meowdb.cli.archive import AUDIO_PREFIX, FORMAT_VERSION, MANIFEST_PATH, PHOTOS_PREFIX
from meowdb.cli.helpers import build_context
from meowdb.cli.options import db_path_option
from meowdb.config import DATA_DIR, PHOTOS_DIR
from meowdb.display import print_success, print_warning

_PORTABLE_FIELDS = {
    "id",
    "animal_id",
    "timestamp",
    "duration_ms",
    "labels",
    "play_count",
    "last_played",
    "created_at",
    "waveform_data",
    "peak_dbfs",
    "species_energy_ratio",
    "recorded_at",
    "title",
    "upvote_count",
    "downvote_count",
}


@click.command(name="export")
@click.argument("output", type=click.Path(dir_okay=False), default=None, required=False)
@click.option(
    "--include-photos", is_flag=True, default=False, help="Include animal photos in the archive."
)
@db_path_option
def export_sounds(output: str | None, include_photos: bool, db_path: str | None) -> None:
    """Export the sound library to a portable zip archive."""
    ctx = build_context(db_path)
    sounds = ctx.db.get_all_for_export()
    animals = ctx.db.get_animals()
    photos = ctx.db.get_photos() if include_photos else []
    ctx.db.close()

    out_path = Path(output) if output else DATA_DIR / f"meowdb-export-{date.today()}.zip"

    exported_sounds = 0
    skipped_sounds = 0
    exported_photos = 0
    skipped_photos = 0
    manifest_sounds = []
    manifest_photos = []

    with zipfile.ZipFile(out_path, "w") as zf:
        for sound in sounds:
            wav_path = Path(sound.get("wav_path") or "")
            if not wav_path.exists():
                print_warning(f"Missing WAV for {sound['id'][:8]}, skipping")
                skipped_sounds += 1
                continue
            zf.write(
                wav_path, AUDIO_PREFIX + sound["id"] + ".wav", compress_type=zipfile.ZIP_STORED
            )
            manifest_sounds.append({k: v for k, v in sound.items() if k in _PORTABLE_FIELDS})
            exported_sounds += 1

        for photo in photos:
            photo_path = PHOTOS_DIR / photo["filename"]
            if not photo_path.exists():
                print_warning(f"Missing photo file for {photo['id'][:8]}, skipping")
                skipped_photos += 1
                continue
            zf.write(
                photo_path, PHOTOS_PREFIX + photo["filename"], compress_type=zipfile.ZIP_STORED
            )
            manifest_photos.append(
                {
                    "id": photo["id"],
                    "animal_id": photo["animal_id"],
                    "filename": photo["filename"],
                    "created_at": photo.get("created_at"),
                    "is_default": bool(photo.get("is_default")),
                    "updated_at": photo.get("updated_at"),
                }
            )
            exported_photos += 1

        manifest_animals = [
            {
                "id": a["id"],
                "name": a["name"],
                "species": a["species"],
                "created_at": a["created_at"],
            }
            for a in animals
        ]

        manifest: dict[str, object] = {
            "format_version": FORMAT_VERSION,
            "animals": manifest_animals,
            "sound_count": exported_sounds,
            "sounds": manifest_sounds,
        }
        if include_photos:
            manifest["photos"] = manifest_photos

        zf.writestr(
            zipfile.ZipInfo(MANIFEST_PATH),
            json.dumps(manifest, indent=2),
            compress_type=zipfile.ZIP_DEFLATED,
        )

    if skipped_sounds:
        print_warning(f"Skipped {skipped_sounds} sound(s) with missing WAV files")
    if skipped_photos:
        print_warning(f"Skipped {skipped_photos} photo(s) with missing files")
    msg = f"Exported {exported_sounds} sound(s)"
    if include_photos:
        msg += f", {exported_photos} photo(s)"
    msg += f" to {out_path}"
    print_success(msg)
