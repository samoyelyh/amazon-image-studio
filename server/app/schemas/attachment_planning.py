from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class AttachmentPlanningModuleInput(BaseModel):
    module_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,59}$")
    aspect_ratio: str = Field(min_length=3, max_length=20)
    operator_requirement_cn: str = Field(default="", max_length=10000)


class AttachmentSuitePlanRequest(BaseModel):
    modules: list[AttachmentPlanningModuleInput] = Field(min_length=1, max_length=6)
    visual_direction_cn: str = Field(default="", max_length=10000)
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$", min_length=8, max_length=160)

    @model_validator(mode="after")
    def unique_modules(self) -> "AttachmentSuitePlanRequest":
        keys = [item.module_key for item in self.modules]
        if len(keys) != len(set(keys)):
            raise ValueError("module_key must be unique")
        return self


class AttachmentModulePlanRequest(BaseModel):
    aspect_ratio: str = Field(min_length=3, max_length=20)
    operator_requirement_cn: str = Field(default="", max_length=10000)
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$", min_length=8, max_length=160)


class AttachmentVisualDirectionUpdate(BaseModel):
    visual_direction_cn: str = Field(max_length=10000)
    expected_state_version: int = Field(ge=0)


class AttachmentModulePlanUpdate(BaseModel):
    plan_summary_cn: str | None = Field(default=None, max_length=10000)
    prompt_cn: str | None = Field(default=None, max_length=60000)
    operator_requirement_cn: str | None = Field(default=None, max_length=10000)
    aspect_ratio: str | None = Field(default=None, min_length=3, max_length=20)
    expected_state_version: int = Field(ge=0)


class AttachmentSkillSourceResponse(BaseModel):
    skill_name: str
    skill_version_id: str | None
    skill_version_number: int | None
    can_view_rules: bool
    module_rule: dict[str, object] | None = None


class AttachmentModulePlanResponse(BaseModel):
    id: str
    module_key: str
    module_name: str
    plan_summary_cn: str
    prompt_cn: str
    operator_requirement_cn: str
    aspect_ratio: str
    source: str
    current_version_number: int
    status: str
    planning_job_id: str | None
    error_message: str | None
    state_version: int
    last_saved_at: datetime | None
    skill_source: AttachmentSkillSourceResponse


class AttachmentPlanningResponse(BaseModel):
    id: str
    project_id: str
    session_id: str
    visual_direction_cn: str
    visual_direction_source: str
    visual_direction_version: int
    planning_status: str
    planning_job_id: str | None
    error_message: str | None
    state_version: int
    last_saved_at: datetime | None
    modules: list[AttachmentModulePlanResponse]


class AttachmentPlanVersionResponse(BaseModel):
    id: str
    version_scope: str
    module_key: str | None
    version_number: int
    action: Literal["phase1_import", "ai_suite_plan", "ai_module_replan", "ai_prompt_optimize", "manual_edit"] | str
    visual_direction_cn: str | None
    plan_summary_cn: str | None
    prompt_cn: str | None
    operator_requirement_cn: str
    aspect_ratio: str | None
    selected_module_keys: list[str]
    skill_version_id: str | None
    source_version_id: str | None
    ai_job_id: str | None
    ai_model: str | None
    created_by: str
    created_at: datetime
