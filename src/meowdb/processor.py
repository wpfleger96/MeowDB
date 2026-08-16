from __future__ import annotations

import time
import uuid

from pathlib import Path

import noisereduce
import numpy as np

from pydub import AudioSegment
from pydub.silence import detect_leading_silence
from scipy.signal import butter, sosfilt

from meowdb.models import ProcessingResult, ProcessorConfig, SoundSegment

# Envelope framing shared by the VAD and the canine rise-time test
_FRAME_MS = 10.0
_HOP_MS = 5.0

# Canine unit-splitting and boof spectral shape. These are structural choices about how
# a VAD candidate is decomposed and analyzed, deliberately kept out of the tunable config.
_UNIT_GAP_MS = 100.0  # silence run that splits a VAD candidate into classification units
_UNIT_THRESHOLD_OFFSET_DB = 3.0  # unit-split threshold above the VAD threshold, cuts shallow dips
_LOW_BAND_SPLIT_HZ = 900.0  # boof energy concentrates below this; speech formants above


class SoundProcessor:
    def __init__(self, config: ProcessorConfig | None = None) -> None:
        self.config = config or ProcessorConfig()
        # Native rate of the last loaded file, before resampling to 44100
        self._source_frame_rate: float | None = None

    def process_file(self, path: Path, staging_dir: Path | None = None) -> ProcessingResult:
        start = time.monotonic()

        audio, samples, sr = self._load(path)
        species_band, reference_band = self._build_discriminator_signals(samples, sr)

        candidates = self._detect_segments(species_band, sr)
        classified = self._classify_segments(candidates, species_band, reference_band, sr)
        padded = self._apply_padding(classified, len(samples), sr)

        rejected_count = len(candidates) - len(classified)
        total_candidates = len(candidates)

        output_dir = staging_dir or Path(f"/tmp/meowdb_{uuid.uuid4().hex}")
        output_dir.mkdir(parents=True, exist_ok=True)

        segments: list[SoundSegment] = []
        for i, (start_sample, end_sample, ratio) in enumerate(padded):
            start_ms = int(start_sample / sr * 1000)
            end_ms = int(end_sample / sr * 1000)
            slice_audio = audio[start_ms:end_ms]
            segments.append(
                self._build_segment(
                    slice_audio,
                    i,
                    path,
                    start_ms,
                    end_ms,
                    output_dir,
                    f"{path.stem}_{i:03d}",
                    ratio,
                )
            )

        elapsed = time.monotonic() - start
        return ProcessingResult(
            source_path=path,
            segments=segments,
            rejected_count=rejected_count,
            total_candidates=total_candidates,
            elapsed_seconds=elapsed,
        )

    def process_single(self, path: Path, staging_dir: Path | None = None) -> SoundSegment:
        audio, samples, sr = self._load(path)
        species_band, reference_band = self._build_discriminator_signals(samples, sr)

        ratio = self._band_ratio(species_band, reference_band)

        processed = self._process_segment(audio)
        peak_dbfs = max(float(processed.dBFS), -100.0)

        output_dir = staging_dir or Path(f"/tmp/meowdb_{uuid.uuid4().hex}")
        output_dir.mkdir(parents=True, exist_ok=True)

        wav_path, mp3_path = self._export_segment(processed, output_dir, path.stem)
        waveform = self._compute_waveform(processed)

        duration_ms = len(processed)
        return SoundSegment(
            index=0,
            source_path=path,
            start_ms=0,
            end_ms=duration_ms,
            duration_ms=duration_ms,
            species_energy_ratio=ratio,
            peak_dbfs=peak_dbfs,
            wav_path=wav_path,
            mp3_path=mp3_path,
            waveform_data=waveform,
        )

    def detect_only(self, path: Path) -> list[tuple[int, int]]:
        audio, samples, sr = self._load(path)
        species_band, reference_band = self._build_discriminator_signals(samples, sr)
        candidates = self._detect_segments(species_band, sr)
        classified = self._classify_segments(candidates, species_band, reference_band, sr)
        padded = self._apply_padding(classified, len(samples), sr)
        return [(int(s / sr * 1000), int(e / sr * 1000)) for s, e, _ in padded]

    def process_clips(
        self, path: Path, regions: list[tuple[int, int]], staging_dir: Path
    ) -> list[SoundSegment]:
        audio, samples, sr = self._load(path)
        species_band, reference_band = self._build_discriminator_signals(samples, sr)
        staging_dir.mkdir(parents=True, exist_ok=True)
        segments: list[SoundSegment] = []
        for i, (start_ms, end_ms) in enumerate(regions):
            start_sample = int(start_ms / 1000 * sr)
            end_sample = int(end_ms / 1000 * sr)
            ratio = self._band_ratio(
                species_band[start_sample:end_sample],
                reference_band[start_sample:end_sample],
            )
            slice_audio = audio[start_ms:end_ms]
            segments.append(
                self._build_segment(
                    slice_audio,
                    i,
                    path,
                    start_ms,
                    end_ms,
                    staging_dir,
                    f"clip_{i:03d}",
                    ratio,
                    skip_processing=True,
                )
            )
        return segments

    def _build_segment(
        self,
        audio_slice: AudioSegment,
        index: int,
        source_path: Path,
        start_ms: int,
        end_ms: int,
        staging_dir: Path,
        stem: str,
        species_energy_ratio: float,
        skip_processing: bool = False,
    ) -> SoundSegment:
        processed = audio_slice if skip_processing else self._process_segment(audio_slice)
        peak_dbfs = max(float(processed.dBFS), -100.0)
        wav_path, mp3_path = self._export_segment(processed, staging_dir, stem)
        waveform = self._compute_waveform(processed)
        return SoundSegment(
            index=index,
            source_path=source_path,
            start_ms=start_ms,
            end_ms=end_ms,
            duration_ms=len(processed),
            species_energy_ratio=species_energy_ratio,
            peak_dbfs=peak_dbfs,
            wav_path=wav_path,
            mp3_path=mp3_path,
            waveform_data=waveform,
        )

    def _load(self, path: Path) -> tuple[AudioSegment, np.ndarray, int]:
        audio = AudioSegment.from_file(str(path))
        audio = audio.set_channels(1)
        # Resampling to 44100 cannot invent bandwidth the source never had, so the
        # native rate is what the highpass reference band must be judged against
        self._source_frame_rate = float(audio.frame_rate)
        audio = audio.set_frame_rate(44100)
        samples = self._audio_to_numpy(audio)
        return audio, samples, audio.frame_rate

    @staticmethod
    def _band_ratio(species: np.ndarray, reference: np.ndarray) -> float:
        """RMS of the species band over the reference band (epsilon-guarded)."""
        species_rms = float(np.sqrt(np.mean(species**2)))
        reference_rms = float(np.sqrt(np.mean(reference**2)))
        return species_rms / (reference_rms + 1e-10)

    def _audio_to_numpy(self, audio: AudioSegment) -> np.ndarray:
        raw = np.frombuffer(audio.raw_data, dtype=np.int16)
        return raw.astype(np.float32) / 32768.0

    def _numpy_to_audio(self, samples: np.ndarray, sr: int) -> AudioSegment:
        # Clip before multiply to prevent silent int16 overflow
        clipped = np.clip(samples, -1.0, 1.0)
        int_samples = (clipped * 32768.0).astype(np.int16)
        return AudioSegment(
            int_samples.tobytes(),
            frame_rate=sr,
            sample_width=2,
            channels=1,
        )

    def _build_discriminator_signals(
        self, samples: np.ndarray, sr: int
    ) -> tuple[np.ndarray, np.ndarray]:
        seg = self.config.segmentation
        low_norm = seg.band_low_hz / (sr / 2)
        high_norm = seg.band_high_hz / (sr / 2)
        sos_species = butter(4, [low_norm, high_norm], btype="bandpass", output="sos")
        species_band = sosfilt(sos_species, samples)

        # Reference band: lowpass below the species band (cat: speech F0 + rumble) or
        # highpass above it (dog: broadband non-vocal energy)
        default_cutoff = seg.band_low_hz if seg.reference_mode == "lowpass" else seg.band_high_hz
        cutoff = seg.reference_cutoff_hz if seg.reference_cutoff_hz is not None else default_cutoff
        if seg.reference_mode == "highpass":
            self._require_reference_bandwidth(cutoff)
        sos_ref = butter(4, cutoff / (sr / 2), btype=seg.reference_mode, output="sos")
        reference_band = sosfilt(sos_ref, samples)

        return species_band.astype(np.float32), reference_band.astype(np.float32)

    def _require_reference_bandwidth(self, cutoff_hz: float) -> None:
        """Reject sources too narrowband for the highpass reference to mean anything.

        A source recorded below ~13kHz carries no energy above the highpass cutoff, so
        its reference RMS is numerically zero and the dominance gate passes any sound.
        2kHz is the minimum usable reference bandwidth (16kHz sources still gate).
        """
        rate = self._source_frame_rate
        if rate is None:  # direct call without _load — nothing to judge
            return
        if rate / 2 < cutoff_hz + 2000.0:
            raise ValueError(
                f"source sample rate {rate:g} Hz is too low for reliable dog detection; "
                "record at 16 kHz or higher"
            )

    def _segment_envelope_db(self, samples: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
        """Short-time RMS envelope in dBFS: 10ms frames on a 5ms hop.

        Returns (frame_dbfs, frame_indices) where frame_indices maps each frame
        back to its sample position.
        """
        frame_len = int(sr * _FRAME_MS / 1000.0)
        hop_len = int(sr * _HOP_MS / 1000.0)

        # Short-time mean square via convolution. float32 window keeps the full-length
        # transients out of float64 (a 10-min file would allocate ~740MB otherwise).
        squared = samples**2
        window = np.ones(frame_len, dtype=np.float32) / frame_len
        mean_sq = np.convolve(squared, window, mode="same")

        # Downsample first: sqrt/log10 then run over frames, not every sample
        frame_indices = np.arange(0, len(mean_sq), hop_len)
        framed = np.sqrt(np.maximum(mean_sq[frame_indices], 0.0))

        epsilon = 1e-10
        return 20.0 * np.log10(framed + epsilon), frame_indices

    def _detect_segments(self, species_band: np.ndarray, sr: int) -> list[tuple[int, int]]:
        seg = self.config.segmentation
        frame_dbfs, frame_indices = self._segment_envelope_db(species_band, sr)

        threshold = self._compute_adaptive_threshold(frame_dbfs)
        is_silent = frame_dbfs < threshold

        # Merge silence gaps shorter than min_silence_ms
        min_silence_frames = int(seg.min_silence_ms / _HOP_MS)
        i = 0
        while i < len(is_silent):
            if not is_silent[i]:
                i += 1
                continue
            # Find end of this silence run
            j = i
            while j < len(is_silent) and is_silent[j]:
                j += 1
            silence_len = j - i
            if silence_len < min_silence_frames:
                # Gap too short — fill it (treat as non-silent)
                is_silent[i:j] = False
            i = j

        # Extract candidate segments from non-silent runs
        candidates: list[tuple[int, int]] = []
        in_segment = False
        seg_start = 0
        for fi, silent in enumerate(is_silent):
            sample_pos = frame_indices[fi] if fi < len(frame_indices) else len(species_band)
            if not silent and not in_segment:
                seg_start = int(sample_pos)
                in_segment = True
            elif silent and in_segment:
                seg_end = int(frame_indices[fi] if fi < len(frame_indices) else len(species_band))
                candidates.append((seg_start, seg_end))
                in_segment = False
        if in_segment:
            candidates.append((seg_start, len(species_band)))

        # Split what is too long, drop what is too short
        min_samples = int(seg.min_segment_ms / 1000 * sr)
        max_samples = int(seg.max_segment_ms / 1000 * sr)
        sized: list[tuple[int, int]] = []
        for s, e in candidates:
            sized.extend(
                self._split_to_max(s, e, frame_dbfs, frame_indices, min_samples, max_samples)
            )
        return [(s, e) for s, e in sized if (e - s) >= min_samples]

    def _split_to_max(
        self,
        start: int,
        end: int,
        frame_dbfs: np.ndarray,
        frame_indices: np.ndarray,
        min_samples: int,
        max_samples: int,
    ) -> list[tuple[int, int]]:
        """Cut an over-long candidate at its quietest interior frame until every piece fits.

        A continuous bark volley or howl bout merges into one run that can exceed
        max_segment_ms; dropping it outright loses the whole recording, so it is split
        at the least-energetic moment instead. The cut is confined to the central half:
        margins of only min_samples let each cut land in the same leading silence gap as
        the last one, peeling a 90-bark volley into one sliver per bark instead of
        halving it. Margins never fall below min_samples, so no sub-minimum fragments.
        """
        pieces: list[tuple[int, int]] = []
        pending = [(start, end)]
        while pending:
            s, e = pending.pop()
            if (e - s) <= max_samples:
                pieces.append((s, e))
                continue
            margin = max(min_samples, (e - s) // 4, 1)
            interior = np.flatnonzero((frame_indices >= s + margin) & (frame_indices <= e - margin))
            if len(interior) == 0:
                split = (s + e) // 2
            else:
                split = int(frame_indices[interior[np.argmin(frame_dbfs[interior])]])
            if not s < split < e:  # nothing left to cut
                pieces.append((s, e))
                continue
            pending.extend([(s, split), (split, e)])
        pieces.sort()
        return pieces

    def _compute_adaptive_threshold(self, frame_dbfs: np.ndarray) -> float:
        seg = self.config.segmentation
        if not seg.adaptive_threshold:
            return seg.silence_threshold_dbfs
        active = frame_dbfs[frame_dbfs > -80.0]
        if len(active) < 10:
            return seg.silence_threshold_dbfs
        noise_floor = float(np.percentile(active, seg.adaptive_percentile))
        threshold = noise_floor + seg.adaptive_offset_db
        return max(seg.adaptive_floor_dbfs, min(seg.adaptive_ceiling_dbfs, threshold))

    def _spectral_flatness(self, samples: np.ndarray, sr: int) -> float:
        if len(samples) < 256:
            return 0.0
        seg = self.config.segmentation
        n_fft = 2048
        freq_bins = np.fft.rfftfreq(n_fft, 1.0 / sr)
        mask = (freq_bins >= seg.band_low_hz) & (freq_bins <= seg.band_high_hz)
        if not np.any(mask):
            return 0.0
        window = np.hanning(n_fft)
        flatnesses: list[float] = []
        for start in range(0, len(samples) - n_fft + 1, n_fft):
            spectrum = np.abs(np.fft.rfft(samples[start : start + n_fft] * window)) ** 2
            band = np.maximum(spectrum[mask], 1e-20)
            arith_mean = float(np.mean(band))
            if arith_mean < 1e-18:
                continue
            geo_mean = float(np.exp(np.mean(np.log(band))))
            flatnesses.append(float(np.clip(geo_mean / arith_mean, 0.0, 1.0)))
        if not flatnesses:
            # segment shorter than one full window — analyze whatever we have
            n = len(samples)
            windowed = samples * np.hanning(n)
            spectrum = np.abs(np.fft.rfft(windowed, n=n_fft)) ** 2
            band = np.maximum(spectrum[mask], 1e-20)
            arith_mean = float(np.mean(band))
            if arith_mean < 1e-18:
                return 0.0
            geo_mean = float(np.exp(np.mean(np.log(band))))
            return float(np.clip(geo_mean / arith_mean, 0.0, 1.0))
        return float(np.mean(flatnesses))

    def _rise_time_ms(self, samples: np.ndarray, sr: int) -> float:
        """Attack time: ms from the last frame at/below peak-20dB up to the envelope peak.

        Barks peak within 5-20ms; speech vowels build over 50-150ms. A segment with no
        frame 20dB below its peak has no measurable attack at all — stationary noise
        looks that way — so it returns infinity and fails the impulsive test closed.
        """
        frame_dbfs, _ = self._segment_envelope_db(samples, sr)
        if len(frame_dbfs) == 0:
            return float("inf")
        peak_idx = int(np.argmax(frame_dbfs))
        quiet = np.nonzero(frame_dbfs[: peak_idx + 1] <= frame_dbfs[peak_idx] - 20.0)[0]
        if len(quiet) == 0:
            return float("inf")
        return (peak_idx - int(quiet[-1])) * _HOP_MS

    def _harmonicity(self, samples: np.ndarray, sr: int) -> tuple[float, float, float]:
        """Windowed autocorrelation pitch analysis for the tonal (howl/whine) branch.

        Per 2048-sample Hann window (hop 1024), computes the FFT-based normalized
        autocorrelation r[tau]/r[0] and searches tau for F0 between f0_search_floor_hz
        and max_tonal_f0_hz. The floor sits far below min_tonal_f0_hz on purpose: a
        low-pitched voice must measure its true (too-low) F0 rather than lock the
        half-period peak and report 2xF0 as a howl.

        Returns (voiced_fraction, mean voiced harmonicity, median voiced F0 in Hz);
        all zeros when nothing is voiced.
        """
        can = self.config.segmentation.canine
        n_fft = 2048
        hop = 1024
        tau_min = max(1, int(sr / can.max_tonal_f0_hz))
        tau_max = int(round(sr / can.f0_search_floor_hz))
        if tau_min > tau_max:
            raise ValueError(
                f"f0_search_floor_hz ({can.f0_search_floor_hz:g}) must be below "
                f"max_tonal_f0_hz ({can.max_tonal_f0_hz:g})"
            )
        if len(samples) < n_fft:
            return 0.0, 0.0, 0.0
        window = np.hanning(n_fft)
        n_frames = 0
        voiced_peaks: list[float] = []
        voiced_f0s: list[float] = []
        for start in range(0, len(samples) - n_fft + 1, hop):
            windowed = samples[start : start + n_fft] * window
            # Autocorrelation via FFT (zero-padded to avoid circular wrap)
            spectrum = np.fft.rfft(windowed, n=2 * n_fft)
            autocorr = np.fft.irfft(spectrum * np.conj(spectrum))[: tau_max + 2]
            n_frames += 1
            if autocorr[0] < 1e-12:
                continue
            normalized = autocorr / autocorr[0]
            # A pitch estimate must be a genuine autocorrelation peak: small lags
            # trivially correlate for low-frequency content, so only local maxima
            # count — an F0 below the search range then yields no peak (unvoiced)
            # instead of aliasing to the smallest searchable lag.
            interior = normalized[1:-1]
            is_local_max = (interior > normalized[:-2]) & (interior >= normalized[2:])
            peak_taus = np.nonzero(is_local_max)[0] + 1
            peak_taus = peak_taus[(peak_taus >= tau_min) & (peak_taus <= tau_max)]
            if len(peak_taus) == 0:
                continue
            peak_tau = int(peak_taus[np.argmax(normalized[peak_taus])])
            peak = float(normalized[peak_tau])
            if peak >= can.voiced_peak_threshold:
                voiced_peaks.append(peak)
                voiced_f0s.append(sr / self._refine_tau(normalized, peak_tau))
        if n_frames == 0 or not voiced_peaks:
            return 0.0, 0.0, 0.0
        return (
            len(voiced_peaks) / n_frames,
            float(np.mean(voiced_peaks)),
            float(np.median(voiced_f0s)),
        )

    @staticmethod
    def _refine_tau(normalized: np.ndarray, tau: int) -> float:
        """Sub-sample lag of an autocorrelation peak via 3-point parabolic interpolation.

        Integer lags quantize F0 coarsely enough to straddle min_tonal_f0_hz (tau 176
        and 177 measure 250.6Hz and 249.2Hz), so the vertex is interpolated instead.
        """
        if tau <= 0 or tau >= len(normalized) - 1:
            return float(tau)
        left, center, right = (float(v) for v in normalized[tau - 1 : tau + 2])
        denom = left - 2.0 * center + right
        if denom == 0.0:
            return float(tau)
        offset = 0.5 * (left - right) / denom
        return tau + offset if abs(offset) <= 1.0 else float(tau)

    def _classify_segments(
        self,
        candidates: list[tuple[int, int]],
        species_band: np.ndarray,
        reference_band: np.ndarray,
        sr: int,
    ) -> list[tuple[int, int, float]]:
        if self.config.segmentation.classifier == "canine":
            return self._classify_canine(candidates, species_band, reference_band, sr)
        return self._classify_feline(candidates, species_band, reference_band, sr)

    def _classify_canine(
        self,
        candidates: list[tuple[int, int]],
        species_band: np.ndarray,
        reference_band: np.ndarray,
        sr: int,
    ) -> list[tuple[int, int, float]]:
        """Gate G AND (Sharp OR Bout OR Sustained), evaluated per sub-unit.

        The speech band (300-3400Hz) sits inside the dog band, so no energy ratio can
        separate speech from barks — discrimination comes from temporal and harmonic
        structure. Each candidate is first split into classification units at interior
        quiet runs, so a bark fused with adjacent speech by the VAD is judged on its own.
        Gate G (in-band dominance over the highpass reference) rejects broadband non-vocal
        sound, then a unit is accepted by any one branch:
          Sharp    — a real bark is voiced (not broadband, unlike thumps/knocks), weakly
                      voiced overall (sharp burst plus unvoiced tail), pitched above the
                      speaker's praise-voice (~276Hz median) where this dog measures ~390Hz,
                      with a fast attack.
          Bout     — a sustained, strongly voiced bark volley or howl above praise-voice.
          Sustained — a long "boof": voiced but less harmonic than speech, F0 in the woof
                      range, with energy concentrated in the low band (speech formants sit
                      above it).
        Accepted unit boundaries are emitted, not candidate boundaries; _apply_padding
        already merges the overlapping padded results.
        """
        can = self.config.segmentation.canine
        frame_dbfs, frame_indices = self._segment_envelope_db(species_band, sr)
        unit_threshold = self._compute_adaptive_threshold(frame_dbfs) + _UNIT_THRESHOLD_OFFSET_DB
        # The VAD cuts a candidate at the moment energy crossed the threshold, which is
        # already partway up a bark's attack. Rise time is measured with that much lead
        # restored, or a cropped impulse looks like it has no attack at all.
        attack_lead = int(can.max_attack_ms / 1000 * sr)
        result: list[tuple[int, int, float]] = []
        for cs, ce in candidates:
            for s, e in self._split_units(cs, ce, frame_dbfs, frame_indices, unit_threshold, sr):
                species_slice = species_band[s:e]
                reference_slice = reference_band[s:e]

                # Gate G: in-band dominance (stored as species_energy_ratio). Phrased so a
                # NaN ratio fails closed rather than sliding past a "<" comparison.
                dominance = self._band_ratio(species_slice, reference_slice)
                if not (dominance >= can.min_band_dominance_ratio):
                    continue

                duration_ms = (e - s) / sr * 1000.0
                flatness = self._spectral_flatness(species_slice, sr)
                voiced_fraction, harmonicity, f0_hz = self._harmonicity(species_slice, sr)

                # Sharp bark: voiced (NOT broadband — thumps are broadband), weakly voiced
                # overall (burst + unvoiced tail), pitched above speech, fast attack.
                # Rise time convolves the whole slice, so it is tested last.
                sharp = (
                    flatness <= can.max_sharp_flatness
                    and voiced_fraction <= can.max_sharp_voiced_fraction
                    and f0_hz >= can.min_sharp_f0_hz
                    and self._rise_time_ms(species_band[max(0, s - attack_lead) : e], sr)
                    <= can.max_attack_ms
                )
                # Bark bout / howl: sustained, strongly voiced, pitched above praise-voice.
                bout = (
                    duration_ms >= can.min_tonal_ms
                    and flatness <= can.max_tonal_flatness
                    and voiced_fraction >= can.min_voiced_fraction
                    and harmonicity >= can.min_harmonicity
                    and f0_hz >= can.min_tonal_f0_hz
                )
                # Sustained boof: long, voiced but LESS harmonic than speech, F0 in the
                # canine woof range, energy concentrated in the low band. The PSD ratio
                # is the most expensive test, so it goes last.
                sustained = (
                    duration_ms >= can.min_sustained_ms
                    and voiced_fraction >= can.min_sustained_voiced_fraction
                    and harmonicity <= can.max_sustained_harmonicity
                    and can.min_sustained_f0_hz <= f0_hz <= can.max_sustained_f0_hz
                    and self._low_band_ratio(species_slice, sr) >= can.min_low_band_ratio
                )

                if sharp or bout or sustained:
                    result.append((s, e, dominance))
        return result

    def _split_units(
        self,
        start: int,
        end: int,
        frame_dbfs: np.ndarray,
        frame_indices: np.ndarray,
        threshold: float,
        sr: int,
    ) -> list[tuple[int, int]]:
        """Split one VAD candidate into classification units at interior quiet runs.

        The VAD's min_silence_ms merges a bark with adjacent speech into one candidate
        whose aggregate features look like speech; classifying per burst lets the bark be
        judged alone. Only quiet runs at least _UNIT_GAP_MS long split a unit — shorter
        dips are filled — and the split threshold sits _UNIT_THRESHOLD_OFFSET_DB above the
        VAD threshold to cut the shallow inter-sound dips the VAD threshold rides over.
        If nothing survives the minimum-length filter, the candidate is judged whole.
        """
        m = (frame_indices >= start) & (frame_indices < end)
        env = frame_dbfs[m]
        idx = frame_indices[m]
        silent = (env < threshold).copy()
        gap_frames = int(_UNIT_GAP_MS / _HOP_MS)
        i = 0
        while i < len(silent):  # merge quiet runs shorter than the gap
            if not silent[i]:
                i += 1
                continue
            j = i
            while j < len(silent) and silent[j]:
                j += 1
            if j - i < gap_frames:
                silent[i:j] = False
            i = j
        units: list[tuple[int, int]] = []
        in_unit = False
        unit_start = 0
        for k, is_silent in enumerate(silent):
            if not is_silent and not in_unit:
                unit_start = int(idx[k])
                in_unit = True
            elif is_silent and in_unit:
                units.append((unit_start, int(idx[k])))
                in_unit = False
        if in_unit:
            units.append((unit_start, end))
        min_samples = int(self.config.segmentation.min_segment_ms / 1000 * sr)
        units = [(s, e) for s, e in units if e - s >= min_samples]
        return units or [(start, end)]  # nothing survived — judge the candidate whole

    def _low_band_ratio(self, samples: np.ndarray, sr: int) -> float:
        """PSD energy below _LOW_BAND_SPLIT_HZ over energy above it, within the species band.

        A boof concentrates energy in the bottom of the dog band while speech formants sit
        above _LOW_BAND_SPLIT_HZ, so a bottom-heavy spectrum separates the two. Uses the
        same windowed-FFT idiom as _spectral_flatness (n_fft=2048, Hann, hop 1024, averaged
        power spectrum), zero-padding a short slice up to one full window.
        """
        seg = self.config.segmentation
        n_fft = 2048
        freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
        low_mask = (freqs >= seg.band_low_hz) & (freqs < _LOW_BAND_SPLIT_HZ)
        mid_mask = (freqs >= _LOW_BAND_SPLIT_HZ) & (freqs <= seg.band_high_hz)
        if len(samples) < n_fft:
            padded = np.zeros(n_fft, dtype=samples.dtype)
            padded[: len(samples)] = samples
            samples = padded
        window = np.hanning(n_fft)
        acc = np.zeros(len(freqs))
        count = 0
        for start in range(0, len(samples) - n_fft + 1, 1024):
            acc += np.abs(np.fft.rfft(samples[start : start + n_fft] * window)) ** 2
            count += 1
        psd = acc / max(count, 1)
        return float(psd[low_mask].sum()) / (float(psd[mid_mask].sum()) + 1e-12)

    def _classify_feline(
        self,
        candidates: list[tuple[int, int]],
        species_band: np.ndarray,
        reference_band: np.ndarray,
        sr: int,
    ) -> list[tuple[int, int, float]]:
        seg = self.config.segmentation
        win_samples = max(1, int(seg.peak_ratio_window_ms / 1000 * sr))
        result: list[tuple[int, int, float]] = []
        for s, e in candidates:
            species_slice = species_band[s:e]
            reference_slice = reference_band[s:e]

            # Test 1: whole-segment average ratio
            avg_ratio = self._band_ratio(species_slice, reference_slice)
            test1 = avg_ratio >= seg.min_species_energy_ratio

            # Test 2: peak windowed ratio (rescues short meows diluted by surrounding noise)
            peak_ratio = 0.0
            hop = max(1, win_samples // 2)
            n_wins = (
                max(1, (len(species_slice) - win_samples) // hop + 1)
                if len(species_slice) >= win_samples
                else 1
            )
            for wi in range(n_wins):
                ws = wi * hop
                we = min(ws + win_samples, len(species_slice))
                peak_ratio = max(
                    peak_ratio,
                    self._band_ratio(species_slice[ws:we], reference_slice[ws:we]),
                )
            test2 = peak_ratio >= seg.min_peak_ratio

            # Test 3: spectral flatness (meows are tonal; rejects broadband noise)
            if seg.use_spectral_classifier:
                test3 = self._spectral_flatness(species_slice, sr) <= seg.max_spectral_flatness
            else:
                test3 = True

            if test1 and test2 and test3:
                result.append((s, e, max(avg_ratio, peak_ratio)))
        return result

    def _apply_padding(
        self,
        segments: list[tuple[int, int, float]],
        total_samples: int,
        sr: int,
    ) -> list[tuple[int, int, float]]:
        seg = self.config.segmentation
        pre = int(seg.pre_pad_ms / 1000 * sr)
        post = int(seg.post_pad_ms / 1000 * sr)

        padded: list[tuple[int, int, float]] = []
        for s, e, ratio in segments:
            s = max(0, s - pre)
            e = min(total_samples, e + post)
            padded.append((s, e, ratio))

        # Merge overlapping segments (keep max ratio of merged group)
        if not padded:
            return padded
        padded.sort(key=lambda x: x[0])
        merged: list[tuple[int, int, float]] = [padded[0]]
        for s, e, ratio in padded[1:]:
            prev_s, prev_e, prev_ratio = merged[-1]
            if s <= prev_e:
                merged[-1] = (prev_s, max(prev_e, e), max(prev_ratio, ratio))
            else:
                merged.append((s, e, ratio))
        return merged

    def _process_segment(self, audio: AudioSegment) -> AudioSegment:
        proc = self.config.processing
        sr = audio.frame_rate

        samples = self._audio_to_numpy(audio)
        denoised = noisereduce.reduce_noise(
            y=samples,
            sr=sr,
            stationary=False,
            prop_decrease=proc.noise_reduce_prop_decrease,
        )
        audio = self._numpy_to_audio(denoised, sr)

        current_dbfs = audio.dBFS
        if current_dbfs != float("-inf"):
            gain_db = proc.target_dbfs - current_dbfs
            audio = audio.apply_gain(gain_db)

        samples = self._audio_to_numpy(audio)
        threshold_linear = 10.0 ** (proc.compressor_threshold_dbfs / 20.0)
        ratio = proc.compressor_ratio
        abs_samples = np.abs(samples)
        above = abs_samples > threshold_linear
        gain = np.where(
            above,
            threshold_linear + (abs_samples - threshold_linear) / ratio,
            abs_samples,
        )
        compressed = np.where(abs_samples > 0, samples * (gain / (abs_samples + 1e-10)), samples)
        audio = self._numpy_to_audio(compressed.astype(np.float32), sr)

        start_trim = detect_leading_silence(
            audio, silence_threshold=proc.trim_silence_threshold_dbfs
        )
        reversed_audio = audio.reverse()
        end_trim = detect_leading_silence(
            reversed_audio, silence_threshold=proc.trim_silence_threshold_dbfs
        )

        padding_ms = 50
        start_trim = max(0, start_trim - padding_ms)
        end_ms = len(audio) - max(0, end_trim - padding_ms)
        audio = audio[start_trim:end_ms]

        return audio

    def _export_segment(
        self, audio: AudioSegment, staging_dir: Path, segment_id: str
    ) -> tuple[Path, Path]:
        exp = self.config.export
        wav_path = staging_dir / f"{segment_id}.wav"
        mp3_path = staging_dir / f"{segment_id}.mp3"

        audio.export(
            str(wav_path),
            format="wav",
            parameters=[
                "-ar",
                str(exp.wav_sample_rate),
                "-ac",
                str(exp.wav_channels),
            ],
        )
        audio.export(
            str(mp3_path),
            format="mp3",
            bitrate=exp.mp3_bitrate,
        )
        return wav_path, mp3_path

    def _compute_waveform(self, audio: AudioSegment) -> list[float]:
        samples = self._audio_to_numpy(audio)
        if len(samples) == 0:
            return [0.0]
        sr = audio.frame_rate
        # ~100 samples/sec
        hop = max(1, sr // 100)
        num_frames = max(1, len(samples) // hop)

        n = num_frames * hop
        trimmed = np.abs(samples[:n]).reshape(num_frames, hop)
        envelope_arr = trimmed.max(axis=1)
        max_val = float(envelope_arr.max()) if len(envelope_arr) > 0 else 1.0
        if max_val == 0.0:
            return [0.0] * num_frames
        result: list[float] = (envelope_arr / max_val).tolist()
        return result
