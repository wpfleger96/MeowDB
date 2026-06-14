from __future__ import annotations

import os
import subprocess

from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).parent.parent.parent

MEOW_FILES = [_PROJECT_ROOT / f"Meow {i}.m4a" for i in range(1, 6)]


@pytest.mark.e2e
@pytest.mark.parametrize("meow_path", MEOW_FILES, ids=[p.name for p in MEOW_FILES])
def test_ingest_real_m4a(meow_path: Path, tmp_path: Path) -> None:
    if not meow_path.exists():
        pytest.skip(f"Audio file not available: {meow_path.name}")
    data_dir = str(tmp_path)
    result = subprocess.run(
        ["uv", "run", "meowdb", "ingest", str(meow_path), "--no-review"],
        env={**os.environ, "MEOWDB_DATA_DIR": data_dir},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"ingest failed:\n{result.stderr}"
    mp3_dir = os.path.join(data_dir, "audio", "mp3")
    committed = (
        [f for f in os.listdir(mp3_dir) if f.endswith(".mp3")] if os.path.isdir(mp3_dir) else []
    )
    assert len(committed) > 0, f"No segments committed for {meow_path.name}"
