from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


GenerationMode = Literal["normal_tryon", "detail_tryon"]
PromptMode = Literal["direct", "ai_analysis", "ai_detailed"]
PromptStatus = Literal["draft", "analyzing", "ready", "effective", "stale", "failed"]
TemplateType = Literal[
    "pure_white", "gift_scene", "stadium_scene", "detail_display", "casual_scene", "custom_process",
]
GarmentView = Literal["auto", "front", "back", "front_back", "detail"]


class BatchTryOnWorkflowTemplate(BaseModel):
    template_id: str = Field(min_length=1, max_length=120)
    asset_id: str = Field(min_length=1, max_length=36)
    name: str = Field(min_length=1, max_length=255)
    order: int = Field(ge=0, le=999)
    focus_area: str | None = Field(default=None, max_length=80)
    crop_type: str | None = Field(default=None, max_length=80)
    detail_priority: str | None = Field(default=None, max_length=500)
    visible_regions: list[str] = Field(default_factory=list, max_length=20)
    template_type: TemplateType = "pure_white"
    prompt_preset_id: str | None = Field(default=None, max_length=36)
    analysis_prompt: str | None = Field(default=None, min_length=20, max_length=30000)
    garment_view: GarmentView = "auto"
    prompt_strategy: Literal["preset", "ai_optimize", "luna_per_image"] | None = None


class BatchTryOnWorkflowGarment(BaseModel):
    garment_id: str = Field(min_length=1, max_length=120)
    asset_id: str = Field(min_length=1, max_length=36)
    filename: str = Field(min_length=1, max_length=255)
    order: int = Field(ge=0, le=9999)
    font_reference_asset_id: str | None = Field(default=None, max_length=36)
    front_reference_asset_id: str | None = Field(default=None, max_length=36)
    back_reference_asset_id: str | None = Field(default=None, max_length=36)
    detail_reference_asset_id: str | None = Field(default=None, max_length=36)


class BatchTryOnWorkflowCombination(BaseModel):
    client_item_id: str = Field(min_length=1, max_length=120)
    template_id: str = Field(min_length=1, max_length=120)
    garment_id: str = Field(min_length=1, max_length=120)
    order: int = Field(ge=0, le=9999)
    size: str | None = Field(default=None, max_length=40)
    aspect_ratio: str | None = Field(default=None, max_length=40)
    requested_width: int | None = Field(default=None, ge=1, le=16384)
    requested_height: int | None = Field(default=None, ge=1, le=16384)
    font_reference_asset_id: str | None = Field(default=None, max_length=36)


class BatchTryOnWorkflowCreateRequest(BaseModel):
    project_id: str
    name: str = Field(min_length=1, max_length=160)
    idempotency_key: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$", min_length=8, max_length=160,
    )
    generation_mode: GenerationMode = "normal_tryon"
    prompt_mode: PromptMode = "direct"
    templates: list[BatchTryOnWorkflowTemplate] = Field(min_length=1, max_length=10)
    garments: list[BatchTryOnWorkflowGarment] = Field(min_length=1, max_length=50)
    combinations: list[BatchTryOnWorkflowCombination] | None = Field(default=None, min_length=1, max_length=500)
    preset_selection: dict[str, str | None] = Field(default_factory=dict)
    extra_requirements: str = Field(default="", max_length=10000)
    size: str = Field(default="2048x2048", max_length=40)
    aspect_ratio: str = Field(default="1:1", max_length=40)
    requested_width: int | None = Field(default=None, ge=1, le=16384)
    requested_height: int | None = Field(default=None, ge=1, le=16384)
    quality: str = Field(default="high", max_length=40)
    output_format: Literal["png", "jpeg", "webp"] = "png"
    output_compression: int | None = Field(default=None, ge=1, le=100)
    concurrency: int = Field(default=12, ge=1, le=12)
    admin_test_mode: bool = False
    workspace_batch_id: str | None = Field(default=None, max_length=36)
    submission_kind: Literal["validation", "production"] = "production"

    @model_validator(mode="after")
    def validate_matrix(self) -> "BatchTryOnWorkflowCreateRequest":
        if len(self.templates) * len(self.garments) > 500:
            raise ValueError("template and garment matrix supports at most 500 items")
        template_ids = [item.template_id for item in self.templates]
        garment_ids = [item.garment_id for item in self.garments]
        if len(template_ids) != len(set(template_ids)):
            raise ValueError("template_id values must be unique")
        if len(garment_ids) != len(set(garment_ids)):
            raise ValueError("garment_id values must be unique")
        if self.combinations:
            client_ids = [item.client_item_id for item in self.combinations]
            if len(client_ids) != len(set(client_ids)):
                raise ValueError("combination client_item_id values must be unique")
            if any(item.template_id not in template_ids or item.garment_id not in garment_ids for item in self.combinations):
                raise ValueError("combination references an unknown template or garment")
        if self.generation_mode == "detail_tryon" and any(not item.focus_area for item in self.templates):
            raise ValueError("detail_tryon templates require focus_area")
        return self


class BatchTryOnWorkflowAnalysisJob(BaseModel):
    id: str
    role: Literal["garment_analysis", "template_analysis", "prompt_analysis", "detailed_prompt_analysis"]
    status: str
    error_code: str | None = None
    error_message: str | None = None


class BatchTryOnWorkflowResponse(BaseModel):
    workflow_job_id: str
    project_id: str | None
    generation_mode: GenerationMode
    prompt_mode: PromptMode
    submission_kind: Literal["validation", "production"] = "production"
    workspace_batch_id: str | None = None
    status: Literal[
        "analyzing_garment", "analyzing_templates", "analyzing_prompts", "awaiting_prompt_confirmation", "submitting_batch",
        "generating", "completed", "failed", "cancelled",
    ]
    analysis_call_target: int
    analysis_jobs: list[BatchTryOnWorkflowAnalysisJob] = Field(default_factory=list)
    templates: list[BatchTryOnWorkflowTemplate] = Field(default_factory=list)
    garments: list[BatchTryOnWorkflowGarment] = Field(default_factory=list)
    combinations: list[BatchTryOnWorkflowCombination] = Field(default_factory=list)
    garment_profile: dict[str, object] | None = None
    template_profiles: dict[str, dict[str, object]] = Field(default_factory=dict)
    template_prompts: list["BatchTryOnTemplatePromptResponse"] = Field(default_factory=list)
    batch_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class BatchTryOnPromptPresetResponse(BaseModel):
    id: str
    scope: str
    organization_id: str | None
    owner_user_id: str | None
    template_type: str
    label: str
    analysis_prompt_template: str
    enabled: bool
    sort_order: int
    is_system_preset: bool


class BatchTryOnPromptPresetCreateRequest(BaseModel):
    template_type: TemplateType = "pure_white"
    scope: Literal["user", "organization", "system"] = "user"
    label: str = Field(min_length=1, max_length=160)
    analysis_prompt_template: str = Field(min_length=20, max_length=30000)


class BatchTryOnPromptPresetUpdateRequest(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=160)
    analysis_prompt_template: str | None = Field(default=None, min_length=20, max_length=30000)
    enabled: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=10000)


class BatchTryOnTemplatePromptResponse(BaseModel):
    id: str
    workflow_job_id: str
    template_id: str
    garment_id: str | None
    client_item_id: str | None
    template_type: str
    preset_id: str | None
    template_asset_id: str
    first_garment_asset_id: str
    font_reference_asset_id: str | None
    analysis_job_id: str | None
    analysis_prompt_used: str
    generated_final_prompt: str | None
    edited_final_prompt: str | None
    prompt_status: PromptStatus
    prompt_version: int
    error_code: str | None
    error_message: str | None


class BatchTryOnTemplatePromptSaveRequest(BaseModel):
    edited_final_prompt: str | None = Field(default=None, max_length=30000)


class BatchTryOnTemplatePromptAnalyzeRequest(BaseModel):
    analysis_prompt: str | None = Field(default=None, min_length=20, max_length=30000)


class BatchTryOnWorkflowSubmitRequest(BaseModel):
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$", min_length=8, max_length=160)
