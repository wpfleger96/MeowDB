from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    pass


class SegmentationConfig(BaseModel):
    cat_band_low_hz: float = 250.0
    cat_band_high_hz: float = 5000.0
    silence_threshold_dbfs: float = -40.0
    min_silence_ms: int = 150
    min_segment_ms: int = 80
    max_segment_ms: int = 5000
    min_cat_energy_ratio: float = 3.0
    pre_pad_ms: int = 200
    post_pad_ms: int = 200
    adaptive_threshold: bool = True
    adaptive_percentile: float = 30.0
    adaptive_offset_db: float = 10.0
    adaptive_floor_dbfs: float = -45.0
    adaptive_ceiling_dbfs: float = -40.0
    min_peak_ratio: float = 3.5
    peak_ratio_window_ms: int = 50
    use_spectral_classifier: bool = True
    max_spectral_flatness: float = 0.45


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
class MeowSegment:
    index: int
    source_path: Path
    start_ms: int
    end_ms: int
    duration_ms: int
    cat_energy_ratio: float
    peak_dbfs: float
    wav_path: Path | None = None
    mp3_path: Path | None = None
    waveform_data: list[float] = field(default_factory=list)


@dataclass
class ProcessingResult:
    source_path: Path
    segments: list[MeowSegment]
    rejected_count: int
    total_candidates: int
    elapsed_seconds: float
