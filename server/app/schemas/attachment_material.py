from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.content import AssetResponse


class AttachmentMaterialSaveRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=255)
    tags: list[str] = Field(default_factory=list, max_length=12)
    note: str = Field(default="", max_length=4000)
    material_set_id: str | None = None
    save_mode: Literal["update_existing", "new"] = "update_existing"

    @model_validator(mode="after")
    def normalize_text(self) -> "AttachmentMaterialSaveRequest":
        self.display_name = self.display_name.strip()
        if not self.display_name:
            raise ValueError("素材包名称不能为空")
        self.tags = list(dict.fromkeys(value.strip()[:40] for value in self.tags if value.strip()))
        self.note = self.note.strip()
        return self


class AttachmentMaterialMetadataUpdateRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=255)
    tags: list[str] = Field(default_factory=list, max_length=12)
    note: str = Field(default="", max_length=4000)

    @model_validator(mode="after")
    def normalize_text(self) -> "AttachmentMaterialMetadataUpdateRequest":
        self.display_name = self.display_name.strip()
        self.tags = list(dict.fromkeys(value.strip()[:40] for value in self.tags if value.strip()))
        self.note = self.note.strip()
        return self


class AttachmentMaterialItemResponse(BaseModel):
    id: str
    module_key: str
    source_output_id: str | None
    source_asset_id: str
    source_task_group_id: str | None
    source_job_id: str | None
    plan_version_id: str | None
    prompt_version_id: str | None
    reference_understanding_id: str | None
    product_composition_version_id: str | None
    aspect_ratio: str
    output_size: str
    generation_mode: str
    product_mode: str
    is_manual_revision: bool
    created_at: datetime
    asset: AssetResponse


class AttachmentMaterialVersionResponse(BaseModel):
    id: str
    version_number: int
    content_hash: str
    selected_module_snapshot: list[str]
    module_count: int
    target_module_count: int
    is_complete: bool
    changed_module_keys: list[str] = Field(default_factory=list)
    created_by: str
    created_at: datetime
    items: list[AttachmentMaterialItemResponse] = Field(default_factory=list)


class AttachmentMaterialSetSummaryResponse(BaseModel):
    id: str
    category_key: str
    category_name: str
    product_name: str
    display_name: str
    source_session_id: str | None
    source_project_id: str | None
    cover_asset_id: str | None
    selected_module_snapshot: list[str]
    tags: list[str]
    note: str
    is_complete: bool
    status: str
    current_version_number: int
    module_count: int
    target_module_count: int
    owner_user_id: str
    created_at: datetime
    updated_at: datetime
    cover_asset: AssetResponse | None = None


class AttachmentMaterialSetDetailResponse(AttachmentMaterialSetSummaryResponse):
    current_version_id: str | None
    versions: list[AttachmentMaterialVersionResponse] = Field(default_factory=list)


class AttachmentMaterialSetPage(BaseModel):
    items: list[AttachmentMaterialSetSummaryResponse]
    total: int
    limit: int
    offset: int


class AttachmentMaterialSaveResponse(BaseModel):
    material_set: AttachmentMaterialSetDetailResponse
    created_set: bool
    created_version: bool
    unchanged: bool


class AttachmentMaterialSaveContextResponse(BaseModel):
    project_id: str
    default_name: str
    existing_material_set_id: str | None
    existing_display_name: str | None
    suggested_tags: list[str] = Field(default_factory=list)
