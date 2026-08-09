from __future__ import annotations

from pathlib import Path

import pytest

from PIL import Image

from meowdb.photos import optimize_photo  # triggers register_heif_opener() at module level


@pytest.mark.unit
def test_optimize_photo_converts_heic_to_webp(tmp_path: Path) -> None:
    src = tmp_path / "sample.heic"
    Image.new("RGB", (64, 48), (200, 100, 50)).save(str(src), format="HEIF")

    result = optimize_photo(src)

    assert result.suffix == ".webp"
    with Image.open(result) as img:
        assert img.format == "WEBP"
        assert img.size == (64, 48)
