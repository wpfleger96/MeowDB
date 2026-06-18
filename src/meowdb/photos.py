from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps


def optimize_photo(src: Path) -> Path:
    dest = src.with_suffix(".webp")
    with Image.open(src) as raw:
        img = ImageOps.exif_transpose(raw)
        max_dim = 1200
        if max(img.width, img.height) > max_dim:
            img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
        img.save(dest, format="WEBP", quality=85)
    return dest
