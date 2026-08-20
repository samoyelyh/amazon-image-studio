from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class PresetVersionResponse(BaseModel):
    id: str
    version_number: int
    full_prompt_template: str
    change_summary: str
    created_at: datetime


class VisualPresetResponse(BaseModel):
    id: str
    code: str
    name: str
    short_description: str
    category_scope: list[str]
    recommended_modules: list[str]
    recommended_model_tags: list[str]
    tags: list[str]
    current_version_id: str
    current_version_number: int
    sort_order: int
    is_active: bool
    is_default: bool
    prompt_template: str | None = None


class ThemePresetResponse(BaseModel):
    id: str
    code: str
    name: str
    short_description: str
    tags: list[str]
    current_version_id: str
    current_version_number: int
    sort_order: int
    is_active: bool
    prompt_template: str | None = None


class PresetCreateRequest(BaseModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{1,79}$")
    name: str = Field(min_length=1, max_length=160)
    short_description: str = Field(min_length=1, max_length=500)
    full_prompt_template: str = Field(min_length=20, max_length=60000)
    tags: list[str] = Field(default_factory=list, max_length=30)
    sort_order: int = Field(default=100, ge=0, le=10000)


class VisualPresetCreateRequest(PresetCreateRequest):
    category_scope: list[str] = Field(default_factory=list, max_length=50)
    recommended_modules: list[str] = Field(default_factory=list, max_length=20)
    recommended_model_tags: list[str] = Field(default_factory=list, max_length=30)
    is_default: bool = False


class ThemePresetCreateRequest(PresetCreateRequest):
    pass


class PresetUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    short_description: str | None = Field(default=None, min_length=1, max_length=500)
    full_prompt_template: str | None = Field(default=None, min_length=20, max_length=60000)
    tags: list[str] | None = Field(default=None, max_length=30)
    sort_order: int | None = Field(default=None, ge=0, le=10000)
    is_active: bool | None = None
    change_summary: str = Field(default="管理员更新", max_length=500)


class VisualPresetUpdateRequest(PresetUpdateRequest):
    category_scope: list[str] | None = Field(default=None, max_length=50)
    recommended_modules: list[str] | None = Field(default=None, max_length=20)
    recommended_model_tags: list[str] | None = Field(default=None, max_length=30)
    is_default: bool | None = None


class ThemePresetUpdateRequest(PresetUpdateRequest):
    pass


class AIModelReferenceResponse(BaseModel):
    id: str
    reference_role: str
    asset_id: str
    source_job_id: str | None
    sort_order: int


class AIModelIdentityResponse(BaseModel):
    id: str
    version_number: int
    status: str
    identity_prompt_snapshot: str
    identity_asset_id: str | None
    identity_job_id: str | None
    reference_batch_id: str | None
    confirmed_at: datetime | None
    published_at: datetime | None
    references: list[AIModelReferenceResponse]


class AIModelPresetResponse(BaseModel):
    id: str
    code: str
    name: str
    display_name: str
    gender_presentation: str
    age_range: str
    body_type: str
    short_description: str
    recommended_visual_presets: list[str]
    recommended_modules: list[str]
    tags: list[str]
    cover_asset_id: str | None
    current_identity_version_id: str | None
    status: str
    sort_order: int
    is_active: bool
    is_published: bool
    identity_prompt: str | None = None
    generation_prompt: str | None = None
    negative_constraints: str | None = None
    current_identity: AIModelIdentityResponse | None = None


class AIModelPresetUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    display_name: str | None = Field(default=None, min_length=1, max_length=160)
    short_description: str | None = Field(default=None, min_length=1, max_length=500)
    identity_prompt: str | None = Field(default=None, min_length=20, max_length=30000)
    generation_prompt: str | None = Field(default=None, min_length=20, max_length=30000)
    negative_constraints: str | None = Field(default=None, max_length=10000)
    recommended_visual_presets: list[str] | None = Field(default=None, max_length=30)
    recommended_modules: list[str] | None = Field(default=None, max_length=20)
    tags: list[str] | None = Field(default=None, max_length=30)
    sort_order: int | None = Field(default=None, ge=0, le=10000)
    is_active: bool | None = None


class AIModelGenerateRequest(BaseModel):
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$", min_length=8, max_length=160)


class AIModelReferencePackRequest(AIModelGenerateRequest):
    roles: list[Literal["FULL_BODY_FRONT", "THREE_QUARTER_LEFT", "THREE_QUARTER_RIGHT", "PORTRAIT"]] = Field(
        default_factory=lambda: ["FULL_BODY_FRONT", "THREE_QUARTER_LEFT", "THREE_QUARTER_RIGHT", "PORTRAIT"],
        min_length=1,
        max_length=4,
    )

    @model_validator(mode="after")
    def unique_roles(self) -> "AIModelReferencePackRequest":
        if len(self.roles) != len(set(self.roles)):
            raise ValueError("roles must be unique")
        return self


class ModelSelectionResponse(BaseModel):
    product_slot: int
    source: str
    model: AIModelPresetResponse
    identity_version_id: str


class AttachmentCreativeContextResponse(BaseModel):
    visual_preset: VisualPresetResponse
    theme_preset: ThemePresetResponse | None
    model_selection_mode: Literal["recommended", "selected", "none"] | str
    selected_models: list[ModelSelectionResponse]
    creative_context_version: int
    planning_stale: bool


class AttachmentCreativeContextUpdate(BaseModel):
    visual_preset_id: str = Field(min_length=36, max_length=36)
    theme_preset_id: str | None = Field(default=None, min_length=36, max_length=36)
    model_selection_mode: Literal["recommended", "selected", "none"]
    selected_model_identity_version_ids: list[str] = Field(default_factory=list, max_length=3)
    expected_creative_context_version: int = Field(ge=0)

    @model_validator(mode="after")
    def selection_matches_mode(self) -> "AttachmentCreativeContextUpdate":
        if self.model_selection_mode == "selected" and not self.selected_model_identity_version_ids:
            raise ValueError("selected mode requires at least one model identity")
        if self.model_selection_mode != "selected" and self.selected_model_identity_version_ids:
            raise ValueError("only selected mode accepts explicit model identities")
        if len(self.selected_model_identity_version_ids) != len(set(self.selected_model_identity_version_ids)):
            raise ValueError("model identities must be unique")
        return self
