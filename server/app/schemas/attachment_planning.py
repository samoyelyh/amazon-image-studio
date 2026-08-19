from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.content import AssetResponse


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
    reference_context_dirty: bool
    reference_state_version: int
    reference_analysis_job_id: str | None
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
    reference_understanding_id: str | None = None
    created_by: str
    created_at: datetime


class AttachmentReferenceCreateRequest(BaseModel):
    slot_type: Literal["PRODUCT", "TEMPLATE", "SCENE", "PRINT", "OTHER"]
    asset_id: str = Field(min_length=36, max_length=36)
    metadata: dict[str, object] = Field(default_factory=dict)


class AttachmentProductReferenceRequest(BaseModel):
    asset_id: str = Field(min_length=36, max_length=36)
    source_asset_id: str | None = Field(default=None, min_length=36, max_length=36)
    view_role: Literal["front", "back", "detail"]
    transform_metadata: dict[str, object] = Field(default_factory=dict)


class AttachmentReferenceAnalyzeRequest(BaseModel):
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$", min_length=8, max_length=160)


class AttachmentReferenceSlotDefinitionResponse(BaseModel):
    slot_type: str
    required: bool
    recommended: bool
    max_items: int


class AttachmentProductReferenceItemResponse(BaseModel):
    id: str
    asset: AssetResponse
    source_asset_id: str | None
    view_role: str
    sort_order: int
    source: str
    transform_metadata: dict[str, object]


class AttachmentModuleReferenceResponse(BaseModel):
    id: str
    slot_type: str
    asset: AssetResponse
    sort_order: int
    metadata: dict[str, object]


class AttachmentReferenceUnderstandingResponse(BaseModel):
    id: str
    version_number: int
    status: str
    structured: dict[str, object]
    source_snapshot: dict[str, object]
    ai_job_id: str | None
    ai_model: str | None
    error_message: str | None
    created_at: datetime


class AttachmentModuleReferenceStateResponse(BaseModel):
    module_key: str
    slot_definitions: list[AttachmentReferenceSlotDefinitionResponse]
    references: list[AttachmentModuleReferenceResponse]
    reference_context_dirty: bool
    reference_state_version: int
    reference_analysis_job_id: str | None
    understanding: AttachmentReferenceUnderstandingResponse | None


class AttachmentReferenceStateResponse(BaseModel):
    product_group_id: str
    product_state_version: int
    product_references: list[AttachmentProductReferenceItemResponse]
    modules: list[AttachmentModuleReferenceStateResponse]


class AttachmentGenerationSelectionRequest(BaseModel):
    selected_module_keys: list[str] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def unique_modules(self) -> "AttachmentGenerationSelectionRequest":
        if len(self.selected_module_keys) != len(set(self.selected_module_keys)):
            raise ValueError("selected_module_keys must be unique")
        return self


class AttachmentGenerationRequest(AttachmentGenerationSelectionRequest):
    snapshot_signature: str = Field(pattern=r"^[a-f0-9]{64}$")
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$", min_length=8, max_length=160)


class AttachmentGenerationModulePreviewResponse(BaseModel):
    module_key: str
    module_name: str
    aspect_ratio: str
    image_count: int
    generation_mode: str
    delivery_width: int
    delivery_height: int
    plan_version_id: str
    plan_version_number: int
    prompt_version_id: str
    prompt_version_number: int
    reference_understanding_id: str
    reference_understanding_version: int
    reference_count: int


class AttachmentGenerationPreviewResponse(BaseModel):
    project_id: str
    model_code: str
    modules: list[AttachmentGenerationModulePreviewResponse]
    total_images: int
    snapshot_signature: str


class AttachmentGenerationResponse(BaseModel):
    project_id: str
    batch_id: str
    task_group_id: str
    group_number: int
    status: str
    job_ids: list[str]
    module_keys: list[str]
    total_images: int
    created: bool


class AttachmentOutputReviewRequest(BaseModel):
    status: Literal["approved", "rejected"]
    expected_review_state_version: int = Field(ge=0)
    clear_final_if_rejected: bool = False


class AttachmentOutputStateResponse(BaseModel):
    output_id: str
    module_key: str
    review_status: Literal["pending_review", "approved", "rejected"]
    review_state_version: int
    reviewed_at: datetime | None
    discarded_at: datetime | None
    is_final: bool
    module_state_version: int


class AttachmentModuleResultStateResponse(BaseModel):
    module_key: str
    current_final_output_id: str | None
    results_cleared_at: datetime | None
    state_version: int
    visible_output_count: int
    history_output_count: int
    pending_review_count: int
    approved_count: int
    rejected_count: int


class AttachmentResultStateResponse(BaseModel):
    project_id: str
    total_outputs: int
    reviewed_outputs: int
    final_module_count: int
    modules: list[AttachmentModuleResultStateResponse]


class AttachmentModuleKeysRequest(BaseModel):
    module_keys: list[str] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def unique_result_modules(self) -> "AttachmentModuleKeysRequest":
        if len(self.module_keys) != len(set(self.module_keys)):
            raise ValueError("module_keys must be unique")
        return self


class AttachmentRetryJobRequest(BaseModel):
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$", min_length=8, max_length=160)
