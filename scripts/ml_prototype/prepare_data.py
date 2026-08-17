"""Data-prep CLI for the offline bark/meow ML prototype.

Slices raw home recordings into candidate audio *units* using the exact production
detection path, mines confirmed positives from the MeowDB library (every library
sound is a user-confirmed positive for its animal's species), and writes/merges a
labels CSV the user hand-edits. The unit population is produced by the shipped
`meowdb` detector so all three classifiers downstream are judged on the identical
candidates the heuristic itself judges.
"""

from __future__ import annotations

import argparse
import csv

from math import gcd
from pathlib import Path

import numpy as np

from scipy.signal import resample_poly

import common

from common import (
    LABELS_COLUMNS,
    LABELS_CSV,
    POSITIVE_LABEL,
    UNITS_DIR,
    ensure_dirs,
    read_wav,
    write_wav_16bit,
)

from meowdb import config as meowdb_config
from meowdb.db import MeowDB
from meowdb.processor import _UNIT_THRESHOLD_OFFSET_DB, SoundProcessor
from meowdb.species import processor_config_for_species
from meowdb.storage import is_s3_key

# Units are written at the production export rate so embeddings see the same audio
# the app stores; the canine highpass-reference guard also needs >=16 kHz bandwidth.
TARGET_SR = 44100


def _sanitize_stem(stem: str) -> str:
    """Filesystem/fold-key-safe recording stem: whitespace collapses to underscores."""
    return "_".join(stem.split())


def _resample_to_target(samples: np.ndarray, sr: int) -> np.ndarray:
    """Resample mono float samples to TARGET_SR (no-op when already there)."""
    if sr == TARGET_SR:
        return samples.astype(np.float32)
    divisor = gcd(TARGET_SR, sr)
    return resample_poly(samples, TARGET_SR // divisor, sr // divisor).astype(np.float32)


def _relax_config(config, *, permissive: bool):  # noqa: ANN001 - ProcessorConfig
    """Optionally widen the candidate-unit detector.

    Lowering the adaptive-threshold offset drops the VAD threshold so quieter and
    partial vocalizations become candidates; lowering min_segment_ms admits shorter
    bursts. Neither touches the classifier knobs, so the detected population widens
    without changing what any downstream classifier decides. Defaults are left exact
    when not permissive.
    """
    if not permissive:
        return config
    seg = config.segmentation
    relaxed = seg.model_copy(
        update={
            "min_segment_ms": max(10, seg.min_segment_ms // 2),
            "adaptive_offset_db": seg.adaptive_offset_db - 5.0,
        }
    )
    return config.model_copy(update={"segmentation": relaxed})


def _row(
    *,
    unit_id: str,
    source_recording: str,
    source_kind: str,
    start_ms: int,
    end_ms: int,
    species: str,
    label: str,
    split_group: str,
) -> dict[str, str]:
    """Build one labels.csv row with columns in the canonical order."""
    return {
        "unit_id": unit_id,
        "source_recording": source_recording,
        "source_kind": source_kind,
        "start_ms": str(start_ms),
        "end_ms": str(end_ms),
        "sample_rate": str(TARGET_SR),
        "species": species,
        "label": label,
        "split_group": split_group,
    }


def _units_for_candidates(
    proc: SoundProcessor,
    species: str,
    species_band: np.ndarray,
    candidates: list[tuple[int, int]],
    sr: int,
) -> list[tuple[int, int]]:
    """Turn VAD candidates into classification units exactly as the classifier does.

    The canine classifier splits each candidate at interior quiet runs before judging
    it (so a bark fused with adjacent speech is scored alone); the feline classifier
    scores each candidate whole. Mirroring that split here means the labeled units are
    precisely the units the heuristic evaluates.
    """
    if species != "dog":
        return list(candidates)
    frame_dbfs, frame_indices = proc._segment_envelope_db(species_band, sr)
    unit_threshold = proc._compute_adaptive_threshold(frame_dbfs) + _UNIT_THRESHOLD_OFFSET_DB
    units: list[tuple[int, int]] = []
    for cs, ce in candidates:
        units.extend(
            proc._split_units(cs, ce, frame_dbfs, frame_indices, unit_threshold, sr)
        )
    return units


def _extract_recording(
    proc: SoundProcessor, species: str, recording: Path
) -> list[dict[str, str]]:
    """Detect units in one raw recording, write their WAVs, return their CSV rows."""
    _audio, samples, sr = proc._load(recording)
    species_band, _reference_band = proc._build_discriminator_signals(samples, sr)
    candidates = proc._detect_segments(species_band, sr)
    units = _units_for_candidates(proc, species, species_band, candidates, sr)

    stem = _sanitize_stem(recording.stem)
    rows: list[dict[str, str]] = []
    for idx, (start, end) in enumerate(units):
        unit_id = f"{stem}__{idx:03d}"
        write_wav_16bit(UNITS_DIR / f"{unit_id}.wav", samples[start:end], TARGET_SR)
        rows.append(
            _row(
                unit_id=unit_id,
                source_recording=recording.name,
                source_kind="raw",
                start_ms=int(start / sr * 1000),
                end_ms=int(end / sr * 1000),
                species=species,
                label="",
                split_group=stem,  # leave-one-recording-out fold key
            )
        )
    return rows


def _resolve_library_wav(wav_path_str: str) -> Path | None:
    """Resolve a stored sounds.wav_path to a local file, or None if unavailable.

    Local committed media is stored as an absolute path; S3-mode media is stored as a
    relative object key whose local mirror lives under the meowdb data dir. Anything
    that does not resolve to an existing file (e.g. S3-only clips) is skipped.
    """
    if not wav_path_str:
        return None
    path = Path(wav_path_str) if not is_s3_key(wav_path_str) else meowdb_config.DATA_DIR / wav_path_str
    return path if path.exists() else None


def _mine_library(species: str) -> list[dict[str, str]]:
    """Copy every library sound of `species` into units/ as a prefilled positive row.

    Returns [] with a printed note (never raises) when the DB or data dir is absent,
    so raw-only prep still works on a machine without a MeowDB install.
    """
    if not meowdb_config.DB_PATH.exists():
        print(f"note: MeowDB database not found at {meowdb_config.DB_PATH}; skipping library mining")
        return []

    db = MeowDB(meowdb_config.DB_PATH)
    try:
        species_by_id = db.get_sound_species_groups()
        wav_rows = db.get_all_wav_paths()
    finally:
        db.close()

    positive = POSITIVE_LABEL[species]
    rows: list[dict[str, str]] = []
    missing = 0
    for entry in wav_rows:
        sound_id = entry["id"]
        if species_by_id.get(sound_id) != species:
            continue
        source = _resolve_library_wav(entry.get("wav_path", ""))
        if source is None:
            missing += 1
            continue

        samples, sr = read_wav(source)
        samples = _resample_to_target(samples, sr)
        unit_id = f"library__{sound_id}"
        write_wav_16bit(UNITS_DIR / f"{unit_id}.wav", samples, TARGET_SR)
        rows.append(
            _row(
                unit_id=unit_id,
                source_recording=source.name,
                source_kind="library",
                start_ms=0,
                end_ms=int(len(samples) / TARGET_SR * 1000),
                species=species,
                label=positive,  # library sounds are user-confirmed positives
                split_group=unit_id,  # each library clip is its own fold group
            )
        )
    if missing:
        print(f"note: {missing} library {species} sound(s) had no locally resolvable WAV; skipped")
    return rows


def _merge_and_write(new_rows: list[dict[str, str]]) -> tuple[int, int]:
    """Merge new rows into labels.csv, preserving hand-edited labels.

    Every existing row whose unit WAV still exists is kept verbatim (crucially its
    hand-edited `label`); only rows for genuinely new unit_ids are appended. Returns
    (total_rows, rows_needing_labels).
    """
    preserved: list[dict[str, str]] = []
    known: set[str] = set()
    if LABELS_CSV.exists():
        with LABELS_CSV.open(newline="") as handle:
            for row in csv.DictReader(handle):
                unit_id = row.get("unit_id", "")
                if unit_id and (UNITS_DIR / f"{unit_id}.wav").exists():
                    preserved.append({col: row.get(col, "") for col in LABELS_COLUMNS})
                    known.add(unit_id)

    appended = [row for row in new_rows if row["unit_id"] not in known]
    merged = preserved + appended

    with LABELS_CSV.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LABELS_COLUMNS)
        writer.writeheader()
        writer.writerows(merged)

    needing = sum(1 for row in merged if not row["label"])
    return len(merged), needing


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Slice raw recordings into labeled candidate units for the ML prototype."
    )
    parser.add_argument("--species", choices=("dog", "cat"), default="dog")
    parser.add_argument(
        "--raw-recording",
        action="append",
        default=[],
        metavar="PATH",
        help="Raw recording to slice into units (repeatable).",
    )
    parser.add_argument(
        "--mine-library",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Mine confirmed positives from the MeowDB library.",
    )
    parser.add_argument(
        "--permissive",
        action="store_true",
        help="Widen the candidate-unit detector (lower threshold, shorter minimum).",
    )
    args = parser.parse_args()

    ensure_dirs()

    config = _relax_config(processor_config_for_species(args.species), permissive=args.permissive)
    proc = SoundProcessor(config)

    new_rows: list[dict[str, str]] = []
    per_recording: list[tuple[str, int]] = []
    for raw in args.raw_recording:
        rows = _extract_recording(proc, args.species, Path(raw))
        per_recording.append((raw, len(rows)))
        new_rows.extend(rows)

    library_count = 0
    if args.mine_library:
        library_rows = _mine_library(args.species)
        library_count = len(library_rows)
        new_rows.extend(library_rows)

    total, needing = _merge_and_write(new_rows)

    print()
    print(f"Species: {args.species}{'  (permissive detector)' if args.permissive else ''}")
    for raw, count in per_recording:
        print(f"  {count:4d} units from {raw}")
    if args.mine_library:
        print(f"  {library_count:4d} library positives mined")
    print(f"labels.csv now has {total} rows; {needing} still need a label.")
    print(f"Next: edit {LABELS_CSV}, then run `just ml-embed`.")


if __name__ == "__main__":
    main()
