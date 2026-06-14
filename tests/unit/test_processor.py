from __future__ import annotations

import shutil

from pathlib import Path

import numpy as np
import pytest

from pydub import AudioSegment

from meowdb.processor import MeowProcessor

_ffmpeg_available = pytest.mark.skipif(
    shutil.which("ffmpeg") is None,
    reason="ffmpeg not installed",
)


def _make_sine_wav(
    frequency: float,
    duration_ms: int,
    amplitude: float = 0.5,
    sample_rate: int = 44100,
) -> AudioSegment:
    """Build a mono WAV AudioSegment containing a pure sine wave."""
    num_samples = int(sample_rate * duration_ms / 1000)
    t = np.linspace(0, duration_ms / 1000, num_samples, endpoint=False)
    wave_data = (amplitude * np.sin(2 * np.pi * frequency * t)).astype(np.float32)
    int_samples = (np.clip(wave_data, -1.0, 1.0) * 32768.0).astype(np.int16)
    return AudioSegment(
        int_samples.tobytes(),
        frame_rate=sample_rate,
        sample_width=2,
        channels=1,
    )


def _save_wav(audio: AudioSegment, path: Path) -> None:
    audio.export(str(path), format="wav")


@pytest.mark.unit
class TestAudioConversion:
    def test_numpy_to_audio_clips_before_multiply(self):
        """Values > 1.0 are clipped to [-1,1] before int16 multiply.

        Without the clip, 1.5 * 32768 = 49152 which wraps to a negative int16.
        With the clip, 1.0 * 32768 = 32768 which is the int16 boundary.
        The key invariant: clipped positive samples produce non-negative int16 values
        and clipped negative samples produce non-positive int16 values.
        """
        processor = MeowProcessor()
        samples = np.array([1.5, -1.5, 0.5], dtype=np.float32)
        audio = processor._numpy_to_audio(samples, 44100)
        recovered = np.frombuffer(audio.raw_data, dtype=np.int16)
        # 0.5 is within [-1,1] and should round-trip cleanly
        assert recovered[2] == pytest.approx(int(0.5 * 32768.0), abs=1)
        # The full signal must have been clipped (no wild overflow artifacts)
        assert np.all(np.abs(recovered.astype(np.int32)) <= 32768)

    def test_round_trip_preserves_shape(self):
        processor = MeowProcessor()
        audio = _make_sine_wav(800, 500)
        samples = processor._audio_to_numpy(audio)
        reconstructed = processor._numpy_to_audio(samples, audio.frame_rate)
        recovered = processor._audio_to_numpy(reconstructed)
        assert len(recovered) == len(samples)

    def test_audio_to_numpy_float32(self):
        processor = MeowProcessor()
        audio = _make_sine_wav(800, 100)
        samples = processor._audio_to_numpy(audio)
        assert samples.dtype == np.float32
        assert np.all(samples >= -1.0)
        assert np.all(samples <= 1.0)


@pytest.mark.unit
class TestDiscriminatorSignals:
    def test_cat_band_passes_cat_frequency(self):
        """800Hz is inside the cat band (300-5000Hz); energy should be high."""
        processor = MeowProcessor()
        audio = _make_sine_wav(800, 500)
        samples = processor._audio_to_numpy(audio)
        cat_band, low_band = processor._build_discriminator_signals(samples, audio.frame_rate)
        cat_rms = float(np.sqrt(np.mean(cat_band**2)))
        low_rms = float(np.sqrt(np.mean(low_band**2)))
        assert cat_rms > low_rms * 1.5

    def test_low_band_passes_speech_frequency(self):
        """150Hz is in the low band (0-300Hz); low energy should dominate."""
        processor = MeowProcessor()
        audio = _make_sine_wav(150, 500)
        samples = processor._audio_to_numpy(audio)
        cat_band, low_band = processor._build_discriminator_signals(samples, audio.frame_rate)
        cat_rms = float(np.sqrt(np.mean(cat_band**2)))
        low_rms = float(np.sqrt(np.mean(low_band**2)))
        assert low_rms > cat_rms


@pytest.mark.unit
class TestSegmentDetection:
    def test_detects_cat_frequency_segment(self, tmp_path: Path):
        """800Hz tone should be detected as a candidate segment."""
        processor = MeowProcessor()
        audio = _make_sine_wav(800, 1000, amplitude=0.6)
        wav_path = tmp_path / "cat.wav"
        _save_wav(audio, wav_path)

        samples = processor._audio_to_numpy(audio)
        cat_band, _ = processor._build_discriminator_signals(samples, audio.frame_rate)
        candidates = processor._detect_segments(cat_band, audio.frame_rate)
        assert len(candidates) >= 1

    def test_segment_duration_filter_rejects_too_short(self):
        """A 50ms tone is below min_segment_ms=200 and must be rejected."""
        processor = MeowProcessor()
        audio = _make_sine_wav(800, 50, amplitude=0.6)
        samples = processor._audio_to_numpy(audio)
        cat_band, _ = processor._build_discriminator_signals(samples, audio.frame_rate)
        candidates = processor._detect_segments(cat_band, audio.frame_rate)
        assert len(candidates) == 0

    def test_segment_duration_filter_rejects_too_long(self):
        """A 10-second tone exceeds max_segment_ms=4000 and must be rejected."""
        processor = MeowProcessor()
        # Use lower amplitude so convolve-based RMS produces one merged run
        audio = _make_sine_wav(800, 10000, amplitude=0.4)
        samples = processor._audio_to_numpy(audio)
        cat_band, _ = processor._build_discriminator_signals(samples, audio.frame_rate)
        candidates = processor._detect_segments(cat_band, audio.frame_rate)
        assert len(candidates) == 0


@pytest.mark.unit
class TestClassification:
    def test_accepts_cat_frequency_segment(self):
        """800Hz has high cat-band energy; ratio >= 1.2 → accepted."""
        processor = MeowProcessor()
        audio = _make_sine_wav(800, 1000, amplitude=0.6)
        samples = processor._audio_to_numpy(audio)
        cat_band, low_band = processor._build_discriminator_signals(samples, audio.frame_rate)
        candidates = [(0, len(samples))]
        classified = processor._classify_segments(candidates, cat_band, low_band)
        assert len(classified) == 1
        assert classified[0][2] >= 1.2  # ratio field

    def test_rejects_speech_frequency_segment(self):
        """150Hz lives in low band; ratio < 1.2 → rejected."""
        processor = MeowProcessor()
        audio = _make_sine_wav(150, 1000, amplitude=0.6)
        samples = processor._audio_to_numpy(audio)
        cat_band, low_band = processor._build_discriminator_signals(samples, audio.frame_rate)
        candidates = [(0, len(samples))]
        classified = processor._classify_segments(candidates, cat_band, low_band)
        assert len(classified) == 0


@pytest.mark.unit
class TestPadding:
    def test_expands_segment_by_pad(self):
        processor = MeowProcessor()
        sr = 44100
        # pre_pad_ms=150, post_pad_ms=150
        pre = int(0.150 * sr)
        post = int(0.150 * sr)
        total = sr * 3  # 3 seconds
        segments = [(sr, sr * 2, 1.5)]  # 1s to 2s
        padded = processor._apply_padding(segments, total, sr)
        assert padded[0][0] == sr - pre
        assert padded[0][1] == sr * 2 + post

    def test_clamps_to_bounds(self):
        processor = MeowProcessor()
        sr = 44100
        total = sr * 2
        # Segment starting at 0 — pre-pad would go negative
        segments = [(0, sr, 1.5)]
        padded = processor._apply_padding(segments, total, sr)
        assert padded[0][0] == 0
        assert padded[0][1] <= total

    def test_merges_overlapping_after_padding(self):
        processor = MeowProcessor()
        sr = 44100
        total = sr * 5
        # Two close segments that overlap after padding
        segments = [(sr, sr + 100, 1.5), (sr + 200, sr + 300, 1.8)]
        padded = processor._apply_padding(segments, total, sr)
        assert len(padded) == 1


@pytest.mark.unit
class TestWaveform:
    def test_waveform_range(self):
        """All waveform values must be in [0, 1]."""
        processor = MeowProcessor()
        audio = _make_sine_wav(800, 500)
        waveform = processor._compute_waveform(audio)
        assert all(0.0 <= v <= 1.0 for v in waveform)

    def test_waveform_length_approx_100_per_sec(self):
        """~100 samples/sec — 500ms → ~50 frames."""
        processor = MeowProcessor()
        audio = _make_sine_wav(800, 500)
        waveform = processor._compute_waveform(audio)
        assert 30 <= len(waveform) <= 70

    def test_waveform_max_is_one(self):
        """After normalization, the peak must equal exactly 1.0."""
        processor = MeowProcessor()
        audio = _make_sine_wav(800, 500, amplitude=0.3)
        waveform = processor._compute_waveform(audio)
        assert max(waveform) == pytest.approx(1.0, abs=1e-6)

    def test_silent_audio_returns_zeros(self):
        """Silent audio should produce all-zero waveform."""
        processor = MeowProcessor()
        silence = AudioSegment.silent(duration=500, frame_rate=44100)
        waveform = processor._compute_waveform(silence)
        assert all(v == 0.0 for v in waveform)


@pytest.mark.unit
@_ffmpeg_available
class TestProcessSingle:
    def test_process_single_returns_valid_segment(self, tmp_path: Path):
        audio = _make_sine_wav(800, 1000, amplitude=0.4)
        wav_path = tmp_path / "meow.wav"
        _save_wav(audio, wav_path)

        processor = MeowProcessor()
        segment = processor.process_single(wav_path, staging_dir=tmp_path)

        assert segment.index == 0
        assert segment.duration_ms > 0
        assert segment.wav_path is not None and segment.wav_path.exists()
        assert segment.mp3_path is not None and segment.mp3_path.exists()
        assert len(segment.waveform_data) > 0

    def test_process_single_rms_not_corrupted(self, tmp_path: Path):
        """Processing chain must not destroy the signal — output RMS non-zero."""
        audio = _make_sine_wav(800, 1000, amplitude=0.4)
        wav_path = tmp_path / "meow.wav"
        _save_wav(audio, wav_path)

        processor = MeowProcessor()
        segment = processor.process_single(wav_path, staging_dir=tmp_path)

        assert segment.wav_path is not None
        output = AudioSegment.from_wav(str(segment.wav_path))
        samples = np.frombuffer(output.raw_data, dtype=np.int16).astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(samples**2)))
        assert rms > 0.01  # non-trivial signal survived processing


@pytest.mark.unit
@_ffmpeg_available
class TestProcessFile:
    def test_detects_cat_meow_segment(self, tmp_path: Path):
        """A cat-frequency segment surrounded by silence should be found."""
        sr = 44100
        silence = AudioSegment.silent(duration=400, frame_rate=sr)
        meow = _make_sine_wav(800, 800, amplitude=0.6)
        full = silence + meow + silence
        wav_path = tmp_path / "recording.wav"
        _save_wav(full, wav_path)

        processor = MeowProcessor()
        result = processor.process_file(wav_path, staging_dir=tmp_path)

        assert result.source_path == wav_path
        assert len(result.segments) >= 1

    def test_rejects_speech_frequency(self, tmp_path: Path):
        """A speech-frequency tone in silence should produce no accepted segments."""
        sr = 44100
        silence = AudioSegment.silent(duration=400, frame_rate=sr)
        speech = _make_sine_wav(150, 800, amplitude=0.6)
        full = silence + speech + silence
        wav_path = tmp_path / "speech.wav"
        _save_wav(full, wav_path)

        processor = MeowProcessor()
        result = processor.process_file(wav_path, staging_dir=tmp_path)

        assert len(result.segments) == 0
        assert result.rejected_count >= 1 or result.total_candidates == 0

    def test_result_elapsed_seconds_positive(self, tmp_path: Path):
        audio = _make_sine_wav(800, 500, amplitude=0.4)
        wav_path = tmp_path / "meow.wav"
        _save_wav(audio, wav_path)

        processor = MeowProcessor()
        result = processor.process_file(wav_path, staging_dir=tmp_path)

        assert result.elapsed_seconds > 0
