"""Extract AST embeddings + zero-shot AudioSet logits for every labeled unit.

For each hand-labeled audio unit this computes a frozen 768-dim AST embedding and
the 527-dim AudioSet logit vector, caching both by audio content hash so re-runs
only touch units that are actually new. train_eval.py joins labels to these
vectors through the manifest this script regenerates each run.

The heavy model (torch/transformers) is loaded lazily inside
`common.ast_embedding_and_logits`, and that function is only ever called when a
unit misses the cache — so an all-cache-hit run completes with no ML deps
installed. Keep it that way: never touch the model outside the cache-miss branch.
"""

from __future__ import annotations

import argparse
import csv
import sys

from pathlib import Path

import numpy as np

# The prototype dir is not a package; put it on the path so `import common` works
# no matter the cwd (script run, `-m`, or imported by a throwaway test harness).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    CACHE_DIR,
    LABELS_CSV,
    MANIFEST_CSV,
    UNITS_DIR,
    ast_embedding_and_logits,
    content_hash,
    ensure_dirs,
    read_wav,
    resample_to_16k,
)

DOWNLOAD_NOTE = (
    "  (first model load downloads the ~350 MB AST checkpoint via transformers)"
)


def load_labeled_rows(labels_path: Path) -> tuple[list[dict[str, str]], int]:
    """Return (rows with a non-blank label, count of blank-label rows skipped).

    Fails loudly if the CSV is absent — that means prepare_data has not run yet.
    """
    if not labels_path.exists():
        raise SystemExit(
            f"labels CSV not found: {labels_path}\n"
            "Run prepare_data.py first to slice units and create the labels file."
        )
    labeled: list[dict[str, str]] = []
    unlabeled = 0
    with labels_path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            if (row.get("label") or "").strip():
                labeled.append(row)
            else:
                unlabeled += 1
    return labeled, unlabeled


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Compute cached AST embeddings + zero-shot logits for labeled units."
    )
    parser.add_argument(
        "--labels",
        type=Path,
        default=LABELS_CSV,
        help=f"labels CSV to read (default: {LABELS_CSV})",
    )
    args = parser.parse_args(argv)

    ensure_dirs()
    labeled, unlabeled = load_labeled_rows(args.labels)
    if unlabeled:
        print(f"{unlabeled} unlabeled units skipped — label them in labels.csv")

    total = len(labeled)
    computed = cache_hits = skipped_missing = 0
    manifest_rows: list[tuple[str, str]] = []

    for index, row in enumerate(labeled, start=1):
        unit_id = row["unit_id"]
        wav_path = UNITS_DIR / f"{unit_id}.wav"
        if not wav_path.exists():
            print(f"  [{index}/{total}] {unit_id}: WAV missing at {wav_path} — skipped")
            skipped_missing += 1
            continue

        samples_16k = resample_to_16k(*read_wav(wav_path))
        digest = content_hash(samples_16k)
        cache_path = CACHE_DIR / f"{digest}.npz"

        if cache_path.exists():
            cache_hits += 1
            print(f"  [{index}/{total}] {unit_id}: cache hit")
        else:
            if computed == 0:  # first compute of the run — warn about the download
                print(DOWNLOAD_NOTE)
            embedding, zeroshot_logits = ast_embedding_and_logits(samples_16k)
            np.savez(cache_path, embedding=embedding, zeroshot_logits=zeroshot_logits)
            computed += 1
            print(f"  [{index}/{total}] {unit_id}: computed")

        manifest_rows.append((unit_id, digest))

    # Regenerate the manifest in full every run so it exactly mirrors the current
    # labeled set (a removed/relabeled unit must not linger from a prior run).
    with MANIFEST_CSV.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["unit_id", "content_hash"])
        writer.writerows(manifest_rows)

    print(
        f"\n{total} labeled units — {computed} computed, {cache_hits} cache hits, "
        f"{skipped_missing} missing/skipped"
    )
    print(f"Manifest: {MANIFEST_CSV}")


if __name__ == "__main__":
    main()
