from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


UploadAssetCategoryValue = Literal[
    "product_reference",
    "model_template",
    "garment",
    "style_reference",
    "temporary",
]
GeneratedAssetCategoryValue = Literal[
    "listing_output",
    "batch_tryon_output",
    "aplus_output",
]
AssetCategoryValue = UploadAssetCategoryValue | GeneratedAssetCategoryValue
ProjectTypeValue = Literal["listing", "batch_tryon", "aplus"]
ProjectStatusValue = Literal["draft", "archived"]


class AssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    category: str
    filename: str
    mime_type: str
    size: int
    width: int
    height: int
    sha256: str
    created_by: str
    created_at: datetime
    updated_at: datetime
    url: str | None = None
    url_expires_at: datetime | None = None


class AssetPage(BaseModel):
    items: list[AssetResponse]
    total: int
    limit: int
    offset: int


class AssetUrlResponse(BaseModel):
    asset_id: str
    url: str
    expires_at: datetime | None = None


class ProjectVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    version_number: int
    draft_json: dict[str, object]
    change_summary: str | None
    created_by: str
    created_at: datetime


class ProjectAssetResponse(BaseModel):
    id: str
    role: str
    sort_order: int
    asset: AssetResponse
    created_at: datetime


class ProjectResponse(BaseModel):
    id: str
    project_type: str
    name: str
    description: str | None
    status: str
    created_by: str
    updated_by: str
    created_at: datetime
    updated_at: datetime
    latest_version: ProjectVersionResponse
    assets: list[ProjectAssetResponse] = Field(default_factory=list)


class ProjectPage(BaseModel):
    items: list[ProjectResponse]
    total: int
    limit: int
    offset: int


class ProjectCreateRequest(BaseModel):
    project_type: ProjectTypeValue
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=500)
    draft: dict[str, object] = Field(default_factory=dict)


class ProjectUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=500)
    status: ProjectStatusValue | None = None


class ProjectVersionCreateRequest(BaseModel):
    draft: dict[str, object]
    expected_version: int = Field(ge=1)
    change_summary: str | None = Field(default=None, max_length=500)


class ProjectAssetCreateRequest(BaseModel):
    asset_id: str
    role: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$", min_length=1, max_length=60)
    sort_order: int = Field(default=0, ge=0, le=10000)
