from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CanineConfig(BaseModel):
    """Canine classifier knobs (Gate G + Branch A/B); inert under the feline profile."""

    model_config = ConfigDict(extra="forbid")

    min_band_dominance_ratio: float = Field(default=2.0, gt=0)
    max_attack_ms: int = Field(default=40, gt=0)
    min_impulsive_flatness: float = Field(default=0.20, ge=0, le=1)
    max_tonal_flatness: float = Field(default=0.30, ge=0, le=1)
    min_tonal_ms: int = Field(default=300, gt=0)
    min_harmonicity: float = Field(default=0.5, ge=0, le=1)
    min_voiced_fraction: float = Field(default=0.5, ge=0, le=1)
    min_tonal_f0_hz: float = Field(default=250.0, gt=0)
    max_tonal_f0_hz: float = Field(default=2000.0, gt=0)
    # Below min_tonal_f0_hz on purpose: a low-pitched voice must measure its true
    # (too-low) F0 rather than octave-alias to a harmonic above the floor.
    f0_search_floor_hz: float = Field(default=70.0, gt=0)
    voiced_peak_threshold: float = Field(default=0.4, ge=0, le=1)


class SegmentationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    band_low_hz: float = 250.0
    band_high_hz: float = 8000.0
    silence_threshold_dbfs: float = -40.0
    min_silence_ms: int = 150
    min_segment_ms: int = 80
    max_segment_ms: int = 5000
    min_species_energy_ratio: float = 3.0
    pre_pad_ms: int = 200
    post_pad_ms: int = 200
    adaptive_threshold: bool = True
    adaptive_percentile: float = 30.0
    adaptive_offset_db: float = 10.0
    adaptive_floor_dbfs: float = -45.0
    adaptive_ceiling_dbfs: float = -40.0
    min_peak_ratio: float = 3.5
    peak_ratio_window_ms: int = 50
    use_spectral_classifier: bool = True  # feline classifier only (test 3)
    max_spectral_flatness: float = 0.45
    classifier: Literal["feline", "canine"] = "feline"
    reference_mode: Literal["lowpass", "highpass"] = "lowpass"
    reference_cutoff_hz: float | None = None  # None -> band_low_hz / band_high_hz
    canine: CanineConfig = CanineConfig()


class ProcessingConfig(BaseModel):
    noise_reduce_prop_decrease: float = 0.75
    target_dbfs: float = -3.0
    compressor_threshold_dbfs: float = -12.0
    compressor_ratio: float = 4.0
    trim_silence_threshold_dbfs: float = -50.0


class ExportConfig(BaseModel):
    wav_sample_rate: int = 44100
    wav_channels: int = 1
    mp3_bitrate: str = "192k"


class ProcessorConfig(BaseModel):
    segmentation: SegmentationConfig = SegmentationConfig()
    processing: ProcessingConfig = ProcessingConfig()
    export: ExportConfig = ExportConfig()


@dataclass
class SoundSegment:
    index: int
    source_path: Path
    start_ms: int
    end_ms: int
    duration_ms: int
    species_energy_ratio: float
    peak_dbfs: float
    wav_path: Path | None = None
    mp3_path: Path | None = None
    waveform_data: list[float] = field(default_factory=list)

    def to_db_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "duration_ms": self.duration_ms,
            "wav_path": str(self.wav_path) if self.wav_path else "",
            "waveform_data": self.waveform_data,
            "peak_dbfs": self.peak_dbfs,
            "species_energy_ratio": self.species_energy_ratio,
        }


@dataclass
class ProcessingResult:
    source_path: Path
    segments: list[SoundSegment]
    rejected_count: int
    total_candidates: int
    elapsed_seconds: float
