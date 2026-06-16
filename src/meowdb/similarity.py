from __future__ import annotations

from pathlib import Path

import numpy as np

from pydub import AudioSegment
from scipy.fft import dct


class MeowSimilarity:
    """MFCC-based audio fingerprinting and uniqueness scoring for meow comparison."""

    def __init__(
        self,
        n_mfcc: int = 13,
        n_mels: int = 26,
        fmin: float = 250.0,
        fmax: float = 5000.0,
        sr: int = 44100,
        n_fft: int = 2048,
        hop_length: int = 512,
    ) -> None:
        self.n_mfcc = n_mfcc
        self.n_fft = n_fft
        self.hop_length = hop_length
        self.sr = sr
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

    def extract_fingerprint(self, wav_path: str | Path) -> list[float]:
        """Return a 26-dim feature vector (13 MFCC means + 13 MFCC stds) for the meow."""
        audio = AudioSegment.from_wav(str(wav_path))
        audio = audio.set_channels(1).set_frame_rate(self.sr)
        samples = np.array(audio.get_array_of_samples(), dtype=np.float32)
        # Normalize to [-1, 1] based on bit depth
        samples /= float(2 ** (audio.sample_width * 8 - 1))

        window = np.hanning(self.n_fft)
        n_frames = max(1, (len(samples) - self.n_fft) // self.hop_length + 1)

        mfcc_frames: list[np.ndarray] = []
        for i in range(n_frames):
            start = i * self.hop_length
            frame = samples[start : start + self.n_fft]
            if len(frame) < self.n_fft:
                frame = np.pad(frame, (0, self.n_fft - len(frame)))
            power = np.abs(np.fft.rfft(frame * window)) ** 2
            mel_energy = self._filterbank @ power
            # Floor at small positive value before log to avoid -inf
            log_mel = np.log(np.maximum(mel_energy, 1e-10))
            mfcc = dct(log_mel, type=2, norm="ortho")[: self.n_mfcc]
            mfcc_frames.append(mfcc)

        frames_arr = np.stack(mfcc_frames)  # (n_frames, n_mfcc)
        means = frames_arr.mean(axis=0)
        stds = frames_arr.std(axis=0)
        return list(np.concatenate([means, stds]).astype(float))

    def compute_uniqueness_scores(self, fingerprints: dict[str, list[float]]) -> dict[str, float]:
        """Return {meow_id: uniqueness_score} for all meows.

        Uniqueness = (1 - cosine_similarity_to_nearest_neighbor) * 100.
        A library of one meow returns 100.0 for that meow.
        """
        ids = list(fingerprints.keys())
        if len(ids) == 0:
            return {}
        if len(ids) == 1:
            return {ids[0]: 100.0}

        matrix = np.array([fingerprints[i] for i in ids], dtype=np.float64)

        # Z-score normalize each feature dimension across the library
        col_std = matrix.std(axis=0)
        col_std[col_std == 0] = 1.0  # avoid divide-by-zero for constant features
        matrix = (matrix - matrix.mean(axis=0)) / col_std

        # Cosine similarity: normalize rows, then dot product
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        normalized = matrix / norms
        # Full pairwise similarity matrix (N x N)
        sim_matrix = normalized @ normalized.T

        scores: dict[str, float] = {}
        for idx, meow_id in enumerate(ids):
            row = sim_matrix[idx].copy()
            row[idx] = -np.inf  # exclude self-similarity
            max_sim = float(np.max(row))
            # Clamp to [0, 1] — cosine sim on z-scored data can go negative
            max_sim = max(0.0, min(1.0, max_sim))
            scores[meow_id] = round((1.0 - max_sim) * 100.0, 1)
        return scores
