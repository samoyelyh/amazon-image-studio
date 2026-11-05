from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


class RetentionRule(BaseModel):
    enabled: bool = False
    days: int = Field(default=3, ge=1, le=365)
    age_basis: Literal["created_at", "last_activity"] = "last_activity"
    action: Literal["archive", "pause_archive", "delete"] = "delete"


class RetentionSettings(RetentionRule):
    revision: int = 0
    can_manage: bool = False
    last_run_at: datetime | None = None
    last_run_summary: dict = Field(default_factory=dict)
    pending_storage_count: int = 0


class RetentionSave(RetentionRule):
    expected_revision: int = Field(ge=0)
    confirmation: str = ""


class RetentionRun(BaseModel):
    expected_revision: int = Field(ge=1)
    preview_token: str
    confirmation: str = ""
