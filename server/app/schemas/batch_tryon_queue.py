from datetime import datetime
from pydantic import BaseModel, Field


class QueueNavigation(BaseModel):
    project_id: str | None = None
    workspace_id: str | None = None
    batch_id: str | None = None


class QueueWaitEstimate(BaseModel):
    minimum_seconds: int | None = None
    maximum_seconds: int | None = None
    sample_count: int = 0
    reason: str


class SharedQueueEntry(BaseModel):
    id: str
    name: str
    creator_name: str
    created_at: datetime
    status: str
    archived: bool = False
    archived_at: str | None = None
    total_count: int
    completed_count: int
    processed_count: int
    running_count: int
    waiting_count: int
    failed_count: int
    cancelled_count: int
    retrying_count: int
    analysis_running: int = 0
    auxiliary_running: int = 0
    ahead_count: int | None = None
    progress_percent: int
    can_open: bool
    navigation: QueueNavigation | None = None
    estimate: QueueWaitEstimate


class SharedQueueCapacity(BaseModel):
    configured: int
    effective: int
    in_use: int
    source: str
    reason: str


class SharedQueueBoard(BaseModel):
    snapshot_at: datetime
    entries: list[SharedQueueEntry] = Field(default_factory=list)
    running_count: int
    waiting_count: int
    failed_count: int
    analysis_running: int
    capacity: SharedQueueCapacity
    truncated: bool = False
