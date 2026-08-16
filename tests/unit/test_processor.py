from __future__ import annotations

import shutil

from pathlib import Path

import numpy as np
import pytest

from pydub import AudioSegment
from scipy.signal import butter, chirp, sosfilt

from meowdb.processor import SoundProcessor
from meowdb.species import processor_config_for_species

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


def _to_audio_segment(wave_data: np.ndarray, sample_rate: int) -> AudioSegment:
    """Wrap a float waveform in [-1, 1] as a mono 16-bit AudioSegment."""
    int_samples = (np.clip(wave_data, -1.0, 1.0) * 32768.0).astype(np.int16)
    return AudioSegment(
        int_samples.tobytes(),
        frame_rate=sample_rate,
        sample_width=2,
        channels=1,
    )


def _band_limited_noise(
    num_samples: int,
    sample_rate: int,
    low_hz: float = 200.0,
    high_hz: float = 2500.0,
    seed: int = 7,
) -> np.ndarray:
    """White noise band-limited to low_hz-high_hz, peak-normalized to 1.0."""
    rng = np.random.default_rng(seed)
    noise = rng.standard_normal(num_samples)
    nyquist = sample_rate / 2
    sos = butter(4, [low_hz / nyquist, high_hz / nyquist], btype="bandpass", output="sos")
    filtered = sosfilt(sos, noise)
    return np.asarray(filtered / np.max(np.abs(filtered)), dtype=np.float32)


def _make_bark_wav(
    duration_ms: int = 200,
    amplitude: float = 0.6,
    sample_rate: int = 44100,
) -> AudioSegment:
    """Bark surrogate: noise band-limited to 200-2500Hz (critical — unfiltered noise
    fails the canine dominance gate by design), instant attack, exponential decay."""
    num_samples = int(sample_rate * duration_ms / 1000)
    t = np.arange(num_samples) / sample_rate
    decay_tau = duration_ms / 2000  # seconds; keeps the tail above the VAD threshold
    envelope = np.exp(-t / decay_tau)
    wave_data = amplitude * _band_limited_noise(num_samples, sample_rate) * envelope
    return _to_audio_segment(wave_data, sample_rate)


def _make_howl_wav(
    duration_ms: int = 1500,
    amplitude: float = 0.5,
    sample_rate: int = 44100,
) -> AudioSegment:
    """Howl surrogate: 400->550Hz chirp with a 150ms fade-in (too slow for Branch A)."""
    num_samples = int(sample_rate * duration_ms / 1000)
    t = np.arange(num_samples) / sample_rate
    wave = chirp(t, f0=400, f1=550, t1=duration_ms / 1000, method="linear")
    envelope = np.minimum(1.0, t / 0.150)
    return _to_audio_segment(amplitude * wave * envelope, sample_rate)


def _make_speech_wav(
    duration_ms: int = 1000,
    amplitude: float = 0.6,
    sample_rate: int = 44100,
) -> AudioSegment:
    """Speech surrogate: harmonics of F0=140Hz under 4Hz syllabic AM (~80ms onsets)."""
    num_samples = int(sample_rate * duration_ms / 1000)
    t = np.arange(num_samples) / sample_rate
    wave = np.zeros(num_samples)
    for k in range(1, 7):
        wave += (1.0 / k) * np.sin(2 * np.pi * k * 140.0 * t)
    wave /= np.max(np.abs(wave))
    syllables = 0.5 * (1.0 - np.cos(2 * np.pi * 4.0 * t))
    return _to_audio_segment(amplitude * wave * syllables, sample_rate)


def _make_ramped_noise_wav(
    duration_ms: int = 600,
    amplitude: float = 0.6,
    attack_ms: int = 300,
    sample_rate: int = 44100,
) -> AudioSegment:
    """Band-limited noise with a slow linear attack — broadband but not impulsive."""
    num_samples = int(sample_rate * duration_ms / 1000)
    t = np.arange(num_samples) / sample_rate
    envelope = np.minimum(1.0, t / (attack_ms / 1000))
    wave_data = amplitude * _band_limited_noise(num_samples, sample_rate) * envelope
    return _to_audio_segment(wave_data, sample_rate)


def _make_dog_processor() -> SoundProcessor:
    return SoundProcessor(config=processor_config_for_species("dog"))


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
        processor = SoundProcessor()
        samples = np.array([1.5, -1.5, 0.5], dtype=np.float32)
        audio = processor._numpy_to_audio(samples, 44100)
        recovered = np.frombuffer(audio.raw_data, dtype=np.int16)
        # 0.5 is within [-1,1] and should round-trip cleanly
        assert recovered[2] == pytest.approx(int(0.5 * 32768.0), abs=1)
        # The full signal must have been clipped (no wild overflow artifacts)
        assert np.all(np.abs(recovered.astype(np.int32)) <= 32768)

    def test_round_trip_preserves_shape(self):
        processor = SoundProcessor()
        audio = _make_sine_wav(800, 500)
        samples = processor._audio_to_numpy(audio)
        reconstructed = processor._numpy_to_audio(samples, audio.frame_rate)
        recovered = processor._audio_to_numpy(reconstructed)
        assert len(recovered) == len(samples)

    def test_audio_to_numpy_float32(self):
        processor = SoundProcessor()
        audio = _make_sine_wav(800, 100)
        samples = processor._audio_to_numpy(audio)
        assert samples.dtype == np.float32
        assert np.all(samples >= -1.0)
        assert np.all(samples <= 1.0)


@pytest.mark.unit
class TestDiscriminatorSignals:
    def test_cat_band_passes_cat_frequency(self):
        """800Hz is inside the cat band (300-5000Hz); energy should be high."""
        processor = SoundProcessor()
        audio = _make_sine_wav(800, 500)
        samples = processor._audio_to_numpy(audio)
        cat_band, low_band = processor._build_discriminator_signals(samples, audio.frame_rate)
        cat_rms = float(np.sqrt(np.mean(cat_band**2)))
        low_rms = float(np.sqrt(np.mean(low_band**2)))
        assert cat_rms > low_rms * 1.5

    def test_low_band_passes_speech_frequency(self):
        """150Hz is in the low band (0-300Hz); low energy should dominate."""
        processor = SoundProcessor()
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
        processor = SoundProcessor()
        audio = _make_sine_wav(800, 1000, amplitude=0.6)
        wav_path = tmp_path / "cat.wav"
        _save_wav(audio, wav_path)

        samples = processor._audio_to_numpy(audio)
        cat_band, _ = processor._build_discriminator_signals(samples, audio.frame_rate)
        candidates = processor._detect_segments(cat_band, audio.frame_rate)
        assert len(candidates) >= 1

    def test_segment_duration_filter_rejects_too_short(self):
        """A 50ms tone is below min_segment_ms=80 and must be rejected."""
        processor = SoundProcessor()
        audio = _make_sine_wav(800, 50, amplitude=0.6)
        samples = processor._audio_to_numpy(audio)
        cat_band, _ = processor._build_discriminator_signals(samples, audio.frame_rate)
        candidates = processor._detect_segments(cat_band, audio.frame_rate)
        assert len(candidates) == 0

    def test_segment_duration_filter_rejects_too_long(self):
        """A 10-second tone exceeds max_segment_ms=5000 and must be rejected."""
        processor = SoundProcessor()
        # Use lower amplitude so convolve-based RMS produces one merged run
        audio = _make_sine_wav(800, 10000, amplitude=0.4)
        samples = processor._audio_to_numpy(audio)
        cat_band, _ = processor._build_discriminator_signals(samples, audio.frame_rate)
        candidates = processor._detect_segments(cat_band, audio.frame_rate)
        assert len(candidates) == 0


@pytest.mark.unit
class TestClassification:
    def test_accepts_cat_frequency_segment(self):
        """800Hz has high cat-band energy; ratio >= min_cat_energy_ratio → accepted."""
        processor = SoundProcessor()
        audio = _make_sine_wav(800, 1000, amplitude=0.6)
        samples = processor._audio_to_numpy(audio)
        cat_band, low_band = processor._build_discriminator_signals(samples, audio.frame_rate)
        candidates = [(0, len(samples))]
        classified = processor._classify_segments(candidates, cat_band, low_band, audio.frame_rate)
        assert len(classified) == 1
        assert classified[0][2] >= processor.config.segmentation.min_species_energy_ratio

    def test_rejects_speech_frequency_segment(self):
        """150Hz lives in low band; ratio < 1.2 → rejected."""
        processor = SoundProcessor()
        audio = _make_sine_wav(150, 1000, amplitude=0.6)
        samples = processor._audio_to_numpy(audio)
        cat_band, low_band = processor._build_discriminator_signals(samples, audio.frame_rate)
        candidates = [(0, len(samples))]
        classified = processor._classify_segments(candidates, cat_band, low_band, audio.frame_rate)
        assert len(classified) == 0


@pytest.mark.unit
class TestPadding:
    def test_expands_segment_by_pad(self):
        processor = SoundProcessor()
        sr = 44100
        # pre_pad_ms=200, post_pad_ms=200
        pre = int(0.200 * sr)
        post = int(0.200 * sr)
        total = sr * 3  # 3 seconds
        segments = [(sr, sr * 2, 1.5)]  # 1s to 2s
        padded = processor._apply_padding(segments, total, sr)
        assert padded[0][0] == sr - pre
        assert padded[0][1] == sr * 2 + post

    def test_clamps_to_bounds(self):
        processor = SoundProcessor()
        sr = 44100
        total = sr * 2
        # Segment starting at 0 — pre-pad would go negative
        segments = [(0, sr, 1.5)]
        padded = processor._apply_padding(segments, total, sr)
        assert padded[0][0] == 0
        assert padded[0][1] <= total

    def test_merges_overlapping_after_padding(self):
        processor = SoundProcessor()
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
        processor = SoundProcessor()
        audio = _make_sine_wav(800, 500)
        waveform = processor._compute_waveform(audio)
        assert all(0.0 <= v <= 1.0 for v in waveform)

    def test_waveform_length_approx_100_per_sec(self):
        """~100 samples/sec — 500ms → ~50 frames."""
        processor = SoundProcessor()
        audio = _make_sine_wav(800, 500)
        waveform = processor._compute_waveform(audio)
        assert 30 <= len(waveform) <= 70

    def test_waveform_max_is_one(self):
        """After normalization, the peak must equal exactly 1.0."""
        processor = SoundProcessor()
        audio = _make_sine_wav(800, 500, amplitude=0.3)
        waveform = processor._compute_waveform(audio)
        assert max(waveform) == pytest.approx(1.0, abs=1e-6)

    def test_silent_audio_returns_zeros(self):
        """Silent audio should produce all-zero waveform."""
        processor = SoundProcessor()
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

        processor = SoundProcessor()
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

        processor = SoundProcessor()
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

        processor = SoundProcessor()
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

        processor = SoundProcessor()
        result = processor.process_file(wav_path, staging_dir=tmp_path)

        assert len(result.segments) == 0
        assert result.rejected_count >= 1 or result.total_candidates == 0

    def test_result_elapsed_seconds_positive(self, tmp_path: Path):
        audio = _make_sine_wav(800, 500, amplitude=0.4)
        wav_path = tmp_path / "meow.wav"
        _save_wav(audio, wav_path)

        processor = SoundProcessor()
        result = processor.process_file(wav_path, staging_dir=tmp_path)

        assert result.elapsed_seconds > 0


@pytest.mark.unit
class TestAdaptiveThreshold:
    def test_detects_quiet_signal_missed_by_fixed_threshold(self):
        """Adaptive threshold detects a quiet meow that a fixed -40dBFS threshold misses.

        The recording has 5s of background noise at ~-78dBFS in the cat band. The P30
        of active frames falls in the noise floor, driving the adaptive threshold to the
        -45dBFS floor. The meow's ~-43dBFS RMS is above that floor but below the fixed
        -40dBFS threshold, so only adaptive detection catches it.
        """
        sr = 44100
        processor = SoundProcessor()
        # 5s recording: meow is only 8% of frames so P30 stays in the noise floor
        n_total = int(sr * 5.0)

        rng = np.random.default_rng(42)
        samples = (rng.standard_normal(n_total) * 0.0002).astype(np.float32)

        # 800Hz burst at amplitude 0.01 (~-43dBFS RMS) from 2.0s to 2.4s
        # Below fixed threshold (-40dBFS) but above adaptive floor (-45dBFS)
        meow_start = int(sr * 2.0)
        meow_end = int(sr * 2.4)
        t = np.arange(meow_end - meow_start) / sr
        samples[meow_start:meow_end] += (0.010 * np.sin(2 * np.pi * 800 * t)).astype(np.float32)

        cat_band, _ = processor._build_discriminator_signals(samples, sr)

        # Fixed threshold (-40dBFS) must miss the meow (meow RMS ~ -43dBFS < -40)
        from meowdb.models import ProcessorConfig, SegmentationConfig

        fixed_proc = SoundProcessor(
            config=ProcessorConfig(segmentation=SegmentationConfig(adaptive_threshold=False))
        )
        fixed_candidates = fixed_proc._detect_segments(cat_band, sr)
        assert len(fixed_candidates) == 0, "Fixed threshold should miss the quiet meow"

        # Adaptive threshold (floor -45dBFS) must detect it
        adaptive_candidates = processor._detect_segments(cat_band, sr)
        assert len(adaptive_candidates) >= 1

    def test_adaptive_floor_clamps_threshold(self):
        """If percentile + offset would fall below adaptive_floor_dbfs, clamp to floor."""
        processor = SoundProcessor()
        # All active frames at -75dBFS: P30=-75, threshold=-75+10=-65, clamped to floor
        very_quiet = np.full(10000, -75.0)
        threshold = processor._compute_adaptive_threshold(very_quiet)
        assert threshold == processor.config.segmentation.adaptive_floor_dbfs

    def test_adaptive_ceiling_clamps_threshold(self):
        """If percentile + offset would exceed adaptive_ceiling_dbfs, clamp to ceiling."""
        processor = SoundProcessor()
        # All frames near -10 dBFS → high percentile → threshold must clamp to ceiling
        very_loud = np.full(10000, -10.0)
        threshold = processor._compute_adaptive_threshold(very_loud)
        assert threshold == processor.config.segmentation.adaptive_ceiling_dbfs

    def test_disabled_adaptive_uses_fixed_threshold(self):
        """With adaptive_threshold=False, the fixed silence_threshold_dbfs is returned."""
        from meowdb.models import ProcessorConfig, SegmentationConfig

        config = ProcessorConfig(segmentation=SegmentationConfig(adaptive_threshold=False))
        processor = SoundProcessor(config=config)
        frame_dbfs = np.linspace(-80, -20, 1000)
        threshold = processor._compute_adaptive_threshold(frame_dbfs)
        assert threshold == config.segmentation.silence_threshold_dbfs


@pytest.mark.unit
class TestSpectralClassifier:
    def test_pure_tone_has_low_flatness(self):
        """A pure 800Hz sine has near-zero spectral flatness (highly tonal)."""
        processor = SoundProcessor()
        audio = _make_sine_wav(800, 500)
        samples = processor._audio_to_numpy(audio)
        flatness = processor._spectral_flatness(samples, audio.frame_rate)
        assert flatness < 0.1

    def test_white_noise_has_high_flatness(self):
        """White noise has flatness near 1.0 (spectrally flat)."""
        processor = SoundProcessor()
        rng = np.random.default_rng(42)
        noise = rng.standard_normal(44100).astype(np.float32) * 0.1
        flatness = processor._spectral_flatness(noise, 44100)
        assert flatness > 0.4

    def test_short_segment_returns_zero(self):
        """Segments shorter than 256 samples return 0.0 (assumed tonal, passes test3)."""
        processor = SoundProcessor()
        short = np.zeros(100, dtype=np.float32)
        flatness = processor._spectral_flatness(short, 44100)
        assert flatness == 0.0

    def test_tonal_onset_then_noise_not_fooled(self):
        """Flatness is averaged over the full segment, not just the first window.

        A tonal first 46ms followed by broadband noise must score high flatness
        overall, not low flatness from the onset alone.
        """
        processor = SoundProcessor()
        sr = 44100
        rng = np.random.default_rng(0)
        # 46ms tonal onset (one 2048-sample window)
        t_tone = np.arange(2048) / sr
        tone = (0.5 * np.sin(2 * np.pi * 800 * t_tone)).astype(np.float32)
        # ~500ms of broadband noise (many more windows)
        noise = (rng.standard_normal(sr // 2) * 0.3).astype(np.float32)
        combined = np.concatenate([tone, noise])
        flatness = processor._spectral_flatness(combined, sr)
        # Overall flatness should be high (noise dominated) not low (tone dominated)
        assert flatness > 0.3


@pytest.mark.unit
class TestClassifierRequiresAllThree:
    def test_rejects_noisy_segment_despite_high_ratios(self):
        """All 3 tests must pass; broadband noise fails test3 even when ratio tests pass.

        A 50ms 800Hz burst mixed into 300ms of white noise produces high avg_ratio and
        peak_ratio (the burst dominates energy), but the noise elevates spectral flatness
        above the 0.45 threshold. The 3-of-3 requirement correctly rejects this segment.
        """
        sr = 44100
        processor = SoundProcessor()
        rng = np.random.default_rng(7)
        noise_samples = (rng.standard_normal(int(sr * 0.3)) * 0.005).astype(np.float32)
        burst_audio = _make_sine_wav(800, 50, amplitude=0.5)
        burst_samples = processor._audio_to_numpy(burst_audio)
        combined = np.concatenate([noise_samples, burst_samples])

        cat_band, low_band = processor._build_discriminator_signals(combined, sr)
        candidates = [(0, len(combined))]
        classified = processor._classify_segments(candidates, cat_band, low_band, sr)
        # Ratio tests pass but spectral flatness > 0.45 due to noise → rejected
        assert len(classified) == 0


@pytest.mark.unit
@_ffmpeg_available
class TestShortMeowDetection:
    def test_detects_100ms_meow(self, tmp_path: Path):
        """A 100ms 800Hz tone (above new min_segment_ms=80) is found as a candidate."""
        sr = 44100
        silence = AudioSegment.silent(duration=400, frame_rate=sr)
        meow = _make_sine_wav(800, 100, amplitude=0.6)
        full = silence + meow + silence
        wav_path = tmp_path / "short_meow.wav"
        _save_wav(full, wav_path)

        processor = SoundProcessor()
        audio, samples, rate = processor._load(wav_path)
        cat_band, _ = processor._build_discriminator_signals(samples, rate)
        candidates = processor._detect_segments(cat_band, rate)
        assert len(candidates) >= 1

    def test_still_rejects_50ms(self, tmp_path: Path):
        """A 50ms tone is still below min_segment_ms=80 and must be rejected."""
        sr = 44100
        silence = AudioSegment.silent(duration=400, frame_rate=sr)
        meow = _make_sine_wav(800, 50, amplitude=0.6)
        full = silence + meow + silence
        wav_path = tmp_path / "very_short.wav"
        _save_wav(full, wav_path)

        processor = SoundProcessor()
        audio, samples, rate = processor._load(wav_path)
        cat_band, _ = processor._build_discriminator_signals(samples, rate)
        candidates = processor._detect_segments(cat_band, rate)
        assert len(candidates) == 0


@pytest.mark.unit
class TestSpeciesConfig:
    def test_processor_config_for_species_dog_has_dog_overrides(self):
        """processor_config_for_species('dog') applies the canine segmentation overrides
        (detection band 150–3500 Hz) while the fingerprint band keeps fmin=60."""
        from meowdb.species import SPECIES_REGISTRY, processor_config_for_species

        config = processor_config_for_species("dog")
        seg = config.segmentation
        assert seg.band_low_hz == pytest.approx(150.0)
        assert seg.band_high_hz == pytest.approx(3500.0)
        assert seg.classifier == "canine"
        assert seg.reference_mode == "highpass"
        assert seg.reference_cutoff_hz == pytest.approx(4500.0)
        assert seg.min_silence_ms == 250
        assert seg.min_segment_ms == 60
        assert seg.max_segment_ms == 15000

        # Fingerprint band (similarity.py) is untouched by detection overrides
        assert SPECIES_REGISTRY["dog"].fmin == pytest.approx(60.0)
        assert SPECIES_REGISTRY["dog"].fmax == pytest.approx(3500.0)

        processor = SoundProcessor(config=config)
        assert processor.config.segmentation.band_low_hz == pytest.approx(150.0)

    def test_get_species_config_unknown_falls_back_to_cat(self):
        """get_species_config with an unrecognised species name returns cat defaults."""
        from meowdb.species import SPECIES_REGISTRY, get_species_config

        cat_cfg = SPECIES_REGISTRY["cat"]
        unk_cfg = get_species_config("unknown_species")
        assert unk_cfg.fmin == pytest.approx(cat_cfg.fmin)
        assert unk_cfg.fmax == pytest.approx(cat_cfg.fmax)


@pytest.mark.unit
class TestCatRegression:
    def test_default_segmentation_config_is_cat_contract(self):
        """Field-value snapshot of SegmentationConfig() defaults — locks the cat contract.

        SegmentationConfig() with no args must remain exactly today's cat config; any
        new field must default to a value that leaves cat behavior unchanged.
        """
        from meowdb.models import SegmentationConfig

        config = SegmentationConfig()
        assert config.band_low_hz == 250.0
        assert config.band_high_hz == 8000.0
        assert config.silence_threshold_dbfs == -40.0
        assert config.min_silence_ms == 150
        assert config.min_segment_ms == 80
        assert config.max_segment_ms == 5000
        assert config.min_species_energy_ratio == 3.0
        assert config.pre_pad_ms == 200
        assert config.post_pad_ms == 200
        assert config.adaptive_threshold is True
        assert config.adaptive_percentile == 30.0
        assert config.adaptive_offset_db == 10.0
        assert config.adaptive_floor_dbfs == -45.0
        assert config.adaptive_ceiling_dbfs == -40.0
        assert config.min_peak_ratio == 3.5
        assert config.peak_ratio_window_ms == 50
        assert config.use_spectral_classifier is True
        assert config.max_spectral_flatness == 0.45
        assert config.classifier == "tonal"
        assert config.reference_mode == "lowpass"
        assert config.reference_cutoff_hz is None


@pytest.mark.unit
class TestCanineGate:
    def test_bark_passes_band_dominance_gate(self):
        """A band-limited bark dominates the >=4500Hz reference band by far more than 2x."""
        processor = _make_dog_processor()
        samples = processor._audio_to_numpy(_make_bark_wav())
        species_band, reference_band = processor._build_discriminator_signals(samples, 44100)
        species_rms = float(np.sqrt(np.mean(species_band**2)))
        reference_rms = float(np.sqrt(np.mean(reference_band**2)))
        dominance = species_rms / (reference_rms + 1e-10)
        assert dominance >= processor.config.segmentation.min_band_dominance_ratio

    def test_full_band_white_noise_fails_gate(self):
        """Unfiltered white noise splits energy by bandwidth: dominance ~= 0.44 < 2.0."""
        processor = _make_dog_processor()
        rng = np.random.default_rng(42)
        samples = (rng.standard_normal(44100) * 0.3).astype(np.float32)
        species_band, reference_band = processor._build_discriminator_signals(samples, 44100)
        species_rms = float(np.sqrt(np.mean(species_band**2)))
        reference_rms = float(np.sqrt(np.mean(reference_band**2)))
        dominance = species_rms / (reference_rms + 1e-10)
        assert dominance == pytest.approx(0.44, abs=0.15)

        candidates = [(0, len(samples))]
        classified = processor._classify_canine(candidates, species_band, reference_band, 44100)
        assert len(classified) == 0


@pytest.mark.unit
class TestRiseTime:
    def test_bark_attack_is_fast(self):
        """Instant-attack bark envelope reaches its peak within max_attack_ms."""
        processor = _make_dog_processor()
        samples = processor._audio_to_numpy(_make_bark_wav())
        assert processor._rise_time_ms(samples, 44100) <= 40.0

    def test_ramped_noise_attack_is_slow(self):
        """A 300ms linear attack measures far above the 40ms bark threshold."""
        processor = _make_dog_processor()
        samples = processor._audio_to_numpy(_make_ramped_noise_wav())
        assert processor._rise_time_ms(samples, 44100) > 100.0


@pytest.mark.unit
class TestHarmonicity:
    def test_sine_is_harmonic_with_correct_f0(self):
        """A pure 800Hz sine is almost fully voiced with harmonicity ~= 1 and F0 ~= 800."""
        processor = _make_dog_processor()
        samples = processor._audio_to_numpy(_make_sine_wav(800, 500))
        voiced_fraction, harmonicity, f0_hz = processor._harmonicity(samples, 44100)
        assert voiced_fraction > 0.9
        assert harmonicity > 0.8
        assert f0_hz == pytest.approx(800.0, rel=0.05)

    def test_white_noise_is_inharmonic(self):
        """White noise autocorrelation peaks stay below the 0.4 voicing threshold."""
        processor = _make_dog_processor()
        rng = np.random.default_rng(42)
        samples = (rng.standard_normal(22050) * 0.3).astype(np.float32)
        voiced_fraction, harmonicity, _ = processor._harmonicity(samples, 44100)
        assert voiced_fraction < 0.5
        assert harmonicity < 0.3

    def test_low_tone_measures_below_f0_floor(self):
        """A 150Hz tone measures its true F0 (below the 250Hz floor), not a harmonic."""
        processor = _make_dog_processor()
        samples = processor._audio_to_numpy(_make_sine_wav(150, 500))
        voiced_fraction, _, f0_hz = processor._harmonicity(samples, 44100)
        assert voiced_fraction > 0.5
        assert f0_hz == pytest.approx(150.0, rel=0.05)
        assert f0_hz < processor.config.segmentation.min_tonal_f0_hz


@pytest.mark.unit
class TestCanineBarkBranch:
    def _classify(self, processor: SoundProcessor, audio: AudioSegment):
        samples = processor._audio_to_numpy(audio)
        species_band, reference_band = processor._build_discriminator_signals(samples, 44100)
        candidates = [(0, len(samples))]
        return processor._classify_canine(candidates, species_band, reference_band, 44100)

    def test_bark_accepted(self):
        """Fast attack + broadband spectrum: Branch A accepts the bark surrogate."""
        processor = _make_dog_processor()
        assert len(self._classify(processor, _make_bark_wav())) == 1

    def test_ramped_noise_rejected(self):
        """Broadband but slow attack: fails Branch A on attack, Branch B on flatness."""
        processor = _make_dog_processor()
        assert len(self._classify(processor, _make_ramped_noise_wav())) == 0

    def test_speech_surrogate_rejected(self):
        """Harmonic vowels: fails Branch A on flatness, Branch B on the F0 floor."""
        processor = _make_dog_processor()
        assert len(self._classify(processor, _make_speech_wav())) == 0


@pytest.mark.unit
class TestCanineTonalBranch:
    def _classify(self, processor: SoundProcessor, audio: AudioSegment):
        samples = processor._audio_to_numpy(audio)
        species_band, reference_band = processor._build_discriminator_signals(samples, 44100)
        candidates = [(0, len(samples))]
        return processor._classify_canine(candidates, species_band, reference_band, 44100)

    def test_howl_chirp_accepted(self):
        """Sustained tonal 400->550Hz chirp passes Branch B."""
        processor = _make_dog_processor()
        assert len(self._classify(processor, _make_howl_wav())) == 1

    def test_sustained_tone_accepted(self):
        """A 1s 800Hz tone (whine-like) passes Branch B despite failing A on flatness."""
        processor = _make_dog_processor()
        assert len(self._classify(processor, _make_sine_wav(800, 1000, amplitude=0.5))) == 1

    def test_low_pitch_harmonic_tone_rejected_on_f0_floor(self):
        """A sustained 150Hz harmonic stack is tonal but pitched like speech — rejected."""
        processor = _make_dog_processor()
        sr = 44100
        t = np.arange(sr) / sr
        wave = np.zeros(sr)
        for k in range(1, 4):
            wave += (1.0 / k) * np.sin(2 * np.pi * k * 150.0 * t)
        audio = _to_audio_segment(0.5 * wave / np.max(np.abs(wave)), sr)
        assert len(self._classify(processor, audio)) == 0

    def test_short_blip_rejected_on_min_tonal_ms(self):
        """A tonal 150ms blip is below min_tonal_ms=300 — too short for a howl/whine."""
        processor = _make_dog_processor()
        assert len(self._classify(processor, _make_sine_wav(800, 150, amplitude=0.5))) == 0


@pytest.mark.unit
class TestCanineDurations:
    def test_long_howl_survives_dog_vad(self):
        """An 8s howl exceeds the cat max (5s) but fits the dog max (15s)."""
        processor = _make_dog_processor()
        samples = processor._audio_to_numpy(_make_howl_wav(duration_ms=8000))
        species_band, _ = processor._build_discriminator_signals(samples, 44100)
        candidates = processor._detect_segments(species_band, 44100)
        assert len(candidates) >= 1
        longest = max(e - s for s, e in candidates)
        assert longest >= 7 * 44100

    def test_bark_volley_merges_into_one_candidate(self):
        """Barks separated by 200ms gaps (< min_silence_ms=250) merge into one clip."""
        processor = _make_dog_processor()
        sr = 44100
        bark = processor._audio_to_numpy(_make_bark_wav(duration_ms=150))
        gap = np.zeros(int(sr * 0.200), dtype=np.float32)
        volley = np.concatenate([bark, gap, bark, gap, bark])
        species_band, _ = processor._build_discriminator_signals(volley, sr)
        candidates = processor._detect_segments(species_band, sr)
        assert len(candidates) == 1


@pytest.mark.unit
@_ffmpeg_available
class TestCanineEndToEnd:
    def test_detects_bark(self, tmp_path: Path):
        """A bark surrounded by silence is detected under the dog config."""
        silence = AudioSegment.silent(duration=400, frame_rate=44100)
        full = silence + _make_bark_wav() + silence
        wav_path = tmp_path / "bark.wav"
        _save_wav(full, wav_path)

        regions = _make_dog_processor().detect_only(wav_path)
        assert len(regions) >= 1

    def test_detects_howl(self, tmp_path: Path):
        """A howl surrounded by silence is detected under the dog config."""
        silence = AudioSegment.silent(duration=400, frame_rate=44100)
        full = silence + _make_howl_wav() + silence
        wav_path = tmp_path / "howl.wav"
        _save_wav(full, wav_path)

        regions = _make_dog_processor().detect_only(wav_path)
        assert len(regions) >= 1

    def test_rejects_speech(self, tmp_path: Path):
        """A speech surrogate surrounded by silence produces no dog detections."""
        silence = AudioSegment.silent(duration=400, frame_rate=44100)
        full = silence + _make_speech_wav() + silence
        wav_path = tmp_path / "speech.wav"
        _save_wav(full, wav_path)

        regions = _make_dog_processor().detect_only(wav_path)
        assert len(regions) == 0
