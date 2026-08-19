from typing import Any

from pydantic import BaseModel


class SegmentationResult(BaseModel):
    voxel_count: int
    volume_ml: float
    inference_time_ms: float
    model_name: str
    organ: str
    organ_display_name: str
    mask_size_bytes: int | None = None
    attempts: int | None = None


class JobResponse(BaseModel):
    """Everything a caller needs to render "how is my job doing"."""

    job_id: str
    status: str  # queued | retrying | running | completed | failed | canceled
    dead_lettered: bool = False
    progress: int = 0
    stage: str = "queued"
    stage_label: str = ""
    attempt: int = 0
    max_attempts: int = 1
    organ: str = ""
    file_name: str = ""
    enqueued_at: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    error: str | None = None
    result: SegmentationResult | None = None
    mask_available: bool = False


class QueueStats(BaseModel):
    queued: int
    scheduled: int
    started: int
    workers: int
    dead_lettered: int
    max_queue_depth: int


class HealthResponse(BaseModel):
    status: str
    redis: str
    queue: str
    stats: QueueStats | None = None


class DeadLetterEntry(BaseModel):
    job_id: str
    organ: str = ""
    file_name: str = ""
    attempts: int = 0
    max_attempts: int = 1
    stage: str = ""
    progress: int = 0
    enqueued_at: str | None = None
    failed_at: str | None = None
    error: str = ""
    exc_type: str = ""
    traceback: str = ""
    replayable: bool = False


class DeadLetterList(BaseModel):
    total: int
    entries: list[DeadLetterEntry]


class OrganInfo(BaseModel):
    key: str
    display_name: str


class OrgansResponse(BaseModel):
    organs: list[OrganInfo]
    default: str


class MessageResponse(BaseModel):
    message: str
    detail: Any | None = None
