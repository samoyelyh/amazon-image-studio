from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class AttachmentOutputEditItemRequest(BaseModel):
    source_output_id: str = Field(min_length=36, max_length=36)
    instruction: str = Field(min_length=1, max_length=10000)
    edit_scope: Literal["whole_image", "product", "model", "background", "text", "custom"] = "whole_image"
    reference_asset_ids: list[str] = Field(default_factory=list, max_length=6)
    library_item_ids: list[str] = Field(default_factory=list, max_length=6)
    override_confirmed: bool = False


class AttachmentOutputEditRequest(AttachmentOutputEditItemRequest):
    idempotency_key: str = Field(min_length=8, max_length=160)


class AttachmentOutputBatchEditRequest(BaseModel):
    items: list[AttachmentOutputEditItemRequest] = Field(min_length=1, max_length=24)
    idempotency_key: str = Field(min_length=8, max_length=160)
    concurrency: int = Field(default=6, ge=1, le=12)


class AttachmentOutputEditRevisionResponse(BaseModel):
    id: str
    listing_image_project_id: str
    module_key: str
    root_output_id: str
    parent_output_id: str
    result_output_id: str | None
    job_id: str | None
    batch_id: str | None
    revision_number: int
    status: str
    instruction: str
    edit_scope: str
    explicit_overrides: list[str]
    override_confirmed: bool
    execution_snapshot: dict[str, object]
    error_message: str | None
    created_at: datetime


class AttachmentOutputEditSubmitResponse(BaseModel):
    batch_id: str
    task_group_id: str
    revisions: list[AttachmentOutputEditRevisionResponse]
