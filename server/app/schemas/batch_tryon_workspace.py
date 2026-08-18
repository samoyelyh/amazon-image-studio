from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


WorkspaceStatus = Literal["draft", "validating", "ready", "queued", "running", "review", "completed", "failed"]


class BatchTryOnWorkspaceCreateRequest(BaseModel):
    project_id: str = Field(min_length=1, max_length=36)
    name: str | None = Field(default=None, max_length=160)
    config: dict[str, Any] = Field(default_factory=dict)


class BatchTryOnWorkspaceUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    status: WorkspaceStatus | None = None
    config: dict[str, Any] | None = None


class BatchTryOnWorkspaceResponse(BaseModel):
    id: str
    project_id: str | None
    name: str
    status: str
    hidden: bool
    config: dict[str, Any]
    production_batch_ids: list[str] = Field(default_factory=list)
    validation_batch_ids: list[str] = Field(default_factory=list)
    total_jobs: int = 0
    completed_jobs: int = 0
    created_at: datetime
    updated_at: datetime


class BatchTryOnWorkspacePage(BaseModel):
    items: list[BatchTryOnWorkspaceResponse]
    total: int
