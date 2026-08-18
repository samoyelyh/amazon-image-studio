from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.content import AssetResponse


class PrintAssetGroupCreate(BaseModel):
    code: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$", min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    product_type: str | None = Field(default=None, max_length=100)
    remark: str | None = Field(default=None, max_length=500)


class PrintAssetGroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    product_type: str | None = Field(default=None, max_length=100)
    remark: str | None = Field(default=None, max_length=500)


class PrintAssetGroupResponse(BaseModel):
    id: str
    code: str
    name: str
    product_type: str | None
    remark: str | None
    created_at: datetime
    updated_at: datetime


class PrintAssetCreate(BaseModel):
    asset_id: str
    asset_group_id: str | None = None
    asset_code: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$", min_length=1, max_length=120)
    asset_name: str = Field(min_length=1, max_length=180)
    asset_type: str = Field(default="print", pattern=r"^(print|logo|number|name|graphic)$")
    category: str | None = Field(default=None, max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=30)
    default_position: dict[str, object] | None = None
    allow_rotate: bool = True
    allow_stretch: bool = True
    keep_ratio_default: bool = True
    version: int = Field(default=1, ge=1, le=10000)


class PrintAssetUpdate(BaseModel):
    asset_group_id: str | None = None
    asset_name: str | None = Field(default=None, min_length=1, max_length=180)
    asset_type: str | None = Field(default=None, pattern=r"^(print|logo|number|name|graphic)$")
    category: str | None = Field(default=None, max_length=100)
    tags: list[str] | None = Field(default=None, max_length=30)
    default_position: dict[str, object] | None = None
    allow_rotate: bool | None = None
    allow_stretch: bool | None = None
    keep_ratio_default: bool | None = None
    status: str | None = Field(default=None, pattern=r"^(active|archived)$")


class PrintAssetResponse(BaseModel):
    id: str
    asset_group_id: str | None
    asset_code: str
    asset_name: str
    asset_type: str
    category: str | None
    tags: list[str]
    default_position: dict[str, object] | None
    allow_rotate: bool
    allow_stretch: bool
    keep_ratio_default: bool
    version: int
    status: str
    created_at: datetime
    updated_at: datetime
    asset: AssetResponse


class PrintAssetPage(BaseModel):
    items: list[PrintAssetResponse]
    total: int


class ProductPrintMappingCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=160)
    asset_group_id: str
    product_code: str | None = Field(default=None, max_length=160)
    style_code: str | None = Field(default=None, max_length=160)
    template_code: str | None = Field(default=None, max_length=160)


class ProductPrintMappingResponse(BaseModel):
    id: str
    sku: str
    asset_group_id: str
    product_code: str | None
    style_code: str | None
    template_code: str | None
    created_at: datetime
    updated_at: datetime
