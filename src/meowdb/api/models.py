from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, model_validator


class MeowResponse(BaseModel):
    id: str
    timestamp: str
    duration_ms: int
    labels: list[str]
    play_count: int
    upvote_count: int = 0
    downvote_count: int = 0
    created_at: str
    wav_url: str | None = None
    mp3_url: str | None = None
    waveform_data: list[float] = []
    recorded_at: str | None = None
    title: str | None = None
    uniqueness_score: float | None = None


class MeowListResponse(BaseModel):
    items: list[MeowResponse]
    total: int
    limit: int
    offset: int


class UpdateLabelsRequest(BaseModel):
    labels: list[str]


class UpdateMeowRequest(BaseModel):
    labels: list[str] | None = None
    title: str | None = None
    recorded_at: str | None = None


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


class FeedbackRequest(BaseModel):
    vote: Literal["up", "down"]
    previous: Literal["up", "down"] | None = None


class MeowSummary(BaseModel):
    id: str
    duration_ms: int
    labels: list[str]
    play_count: int
    upvote_count: int = 0
    downvote_count: int = 0
    created_at: str


class StatsResponse(BaseModel):
    total_meows: int
    total_duration_ms: int
    avg_duration_ms: float
    most_played: list[MeowSummary]
    recent: list[MeowSummary]
    most_upvoted: list[MeowSummary] = []
    most_downvoted: list[MeowSummary] = []
    label_counts: dict[str, int]
    first_meow_at: str | None = None


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


class PhotoResponse(BaseModel):
    id: str
    filename: str
    created_at: str
    updated_at: str = ""
    image_url: str
    is_default: bool = False


class PhotoListResponse(BaseModel):
    items: list[PhotoResponse]


class PhotoEditRequest(BaseModel):
    action: Literal["rotate", "flip", "crop"]
    direction: Literal["cw", "ccw"] | None = None
    axis: Literal["horizontal", "vertical"] | None = None
    x: float | None = None
    y: float | None = None
    width: float | None = None
    height: float | None = None

    @model_validator(mode="after")
    def _validate_fields(self) -> PhotoEditRequest:
        if self.action == "rotate":
            if self.direction is None:
                raise ValueError("direction required for rotate")
        elif self.action == "flip":
            if self.axis is None:
                raise ValueError("axis required for flip")
        elif self.action == "crop":
            if self.x is None or self.y is None or self.width is None or self.height is None:
                raise ValueError("x, y, width, height required for crop")
            if not (0.0 <= self.x <= 1.0):
                raise ValueError("x must be in [0, 1]")
            if not (0.0 <= self.y <= 1.0):
                raise ValueError("y must be in [0, 1]")
            if not (0.0 < self.width <= 1.0):
                raise ValueError("width must be in (0, 1]")
            if not (0.0 < self.height <= 1.0):
                raise ValueError("height must be in (0, 1]")
            if self.x + self.width > 1.0 + 1e-9:
                raise ValueError("x + width must be <= 1")
            if self.y + self.height > 1.0 + 1e-9:
                raise ValueError("y + height must be <= 1")
        return self


class RecalculateResponse(BaseModel):
    updated_count: int
    elapsed_seconds: float
