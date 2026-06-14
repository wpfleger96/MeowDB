from __future__ import annotations

import time
import uuid

from pathlib import Path

import noisereduce
import numpy as np

from pydub import AudioSegment
from pydub.silence import detect_leading_silence
from scipy.signal import butter, sosfilt

from meowdb.models import MeowSegment, ProcessingResult, ProcessorConfig


class MeowProcessor:
    def __init__(self, config: ProcessorConfig | None = None) -> None:
        self.config = config or ProcessorConfig()

    def process_file(self, path: Path, staging_dir: Path | None = None) -> ProcessingResult:
        start = time.monotonic()

        audio, samples, sr = self._load(path)
        cat_band, low_band = self._build_discriminator_signals(samples, sr)

        candidates = self._detect_segments(cat_band, sr)
        classified = self._classify_segments(candidates, cat_band, low_band)
        padded = self._apply_padding(classified, len(samples), sr)

        rejected_count = len(candidates) - len(classified)
        total_candidates = len(candidates)

        output_dir = staging_dir or Path(f"/tmp/meowdb_{uuid.uuid4().hex}")
        output_dir.mkdir(parents=True, exist_ok=True)

        segments: list[MeowSegment] = []
        for i, (start_sample, end_sample, ratio) in enumerate(padded):
            start_ms = int(start_sample / sr * 1000)
            end_ms = int(end_sample / sr * 1000)
            slice_audio = audio[start_ms:end_ms]
            processed = self._process_segment(slice_audio)

            peak_dbfs = float(processed.dBFS)
            wav_path, mp3_path = self._export_segment(processed, output_dir, f"{path.stem}_{i:03d}")
            waveform = self._compute_waveform(processed)

            segments.append(
                MeowSegment(
                    index=i,
                    source_path=path,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    duration_ms=end_ms - start_ms,
                    cat_energy_ratio=ratio,
                    peak_dbfs=peak_dbfs,
                    wav_path=wav_path,
                    mp3_path=mp3_path,
                    waveform_data=waveform,
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

    def process_single(self, path: Path, staging_dir: Path | None = None) -> MeowSegment:
        audio, samples, sr = self._load(path)
        cat_band, low_band = self._build_discriminator_signals(samples, sr)

        cat_rms = float(np.sqrt(np.mean(cat_band**2)))
        low_rms = float(np.sqrt(np.mean(low_band**2)))
        ratio = cat_rms / (low_rms + 1e-10)

        processed = self._process_segment(audio)
        peak_dbfs = float(processed.dBFS)

        output_dir = staging_dir or Path(f"/tmp/meowdb_{uuid.uuid4().hex}")
        output_dir.mkdir(parents=True, exist_ok=True)

        wav_path, mp3_path = self._export_segment(processed, output_dir, path.stem)
        waveform = self._compute_waveform(processed)

        duration_ms = len(processed)
        return MeowSegment(
            index=0,
            source_path=path,
            start_ms=0,
            end_ms=duration_ms,
            duration_ms=duration_ms,
            cat_energy_ratio=ratio,
            peak_dbfs=peak_dbfs,
            wav_path=wav_path,
            mp3_path=mp3_path,
            waveform_data=waveform,
        )

    def _load(self, path: Path) -> tuple[AudioSegment, np.ndarray, int]:
        audio = AudioSegment.from_file(str(path))
        audio = audio.set_channels(1)
        audio = audio.set_frame_rate(44100)
        samples = self._audio_to_numpy(audio)
        return audio, samples, audio.frame_rate

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
        low_norm = seg.cat_band_low_hz / (sr / 2)
        high_norm = seg.cat_band_high_hz / (sr / 2)
        sos_cat = butter(4, [low_norm, high_norm], btype="bandpass", output="sos")
        cat_band = sosfilt(sos_cat, samples)

        sos_low = butter(4, 300.0 / (sr / 2), btype="lowpass", output="sos")
        low_band = sosfilt(sos_low, samples)

        return cat_band.astype(np.float32), low_band.astype(np.float32)

    def _detect_segments(self, cat_band: np.ndarray, sr: int) -> list[tuple[int, int]]:
        seg = self.config.segmentation
        frame_len = int(sr * 0.010)  # 10ms frames
        hop_len = int(sr * 0.005)  # 5ms hop

        # Short-time RMS via convolution over squared samples
        squared = cat_band**2
        window = np.ones(frame_len) / frame_len
        mean_sq = np.convolve(squared, window, mode="same")
        rms = np.sqrt(np.maximum(mean_sq, 0.0))

        epsilon = 1e-10
        dbfs = 20.0 * np.log10(rms + epsilon)

        # Downsample to one value per hop
        frame_indices = np.arange(0, len(dbfs), hop_len)
        frame_dbfs = dbfs[frame_indices]

        threshold = seg.silence_threshold_dbfs
        is_silent = frame_dbfs < threshold

        # Merge silence gaps shorter than min_silence_ms
        min_silence_frames = int(seg.min_silence_ms / 5)  # 5ms per frame
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
            sample_pos = frame_indices[fi] if fi < len(frame_indices) else len(cat_band)
            if not silent and not in_segment:
                seg_start = int(sample_pos)
                in_segment = True
            elif silent and in_segment:
                seg_end = int(frame_indices[fi] if fi < len(frame_indices) else len(cat_band))
                candidates.append((seg_start, seg_end))
                in_segment = False
        if in_segment:
            candidates.append((seg_start, len(cat_band)))

        # Filter by duration
        min_samples = int(seg.min_segment_ms / 1000 * sr)
        max_samples = int(seg.max_segment_ms / 1000 * sr)
        return [(s, e) for s, e in candidates if min_samples <= (e - s) <= max_samples]

    def _classify_segments(
        self,
        candidates: list[tuple[int, int]],
        cat_band: np.ndarray,
        low_band: np.ndarray,
    ) -> list[tuple[int, int, float]]:
        threshold = self.config.segmentation.min_cat_energy_ratio
        result: list[tuple[int, int, float]] = []
        for s, e in candidates:
            cat_rms = float(np.sqrt(np.mean(cat_band[s:e] ** 2)))
            low_rms = float(np.sqrt(np.mean(low_band[s:e] ** 2)))
            ratio = cat_rms / (low_rms + 1e-10)
            if ratio >= threshold:
                result.append((s, e, ratio))
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

        # Step 1: Noise reduction (non-stationary — no explicit noise profile needed)
        samples = self._audio_to_numpy(audio)
        denoised = noisereduce.reduce_noise(
            y=samples,
            sr=sr,
            stationary=False,
            prop_decrease=proc.noise_reduce_prop_decrease,
        )
        audio = self._numpy_to_audio(denoised, sr)

        # Step 2: Normalization — bring to target_dbfs
        current_dbfs = audio.dBFS
        if current_dbfs != float("-inf"):
            gain_db = proc.target_dbfs - current_dbfs
            audio = audio.apply_gain(gain_db)

        # Step 3: Dynamic compression
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

        # Step 4: Silence trim from both ends with 50ms padding (gotcha 7)
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
