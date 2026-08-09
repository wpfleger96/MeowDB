from __future__ import annotations

import json
import tempfile
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
        from meowdb.storage import (
            S3NotFoundError,
            download_from_s3_sync,
            is_s3_enabled,
            is_s3_key,
            photo_key,
        )

        s3_enabled = is_s3_enabled()

        for sound in sounds:
            wav_val = sound.get("wav_path") or ""
            arc_name = AUDIO_PREFIX + sound["id"] + ".wav"
            if is_s3_key(wav_val):
                if s3_enabled:
                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
                        tmp = Path(tf.name)
                    try:
                        download_from_s3_sync(wav_val, tmp)
                        zf.write(tmp, arc_name, compress_type=zipfile.ZIP_STORED)
                    except S3NotFoundError:
                        print_warning(f"Missing WAV in S3 for {sound['id'][:8]}, skipping")
                        skipped_sounds += 1
                        continue
                    finally:
                        tmp.unlink(missing_ok=True)
                else:
                    print_warning(f"Missing WAV for {sound['id'][:8]}, skipping")
                    skipped_sounds += 1
                    continue
            else:
                wav_path = Path(wav_val)
                if not wav_path.exists():
                    print_warning(f"Missing WAV for {sound['id'][:8]}, skipping")
                    skipped_sounds += 1
                    continue
                zf.write(wav_path, arc_name, compress_type=zipfile.ZIP_STORED)
            manifest_sounds.append({k: v for k, v in sound.items() if k in _PORTABLE_FIELDS})
            exported_sounds += 1

        for photo in photos:
            filename = photo["filename"]
            photo_path = PHOTOS_DIR / filename
            arc_name = PHOTOS_PREFIX + filename
            if photo_path.exists():
                zf.write(photo_path, arc_name, compress_type=zipfile.ZIP_STORED)
            elif s3_enabled:
                suffix = Path(filename).suffix or ".tmp"
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
                    tmp = Path(tf.name)
                try:
                    download_from_s3_sync(photo_key(filename), tmp)
                    zf.write(tmp, arc_name, compress_type=zipfile.ZIP_STORED)
                except S3NotFoundError:
                    print_warning(f"Missing photo in S3 for {photo['id'][:8]}, skipping")
                    skipped_photos += 1
                    continue
                finally:
                    tmp.unlink(missing_ok=True)
            else:
                print_warning(f"Missing photo file for {photo['id'][:8]}, skipping")
                skipped_photos += 1
                continue

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
