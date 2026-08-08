from __future__ import annotations

import logging

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from pydub import AudioSegment
from scipy.fft import dct

from meowdb.species import DEFAULT_SPECIES, get_species_config

if TYPE_CHECKING:
    from meowdb.db import MeowDB

_logger = logging.getLogger(__name__)


def _compute_group_scores(
    sim_scorer: SoundSimilarity,
    fingerprints: dict[str, list[float]],
    group_map: dict[str, str],
) -> dict[str, float | None]:
    """Partition sounds by group key and score each pool independently.

    Only sounds that appear in both ``fingerprints`` and ``group_map`` are
    included.  Sounds with no fingerprint are silently skipped; their existing
    DB scores are left untouched by the caller.

    Args:
        sim_scorer: Any SoundSimilarity instance — scoring is band-independent.
        fingerprints: {sound_id: feature_vector} for all sounds with fingerprints.
        group_map: {sound_id: group_key} defining the pools (e.g. animal_id or species).

    Returns:
        Flat {sound_id: percentile | None} covering every sound that has both a
        fingerprint and a group key.  A pool of one yields None for that sound.
    """
    pools: dict[str, list[str]] = {}
    for sound_id, group_key in group_map.items():
        if sound_id in fingerprints:
            pools.setdefault(group_key, []).append(sound_id)

    results: dict[str, float | None] = {}
    for ids in pools.values():
        pool_fps = {sid: fingerprints[sid] for sid in ids}
        results.update(sim_scorer.compute_uniqueness_scores(pool_fps))
    return results


def update_library_uniqueness(
    db: MeowDB,
    new_sound_ids: list[str],
    *,
    force: bool = False,
    fingerprints: dict[str, list[float]] | None = None,
) -> None:
    """Extract fingerprints for new sounds, then recompute both uniqueness scores.

    Args:
        db: Open MeowDB instance.
        new_sound_ids: Sound IDs just added to the library.  Fingerprints are
            extracted for any of these that are missing one.
        force: When True, re-extract fingerprints for **all** sounds in the DB
            using their species-appropriate frequency bands (useful after band
            config changes or file fixes).  ``new_sound_ids`` is ignored.
        fingerprints: Pre-loaded fingerprint dict {sound_id: feature_vector}.
            When provided and ``force`` is False, skips the DB fetch for the
            existing fingerprint set (avoids a redundant round-trip when the
            caller already holds the dict).  Ignored when ``force`` is True
            because force re-extracts all fingerprints from scratch.

    Each sound receives two percentile scores:
    - ``animal_uniqueness_score``: rank within the same animal's sound pool.
    - ``species_uniqueness_score``: rank within all sounds of the same species.

    Only sounds whose scores were computed in this call are written; sounds
    absent from the results dict (e.g. no fingerprint) keep their existing
    scores in the DB.
    """
    species_map = db.get_sound_species_groups()
    all_wav_paths = {r["id"]: r["wav_path"] for r in db.get_all_wav_paths()}
    # Re-use caller-supplied fingerprints when available and not force (avoids a
    # redundant DB round-trip when the caller already fetched the full dict).
    if fingerprints is not None and not force:
        fingerprints = dict(fingerprints)  # copy — extraction loop mutates this
    else:
        fingerprints = db.get_all_fingerprints()

    # Cache one SoundSimilarity extractor per species so we pay the filterbank
    # build cost at most once per species per call.
    extractors: dict[str, SoundSimilarity] = {}

    ids_to_extract: list[str] = list(all_wav_paths) if force else new_sound_ids

    # Collect newly extracted fingerprints for a single bulk write after the loop.
    new_fingerprints: dict[str, list[float]] = {}
    for sound_id in ids_to_extract:
        if (force or sound_id not in fingerprints) and sound_id in all_wav_paths:
            try:
                species = species_map.get(sound_id, DEFAULT_SPECIES)
                if species not in extractors:
                    cfg = get_species_config(species)
                    extractors[species] = SoundSimilarity(fmin=cfg.fmin, fmax=cfg.fmax)
                fp = extractors[species].extract_fingerprint(all_wav_paths[sound_id])
                new_fingerprints[sound_id] = fp
                fingerprints[sound_id] = fp
            except Exception as exc:
                _logger.warning("Failed to extract fingerprint for %s: %s", sound_id, exc)

    if new_fingerprints:
        db.update_fingerprints_bulk(new_fingerprints)

    if fingerprints:
        # Band choice doesn't affect scoring math; use a single default instance.
        scorer = SoundSimilarity()
        animal_scores = _compute_group_scores(scorer, fingerprints, db.get_sound_animal_groups())
        species_scores = _compute_group_scores(scorer, fingerprints, species_map)
        db.update_uniqueness_scores_bulk(animal_scores, species_scores)


class SoundSimilarity:
    """MFCC-based audio fingerprinting and uniqueness scoring for sound comparison."""

    def __init__(
        self,
        n_mfcc: int = 20,
        n_mels: int = 40,
        fmin: float = 250.0,
        fmax: float = 8000.0,
        sr: int = 44100,
        n_fft: int = 2048,
        hop_length: int = 512,
        k_neighbors: int = 3,
    ) -> None:
        self.n_mfcc = n_mfcc
        self.n_fft = n_fft
        self.hop_length = hop_length
        self.sr = sr
        self.k_neighbors = k_neighbors
        self._filterbank = self._build_mel_filterbank(n_mels, fmin, fmax, sr, n_fft)

    def _build_mel_filterbank(
        self, n_mels: int, fmin: float, fmax: float, sr: int, n_fft: int
    ) -> np.ndarray:
        def hz_to_mel(hz: float) -> float:
            return float(2595.0 * np.log10(1.0 + hz / 700.0))

        def mel_to_hz(mel: float) -> float:
            return float(700.0 * (10.0 ** (mel / 2595.0) - 1.0))

        mel_min = hz_to_mel(fmin)
        mel_max = hz_to_mel(fmax)
        mel_points = np.linspace(mel_min, mel_max, n_mels + 2)
        hz_points = np.array([mel_to_hz(m) for m in mel_points])
        # Map Hz to FFT bin indices
        bin_points = np.floor((n_fft + 1) * hz_points / sr).astype(int)

        n_bins = n_fft // 2 + 1
        filterbank = np.zeros((n_mels, n_bins))
        for m in range(n_mels):
            left, center, right = bin_points[m], bin_points[m + 1], bin_points[m + 2]
            for k in range(left, center):
                if center != left:
                    filterbank[m, k] = (k - left) / (center - left)
            for k in range(center, right):
                if right != center:
                    filterbank[m, k] = (right - k) / (right - center)
        return filterbank

    def _compute_deltas(self, frames: np.ndarray) -> np.ndarray:
        n_frames, _ = frames.shape
        if n_frames < 5:
            return np.zeros(frames.shape, dtype=np.float64)
        # Repeat boundary frames rather than zero-padding to avoid artificial transients at edges
        padded = np.concatenate([frames[[0, 0]], frames, frames[[-1, -1]]], axis=0)
        return (2 * padded[4:] + padded[3:-1] - padded[1:-3] - 2 * padded[:-4]) / 10.0  # type: ignore[no-any-return]

    def _apply_pcen(self, mel_energies: np.ndarray) -> np.ndarray:
        s, alpha, delta, r, eps = 0.025, 0.98, 2.0, 0.5, 1e-6
        n_frames, _ = mel_energies.shape
        pcen = np.zeros_like(mel_energies)
        M = mel_energies[0].copy()
        for t in range(n_frames):
            E = mel_energies[t]
            M = (1 - s) * M + s * E
            pcen[t] = (E / (eps + M) ** alpha + delta) ** r - delta**r
        return pcen

    def extract_fingerprint(self, wav_path: str | Path) -> list[float]:
        """Return a 120-dim feature vector for the sound (static + delta + delta-delta MFCCs, each mean+std)."""
        audio = AudioSegment.from_wav(str(wav_path))
        audio = audio.set_channels(1).set_frame_rate(self.sr)
        samples = np.array(audio.get_array_of_samples(), dtype=np.float32)
        # Normalize to [-1, 1] based on bit depth
        samples /= float(2 ** (audio.sample_width * 8 - 1))

        window = np.hanning(self.n_fft)
        n_frames = max(1, (len(samples) - self.n_fft) // self.hop_length + 1)

        mel_frames: list[np.ndarray] = []
        for i in range(n_frames):
            start = i * self.hop_length
            frame = samples[start : start + self.n_fft]
            if len(frame) < self.n_fft:
                frame = np.pad(frame, (0, self.n_fft - len(frame)))
            power = np.abs(np.fft.rfft(frame * window)) ** 2
            mel_frames.append(self._filterbank @ power)

        mel_matrix = np.stack(mel_frames)  # (n_frames, n_mels)
        pcen_energies = self._apply_pcen(mel_matrix)

        mfcc_frames = [
            dct(pcen_energies[i], type=2, norm="ortho")[: self.n_mfcc] for i in range(n_frames)
        ]
        frames_arr = np.stack(mfcc_frames)  # (n_frames, n_mfcc)

        deltas = self._compute_deltas(frames_arr)
        delta_deltas = self._compute_deltas(deltas)

        parts = []
        for mat in (frames_arr, deltas, delta_deltas):
            parts.append(mat.mean(axis=0))
            parts.append(mat.std(axis=0))

        return list(np.concatenate(parts).astype(float))

    def compute_uniqueness_scores(
        self, fingerprints: dict[str, list[float]]
    ) -> dict[str, float | None]:
        """Return {sound_id: uniqueness_percentile} for all sounds.

        Score is the percentile rank of each sound's raw uniqueness relative to the pool.
        A pool of one sound returns None (percentile rank is undefined with no peers).
        """
        ids = list(fingerprints.keys())
        if len(ids) == 0:
            return {}
        if len(ids) == 1:
            return {ids[0]: None}

        matrix = np.array([fingerprints[i] for i in ids], dtype=np.float64)

        col_std = matrix.std(axis=0)
        col_std[col_std == 0] = 1.0  # avoid divide-by-zero for constant features
        matrix = (matrix - matrix.mean(axis=0)) / col_std

        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        normalized = matrix / norms
        sim_matrix = normalized @ normalized.T

        raw_uniqueness: dict[str, float] = {}
        for idx, sound_id in enumerate(ids):
            row = sim_matrix[idx].copy()
            row[idx] = -np.inf  # exclude self
            k = min(self.k_neighbors, len(ids) - 1)  # graceful degradation
            # np.partition is O(N), faster than full sort
            top_k = np.partition(row, -k)[-k:]
            avg_sim = float(np.mean(np.clip(top_k, 0.0, 1.0)))
            raw_uniqueness[sound_id] = 1.0 - avg_sim

        raw_vals = np.array([raw_uniqueness[sid] for sid in ids])
        scores: dict[str, float | None] = {}
        for idx, sound_id in enumerate(ids):
            n_below = int(np.sum(raw_vals < raw_vals[idx]))
            pct = round(n_below / (len(ids) - 1) * 100.0, 1) if len(ids) > 1 else 0.0
            scores[sound_id] = pct
        return scores
