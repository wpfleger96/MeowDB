"""Build-time script: content-hash JS/CSS assets and rewrite index.html references."""

import hashlib
import re
import shutil
from pathlib import Path

STATIC_DIR = Path("src/meowdb/static")
INDEX_HTML = STATIC_DIR / "index.html"
HASH_RE = re.compile(r"\.[0-9a-f]{8}$")


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:8]


def already_hashed(stem: str) -> bool:
    # stem may be "alpine.min" — split on all dots and check last segment
    return bool(HASH_RE.search(stem))


def main() -> None:
    mapping: dict[str, str] = {}

    for src in sorted(STATIC_DIR.rglob("*")):
        if src.suffix not in {".js", ".css"}:
            continue
        if not src.is_file():
            continue

        # For "alpine.min.js": stem="alpine.min", suffix=".js"
        stem = src.stem
        if already_hashed(stem):
            continue

        h = file_hash(src)
        hashed_name = f"{stem}.{h}{src.suffix}"
        dest = src.with_name(hashed_name)
        shutil.copy2(src, dest)

        # URLs in index.html are rooted at /static/...; STATIC_DIR is the "static" dir
        rel_original = "/static/" + src.relative_to(STATIC_DIR).as_posix()
        rel_hashed = "/static/" + dest.relative_to(STATIC_DIR).as_posix()
        mapping[rel_original] = rel_hashed
        print(f"  {src.name} -> {hashed_name}")

    html = INDEX_HTML.read_text()
    for original, hashed in mapping.items():
        html = html.replace(original, hashed)
    INDEX_HTML.write_text(html)

    print(f"build.py: hashed {len(mapping)} asset(s), rewrote index.html")


if __name__ == "__main__":
    main()
