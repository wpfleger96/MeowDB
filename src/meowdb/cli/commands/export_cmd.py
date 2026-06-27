from __future__ import annotations

import json
import zipfile

from datetime import date
from pathlib import Path

import click

from meowdb.cli.helpers import build_context
from meowdb.cli.options import db_path_option
from meowdb.config import PHOTOS_DIR
from meowdb.display import print_success, print_warning

_MANIFEST_PATH = "meowdb-export/manifest.json"
_AUDIO_PREFIX = "meowdb-export/audio/"
_PHOTOS_PREFIX = "meowdb-export/photos/"
_FORMAT_VERSION = 1

_PORTABLE_FIELDS = {
    "id",
    "timestamp",
    "duration_ms",
    "labels",
    "play_count",
    "last_played",
    "created_at",
    "waveform_data",
    "peak_dbfs",
    "cat_energy_ratio",
    "recorded_at",
    "title",
    "upvote_count",
    "downvote_count",
}


@click.command(name="export")
@click.argument("output", type=click.Path(dir_okay=False), default=None, required=False)
@click.option(
    "--include-photos", is_flag=True, default=False, help="Include cat photos in the archive."
)
@db_path_option
def export_meows(output: str | None, include_photos: bool, db_path: str | None) -> None:
    """Export the meow library to a portable zip archive."""
    ctx = build_context(Path(db_path) if db_path else None)
    meows = ctx.db.get_all_for_export()
    photos = ctx.db.get_photos() if include_photos else []
    ctx.db.close()

    out_path = Path(output) if output else Path(f"meowdb-export-{date.today()}.zip")

    exported_meows = 0
    skipped_meows = 0
    exported_photos = 0
    skipped_photos = 0
    manifest_meows = []
    manifest_photos = []

    with zipfile.ZipFile(out_path, "w") as zf:
        for meow in meows:
            wav_path = Path(meow.get("wav_path") or "")
            if not wav_path.exists():
                print_warning(f"Missing WAV for {meow['id'][:8]}, skipping")
                skipped_meows += 1
                continue
            zf.write(
                wav_path, _AUDIO_PREFIX + meow["id"] + ".wav", compress_type=zipfile.ZIP_STORED
            )
            manifest_meows.append({k: v for k, v in meow.items() if k in _PORTABLE_FIELDS})
            exported_meows += 1

        for photo in photos:
            photo_path = PHOTOS_DIR / photo["filename"]
            if not photo_path.exists():
                print_warning(f"Missing photo file for {photo['id'][:8]}, skipping")
                skipped_photos += 1
                continue
            zf.write(
                photo_path, _PHOTOS_PREFIX + photo["filename"], compress_type=zipfile.ZIP_STORED
            )
            manifest_photos.append(
                {
                    "id": photo["id"],
                    "filename": photo["filename"],
                    "created_at": photo.get("created_at"),
                    "is_default": bool(photo.get("is_default")),
                    "updated_at": photo.get("updated_at"),
                }
            )
            exported_photos += 1

        manifest: dict[str, object] = {
            "format_version": _FORMAT_VERSION,
            "meow_count": exported_meows,
            "meows": manifest_meows,
        }
        if include_photos:
            manifest["photos"] = manifest_photos

        zf.writestr(
            zipfile.ZipInfo(_MANIFEST_PATH),
            json.dumps(manifest, indent=2),
            compress_type=zipfile.ZIP_DEFLATED,
        )

    if skipped_meows:
        print_warning(f"Skipped {skipped_meows} meow(s) with missing WAV files")
    if skipped_photos:
        print_warning(f"Skipped {skipped_photos} photo(s) with missing files")
    msg = f"Exported {exported_meows} meow(s)"
    if include_photos:
        msg += f", {exported_photos} photo(s)"
    msg += f" to {out_path}"
    print_success(msg)
