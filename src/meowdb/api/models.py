from __future__ import annotations

from pydantic import BaseModel, model_validator


class MeowResponse(BaseModel):
    id: str
    timestamp: str
    duration_ms: int
    labels: list[str]
    play_count: int
    created_at: str
    wav_url: str | None = None
    mp3_url: str | None = None


class MeowListResponse(BaseModel):
    items: list[MeowResponse]
    total: int
    limit: int
    offset: int


class UpdateLabelsRequest(BaseModel):
    labels: list[str]


class IngestSegmentResponse(BaseModel):
    id: str
    index: int
    duration_ms: int
    url: str
    waveform: list[float]
    status: str


class IngestJobResponse(BaseModel):
    job_id: str
    status: str
    segments: list[IngestSegmentResponse] | None = None
    source_filename: str | None = None
    error: str | None = None


class CommitRequest(BaseModel):
    accepted_ids: list[str]
    rejected_ids: list[str]


class CommitResponse(BaseModel):
    meow_ids: list[str]
    rejected_count: int


class MeowSummary(BaseModel):
    id: str
    duration_ms: int
    labels: list[str]
    play_count: int
    created_at: str


class StatsResponse(BaseModel):
    total_meows: int
    total_duration_ms: int
    avg_duration_ms: float
    most_played: list[MeowSummary]
    recent: list[MeowSummary]
    label_counts: dict[str, int]


class LabelResponse(BaseModel):
    label: str
    count: int


class ClipRegion(BaseModel):
    start_ms: int
    end_ms: int

    @model_validator(mode="after")
    def _validate_range(self) -> ClipRegion:
        if self.start_ms < 0:
            raise ValueError("start_ms must be non-negative")
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        return self


class ClipRequest(BaseModel):
    regions: list[ClipRegion]


class DetectRegion(BaseModel):
    start_ms: int
    end_ms: int


class DetectResponse(BaseModel):
    regions: list[DetectRegion]
