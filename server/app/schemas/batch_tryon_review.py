from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.tasks import JobResponse


ReviewStatus = Literal["pending", "approved", "rejected", "regenerating", "generation_failed"]
RetryMode = Literal["direct", "with_review_notes"]


class ReviewAssetResponse(BaseModel):
    id: str
    filename: str
    preview_url: str
    width: int
    height: int
    mime_type: str
    size: int


class BatchTryOnVersionResponse(BaseModel):
    id: str
    version_number: int
    parent_version_id: str | None
    generated_asset_id: str | None
    task_id: str | None
    prompt_snapshot: str
    review_notes: str | None
    retry_mode: str
    generation_status: str
    review_status: str
    generated_asset: ReviewAssetResponse | None
    created_at: datetime
    completed_at: datetime | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    generation_duration_ms: int | None = None


class BatchTryOnReviewDetailResponse(BaseModel):
    item_id: str
    batch_id: str
    client_item_id: str
    review_status: str
    current_version_id: str | None
    approved_version_id: str | None
    regeneration_count: int
    garment_asset: ReviewAssetResponse
    model_asset: ReviewAssetResponse
    current_version: BatchTryOnVersionResponse | None
    versions: list[BatchTryOnVersionResponse]


class BatchTryOnApproveRequest(BaseModel):
    source_version_id: str


class BatchTryOnRegenerateRequest(BaseModel):
    source_version_id: str
    retry_mode: RetryMode
    review_notes: str | None = Field(default=None, max_length=5000)
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$", min_length=8, max_length=160)

    @model_validator(mode="after")
    def validate_notes(self) -> "BatchTryOnRegenerateRequest":
        notes = self.review_notes.strip() if self.review_notes else None
        if self.retry_mode == "with_review_notes" and not notes:
            raise ValueError("review_notes is required when retry_mode is with_review_notes")
        self.review_notes = notes
        return self


class BatchTryOnRegenerateResponse(BaseModel):
    review: BatchTryOnReviewDetailResponse
    job: JobResponse
