from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.tasks import JobOutputResponse


class CategoryCreateRequest(BaseModel):
    category_code: str = Field(pattern=r"^[a-z][a-z0-9_]*$", min_length=2, max_length=100)
    category_name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=1000)
    is_active: bool = True
    sort_order: int = Field(default=100, ge=0, le=100000)


class CategoryUpdateRequest(BaseModel):
    category_name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=1000)
    is_active: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=100000)
    default_skill_id: str | None = None
    default_image_template_id: str | None = None


class CategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    category_code: str
    category_name: str
    description: str | None
    is_active: bool
    sort_order: int
    default_skill_id: str | None
    default_skill_name: str | None = None
    default_image_template_id: str | None
    default_image_template_name: str | None = None
    default_image_types: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class CategorySkillCreateRequest(BaseModel):
    category_id: str
    skill_name: str = Field(min_length=1, max_length=160)
    skill_code: str = Field(pattern=r"^[a-z][a-z0-9_]*$", min_length=2, max_length=120)
    is_active: bool = True
    version: int = Field(default=1, ge=1, le=100000)
    analysis_prompt: str = Field(min_length=20, max_length=30000)
    listing_title_prompt: str = Field(min_length=10, max_length=30000)
    bullet_points_prompt: str = Field(min_length=10, max_length=30000)
    a_plus_prompt: str = Field(min_length=10, max_length=30000)
    image_prompt_template: str = Field(min_length=20, max_length=30000)
    image_types_config: list[dict[str, object]] = Field(min_length=1, max_length=20)
    prompt_rules: dict[str, object] = Field(default_factory=dict)


class CategorySkillUpdateRequest(BaseModel):
    skill_name: str | None = Field(default=None, min_length=1, max_length=160)
    is_active: bool | None = None
    analysis_prompt: str | None = Field(default=None, min_length=20, max_length=30000)
    listing_title_prompt: str | None = Field(default=None, min_length=10, max_length=30000)
    bullet_points_prompt: str | None = Field(default=None, min_length=10, max_length=30000)
    a_plus_prompt: str | None = Field(default=None, min_length=10, max_length=30000)
    image_prompt_template: str | None = Field(default=None, min_length=20, max_length=30000)
    image_types_config: list[dict[str, object]] | None = Field(default=None, min_length=1, max_length=20)
    prompt_rules: dict[str, object] | None = None


class CategorySkillResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    category_id: str
    skill_name: str
    skill_code: str
    is_active: bool
    version: int
    analysis_prompt: str
    listing_title_prompt: str
    bullet_points_prompt: str
    a_plus_prompt: str
    image_prompt_template: str
    image_types_config: list[dict[str, object]]
    prompt_rules: dict[str, object]
    description: str | None = None
    marketplace: str = "amazon_us"
    language: str = "en-US_zh-CN"
    status: str = "draft"
    default_published_version_id: str | None = None
    created_at: datetime
    updated_at: datetime


class CategoryImageTemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    category_id: str
    template_name: str
    template_code: str
    version: int
    is_active: bool
    system_prompt: str
    image_type_prompts: dict[str, str]
    default_image_types: list[str]
    created_at: datetime
    updated_at: datetime


class CategoryImageTemplateCreateRequest(BaseModel):
    category_id: str
    template_name: str = Field(min_length=1, max_length=160)
    template_code: str = Field(pattern=r"^[a-z][a-z0-9_]*$", min_length=2, max_length=120)
    version: int = Field(default=1, ge=1, le=100000)
    is_active: bool = True
    system_prompt: str = Field(min_length=20, max_length=30000)
    image_type_prompts: dict[str, str] = Field(min_length=1, max_length=20)
    default_image_types: list[str] = Field(min_length=1, max_length=10)


class CategoryImageTemplateUpdateRequest(BaseModel):
    template_name: str | None = Field(default=None, min_length=1, max_length=160)
    is_active: bool | None = None
    system_prompt: str | None = Field(default=None, min_length=20, max_length=30000)
    image_type_prompts: dict[str, str] | None = Field(default=None, min_length=1, max_length=20)
    default_image_types: list[str] | None = Field(default=None, min_length=1, max_length=10)


class RecommendCategoryRequest(BaseModel):
    product_image_asset_ids: list[str] = Field(min_length=1, max_length=10)
    idempotency_key: str = Field(min_length=8, max_length=160)


class RecommendationJobResponse(BaseModel):
    job_id: str
    status: str


class CategoryRecommendationResponse(BaseModel):
    job_id: str
    status: str
    category_id: str | None = None
    category_code: str | None = None
    category_name: str | None = None
    confidence: float | None = None
    reason: str | None = None
    error_message: str | None = None


class AnalyzeProductRequest(BaseModel):
    product_image_asset_ids: list[str] = Field(min_length=1, max_length=10)
    primary_asset_id: str | None = None
    selected_category_id: str
    project_id: str | None = None
    idempotency_key: str = Field(min_length=8, max_length=160)

    @model_validator(mode="after")
    def validate_primary(self) -> "AnalyzeProductRequest":
        if self.primary_asset_id and self.primary_asset_id not in self.product_image_asset_ids:
            raise ValueError("primary_asset_id must be included in product_image_asset_ids")
        return self


class AnalyzeProductResponse(BaseModel):
    session_id: str
    project_id: str | None
    job_id: str
    status: str


class QuickListingOptionsResponse(BaseModel):
    category_id: str
    category_name: str
    skill_id: str
    skill_name: str
    skill_version_id: str
    skill_version_number: int
    default_image_types: list[str]
    default_variation_plan_count: int = 0
    default_variation_image_count: int = 0


class QuickListingGenerateRequest(BaseModel):
    product_image_asset_ids: list[str] = Field(min_length=1, max_length=10)
    primary_asset_id: str | None = None
    selected_category_id: str
    selected_image_types: list[str] | None = Field(default=None, min_length=1, max_length=10)
    idempotency_key: str = Field(min_length=8, max_length=160)
    concurrency: int = Field(default=3, ge=1, le=5)
    size: str = Field(default="2048x2048", max_length=40)
    aspect_ratio: str = Field(default="1:1", max_length=40)
    requested_width: int = Field(default=2048, ge=256, le=8192)
    requested_height: int = Field(default=2048, ge=256, le=8192)
    quality: str = Field(default="high", max_length=40)
    output_format: Literal["png", "jpeg", "webp"] = "png"
    include_default_variations: bool = False

    @model_validator(mode="after")
    def validate_primary(self) -> "QuickListingGenerateRequest":
        if self.primary_asset_id and self.primary_asset_id not in self.product_image_asset_ids:
            raise ValueError("primary_asset_id must be included in product_image_asset_ids")
        return self


class QuickListingGenerateResponse(BaseModel):
    session_id: str
    planning_job_id: str
    status: str
    category_name: str
    skill_name: str
    skill_version_number: int
    selected_image_types: list[str]


class QuickListingStatusResponse(BaseModel):
    session_id: str
    stage: str
    status: str
    category_name: str
    skill_name: str
    skill_version_number: int | None
    selected_image_types: list[str]
    listing_version_id: str | None = None
    listing_version_number: int | None = None
    listing_summary: dict[str, object] | None = None
    listing_image_project_id: str | None = None
    task_group_id: str | None = None
    task_group_status: str | None = None
    target_url: str | None = None
    error_message: str | None = None


class ListingSessionUpdateRequest(BaseModel):
    structured_attributes: dict[str, object] | None = None
    listing_content: dict[str, object] | None = None
    user_prompt: str | None = Field(default=None, max_length=30000)
    current_step: int | None = Field(default=None, ge=1, le=10)
    expected_state_version: int | None = Field(default=None, ge=0)


class ListingContentOptimizationRequest(BaseModel):
    direction: Literal["en_to_zh", "zh_to_en"]
    listing_content: dict[str, object]
    idempotency_key: str = Field(min_length=8, max_length=160)


class ListingContentOptimizationResponse(BaseModel):
    session_id: str
    job_id: str
    status: str
    direction: Literal["en_to_zh", "zh_to_en"]
    listing_content: dict[str, object] | None = None
    error_message: str | None = None


class PromptSnapshotResponse(BaseModel):
    system_prompt: str
    skill_prompt: str
    analysis_segment: str
    user_prompt: str
    final_prompt: str
    final_prompts: dict[str, str]


class ListingSessionResponse(BaseModel):
    id: str
    project_id: str | None
    category_id: str
    category_code: str
    category_name: str
    skill_id: str
    skill_name: str
    skill_version_id: str | None = None
    skill_version_number: int | None = None
    category_skill_snapshot: dict[str, object] | None = None
    status: str
    listing_version_id: str | None = None
    listing_version_number: int | None = None
    confirmed_at: datetime | None = None
    confirmed_by: str | None = None
    planning_job_id: str | None
    planning_job_status: str | None
    image_batch_id: str | None
    image_batch_status: str | None
    source_asset_ids: list[str]
    primary_asset_id: str | None
    structured_attributes: dict[str, object]
    listing_content: dict[str, object]
    default_image_types: list[str]
    prompt: PromptSnapshotResponse | None
    error_message: str | None
    state_version: int = 0
    current_step: int = 2
    last_saved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ListingSessionSummaryResponse(BaseModel):
    id: str
    category_name: str
    skill_name: str
    skill_version_number: int | None = None
    status: str
    listing_version_number: int | None = None
    confirmed_at: datetime | None = None
    primary_asset_id: str | None = None
    source_asset_ids: list[str]
    listing_title_en: str = ""
    listing_title_zh: str = ""
    variation_enabled: bool = False
    updated_at: datetime


class ConfirmListingRequest(BaseModel):
    structured_attributes: dict[str, object] | None = None
    listing_content: dict[str, object] | None = None


class OutputProjectSummary(BaseModel):
    exists: bool
    project_id: str | None = None
    status: str | None = None
    listing_version_number: int | None = None
    outdated: bool = False


class OutputOptionsResponse(BaseModel):
    session_id: str
    listing_confirmed: bool
    listing_version_id: str | None
    listing_version_number: int | None
    listing_snapshot: dict[str, object]
    category_name: str
    skill_name: str
    skill_version_number: int | None
    primary_asset_id: str | None
    source_asset_ids: list[str]
    confirmed_at: datetime | None
    listing_image_project: OutputProjectSummary
    a_plus_project: OutputProjectSummary


class OutputProjectCreateRequest(BaseModel):
    session_id: str
    adopt_latest_listing: bool = False


class OutputProjectUpdateRequest(BaseModel):
    selected_template: str | None = Field(default=None, max_length=120)
    prompt_config: dict[str, object] | None = None
    modules: list[dict[str, object]] | None = Field(default=None, max_length=20)
    adopt_latest_listing: bool = False
    expected_state_version: int | None = Field(default=None, ge=0)


class OutputProjectResponse(BaseModel):
    id: str
    session_id: str
    kind: Literal["listing_image", "a_plus"]
    status: str
    selected_template: str | None
    prompt_config: dict[str, object]
    modules: list[dict[str, object]]
    task_count: int
    generated_asset_ids: list[str]
    last_batch_id: str | None
    last_batch_status: str | None
    listing_version_id: str
    listing_version_number: int
    latest_listing_version_number: int
    outdated: bool
    listing_snapshot: dict[str, object]
    analysis_snapshot: dict[str, object]
    category_skill_snapshot: dict[str, object]
    source_asset_ids: list[str]
    primary_asset_id: str | None
    category_name: str
    skill_name: str
    state_version: int = 0
    last_saved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class APlusBuildModulesRequest(BaseModel):
    template_code: str = Field(default="standard", max_length=120)
    module_codes: list[str] | None = Field(default=None, max_length=12)


class APlusBuildModulesResponse(BaseModel):
    project_id: str
    modules: list[dict[str, object]]


class ProjectPromptBuildRequest(BaseModel):
    selected_items: list[str] | None = Field(default=None, max_length=20)
    prompt_overrides: dict[str, str] = Field(default_factory=dict)
    module_attribute_overrides: dict[str, dict[str, object]] = Field(default_factory=dict)


class ProjectPromptBuildResponse(BaseModel):
    project_id: str
    prompts: dict[str, str]
    modules: list[dict[str, object]] = Field(default_factory=list)


class OutputProjectGenerateRequest(BaseModel):
    selected_items: list[str] | None = Field(default=None, max_length=20)
    prompt_overrides: dict[str, str] = Field(default_factory=dict)
    model_code: str | None = Field(default=None, max_length=120)
    idempotency_key: str = Field(min_length=8, max_length=160)
    concurrency: int = Field(default=3, ge=1, le=5)
    size: str = Field(default="2048x2048", max_length=40)
    aspect_ratio: str = Field(default="1:1", max_length=40)
    requested_width: int = Field(default=2048, ge=256, le=8192)
    requested_height: int = Field(default=2048, ge=256, le=8192)
    quality: str = Field(default="high", max_length=40)
    output_format: Literal["png", "jpeg", "webp"] = "png"


class OutputProjectGenerateResponse(BaseModel):
    project_id: str
    batch_id: str
    task_group_id: str | None = None
    group_number: int | None = None
    status: str
    job_ids: list[str]
    items: list[str]


class ListingImageTaskAssetResponse(BaseModel):
    asset_id: str
    role: str
    filename: str
    mime_type: str
    width: int
    height: int
    url: str | None = None
    available: bool = True


class ListingImageTaskResponse(BaseModel):
    id: str
    batch_id: str | None
    image_type: str
    prompt_status: str
    status: str
    progress: int
    final_prompt: str
    model_code: str
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    input_assets: list[ListingImageTaskAssetResponse]
    outputs: list[JobOutputResponse]
    variation_type_code: str | None = None
    variation_type_name: str | None = None
    variation_plan_code: str | None = None
    variation_plan_name: str | None = None
    variation_version: int | None = None
    chinese_prompt: str = ""
    slot_index: int | None = None
    generation_mode: str | None = None
    requested_aspect_ratio: str | None = None
    requested_width: int | None = None
    requested_height: int | None = None
    plan_version_id: str | None = None
    prompt_version_id: str | None = None
    reference_understanding_id: str | None = None
    creative_direction_index: int | None = None
    plan_summary_cn: str = ""
    prompt_cn: str = ""


class ListingImageTaskGroupStatistics(BaseModel):
    total: int
    queued: int
    running: int
    succeeded: int
    failed: int
    cancelled: int


class ListingImageTaskGroupResponse(BaseModel):
    id: str
    batch_id: str | None
    listing_image_project_id: str
    session_id: str
    listing_version_id: str
    listing_version_number: int
    category_skill_version_id: str | None
    skill_version_number: int | None
    category_name: str = ""
    skill_name: str = ""
    listing_summary: dict[str, object] = Field(default_factory=dict)
    workflow_mode: str = "standard"
    variation_types: list[str] = Field(default_factory=list)
    variation_plan_count: int = 0
    source_task_group_id: str | None
    group_number: int
    group_name: str
    status: str
    selected_image_types: list[str]
    input_assets: list[ListingImageTaskAssetResponse]
    tasks: list[ListingImageTaskResponse]
    statistics: ListingImageTaskGroupStatistics
    progress: int
    created_by: str
    created_at: datetime
    updated_at: datetime


class ListingImageTaskGroupPage(BaseModel):
    items: list[ListingImageTaskGroupResponse]
    total: int


class ListingImageTaskGroupRetryRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=160)


class ImageVariationOptionsResponse(BaseModel):
    project_id: str
    session_id: str
    category_name: str
    skill_name: str
    skill_version_id: str | None
    skill_version_number: int | None
    product_asset_ids: list[str]
    primary_asset_id: str | None
    max_total_images: int
    quick_defaults: list[dict[str, object]]
    types: list[dict[str, object]]


class ImageVariationPlanDraft(BaseModel):
    type_code: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,39}$")
    plan_code: str = Field(default="", max_length=40)
    plan_key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,39}$")
    name: str = Field(min_length=1, max_length=120)
    custom: bool = False
    chinese_instruction: str = Field(default="", max_length=30000)
    count: int = Field(default=1, ge=1, le=4)


class ImageVariationPromptBuildRequest(BaseModel):
    plans: list[ImageVariationPlanDraft] = Field(min_length=1, max_length=20)


class ImageVariationPromptResponse(BaseModel):
    item_code: str
    type_code: str
    type_name: str
    plan_code: str
    plan_key: str
    plan_name: str
    custom: bool
    count: int
    recommended_aspect_ratio: str
    preserve_elements: list[str]
    allowed_changes: list[str]
    base_prompt: str
    prompt_item_id: str
    prompt_status: str


class ImageVariationPromptBuildResponse(BaseModel):
    project_id: str
    plans: list[ImageVariationPromptResponse]


class ImageVariationGenerateItem(BaseModel):
    item_code: str = Field(pattern=r"^variation:[a-z][a-z0-9_-]{0,39}:[a-z][a-z0-9_-]{0,39}$", max_length=120)
    count: int = Field(default=1, ge=1, le=4)


class ImageVariationGenerateRequest(BaseModel):
    plans: list[ImageVariationGenerateItem] = Field(min_length=1, max_length=20)
    idempotency_key: str = Field(min_length=8, max_length=160)
    concurrency: int = Field(default=3, ge=1, le=5)
    source_asset_id: str | None = None
    source_task_group_id: str | None = None
    size: str = Field(default="2048x2048", max_length=40)
    aspect_ratio: str = Field(default="1:1", max_length=40)
    requested_width: int = Field(default=2048, ge=256, le=8192)
    requested_height: int = Field(default=2048, ge=256, le=8192)
    quality: str = Field(default="high", max_length=40)
    output_format: Literal["png", "jpeg", "webp"] = "png"

    @model_validator(mode="after")
    def validate_total(self) -> "ImageVariationGenerateRequest":
        if sum(item.count for item in self.plans) > 30:
            raise ValueError("单次智能图片裂变最多生成30张图片")
        if len({item.item_code for item in self.plans}) != len(self.plans):
            raise ValueError("裂变方案不能重复")
        return self


class FreeVariationProjectRequest(BaseModel):
    asset_ids: list[str] = Field(default_factory=list, min_length=0, max_length=10)
    primary_asset_id: str | None = None
    source_session_id: str | None = None

    @model_validator(mode="after")
    def validate_source(self) -> "FreeVariationProjectRequest":
        if not self.source_session_id and not self.asset_ids:
            raise ValueError("请至少上传一张参考图片")
        if self.asset_ids and self.primary_asset_id not in self.asset_ids:
            raise ValueError("主图必须属于当前参考图片")
        return self


class FreeVariationContextUpdateRequest(BaseModel):
    asset_ids: list[str] = Field(min_length=1, max_length=10)
    primary_asset_id: str

    @model_validator(mode="after")
    def validate_primary(self) -> "FreeVariationContextUpdateRequest":
        if self.primary_asset_id not in self.asset_ids:
            raise ValueError("主图必须属于当前参考图片")
        return self


class FreeVariationContextResponse(BaseModel):
    project_id: str
    session_id: str
    category_id: str
    asset_ids: list[str]
    primary_asset_id: str | None
    chinese_prompt: str = ""
    final_english_prompt: str = ""
    prompt_item_id: str | None = None
    prompt_status: str | None = None
    selected_category_id: str | None = None
    template_fragments: list[str] = Field(default_factory=list)


class FreeVariationRecommendationResponse(BaseModel):
    available: bool = False
    category_id: str | None = None
    category_name: str | None = None
    skill_id: str | None = None
    skill_name: str | None = None
    skill_version_id: str | None = None
    skill_version_number: int | None = None
    directions: list[dict[str, object]] = Field(default_factory=list)
    templates: list[dict[str, str]] = Field(default_factory=list)


class FreeVariationPromptBuildRequest(BaseModel):
    chinese_prompt: str = Field(min_length=1, max_length=30000)
    selected_category_id: str | None = None
    template_fragments: list[str] = Field(default_factory=list, max_length=50)


class FreeVariationPromptBuildResponse(BaseModel):
    project_id: str
    session_id: str
    category_id: str
    prompt_item_id: str
    item_code: str
    image_type: str
    base_prompt: str
    chinese_prompt: str
    optimized_english_prompt: str
    prompt_status: str
    recommendation: FreeVariationRecommendationResponse


class FreeVariationGenerateRequest(BaseModel):
    count: int = Field(default=1, ge=1, le=4)
    idempotency_key: str = Field(min_length=8, max_length=160)
    concurrency: int = Field(default=3, ge=1, le=5)
    size: str = Field(default="2048x2048", max_length=40)
    aspect_ratio: str = Field(default="1:1", max_length=40)
    requested_width: int = Field(default=2048, ge=256, le=8192)
    requested_height: int = Field(default=2048, ge=256, le=8192)
    quality: str = Field(default="high", max_length=40)
    output_format: Literal["png", "jpeg", "webp"] = "png"


class BuildImagePromptsRequest(BaseModel):
    session_id: str
    selected_image_types: list[str] | None = Field(default=None, max_length=10)
    user_prompt_override: str | None = Field(default=None, max_length=30000)


class BuildImagePromptsResponse(BaseModel):
    session_id: str
    image_types: list[str]
    prompts: dict[str, str]
    system_prompt: str
    skill_prompt: str
    analysis_segment: str
    user_prompt: str


class GenerateListingImagesRequest(BaseModel):
    session_id: str
    selected_image_types: list[str] | None = Field(default=None, max_length=10)
    user_prompt_override: str | None = Field(default=None, max_length=30000)
    model_code: str | None = Field(default=None, max_length=120)
    idempotency_key: str = Field(min_length=8, max_length=160)
    concurrency: int = Field(default=3, ge=1, le=5)
    size: str = Field(default="2048x2048", max_length=40)
    aspect_ratio: str = Field(default="1:1", max_length=40)
    requested_width: int = Field(default=2048, ge=256, le=8192)
    requested_height: int = Field(default=2048, ge=256, le=8192)
    quality: str = Field(default="high", max_length=40)
    output_format: Literal["png", "jpeg", "webp"] = "png"
    output_compression: int | None = Field(default=None, ge=1, le=100)


class GenerateListingImagesResponse(BaseModel):
    session_id: str
    batch_id: str
    status: str
    job_ids: list[str]
    image_types: list[str]


class ImagePromptItemUpsertRequest(BaseModel):
    project_type: Literal["listing_image", "a_plus"]
    project_id: str
    session_id: str
    prompt_item_id: str = Field(min_length=1, max_length=120)
    category_id: str
    image_type: str = Field(min_length=1, max_length=120)
    original_english_prompt: str = Field(min_length=20, max_length=60000)
    chinese_editing_instruction: str = Field(default="", max_length=30000)
    optimized_english_prompt: str | None = Field(default=None, max_length=60000)
    manual_edit: bool = False
    expected_state_version: int | None = Field(default=None, ge=0)


class ImagePromptOptimizeRequest(ImagePromptItemUpsertRequest):
    idempotency_key: str = Field(min_length=8, max_length=160)


class ImagePromptItemResponse(BaseModel):
    id: str
    project_type: Literal["listing_image", "a_plus"]
    project_id: str
    session_id: str | None
    prompt_item_id: str
    image_type: str
    original_english_prompt: str
    chinese_editing_instruction: str
    optimized_english_prompt: str
    status: Literal["draft", "needs_optimization", "optimizing", "optimized", "manually_edited"]
    current_version_number: int
    optimizer_job_id: str | None
    optimizer_model: str | None
    optimized_at: datetime | None
    error_message: str | None
    state_version: int = 0
    last_saved_at: datetime | None = None


class CategorySkillAdminCreateRequest(BaseModel):
    category_id: str
    skill_name: str = Field(min_length=1, max_length=160)
    skill_code: str = Field(pattern=r"^[a-z][a-z0-9_]*$", min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    marketplace: str = Field(default="amazon_us", min_length=2, max_length=40)
    language: str = Field(default="en-US_zh-CN", min_length=2, max_length=40)
    source_skill_id: str | None = None


class CategorySkillAdminUpdateRequest(BaseModel):
    skill_name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=1000)
    marketplace: str | None = Field(default=None, min_length=2, max_length=40)
    language: str | None = Field(default=None, min_length=2, max_length=40)
    is_active: bool | None = None


class CategorySkillAdminResponse(BaseModel):
    id: str
    category_id: str
    category_name: str
    skill_name: str
    skill_code: str
    description: str | None
    marketplace: str
    language: str
    status: str
    is_active: bool
    default_published_version_id: str | None
    default_version_number: int | None = None
    is_category_default: bool = False
    created_at: datetime
    updated_at: datetime


class CategorySkillVersionCreateRequest(BaseModel):
    source_version_id: str | None = None
    change_summary: str = Field(default="", max_length=1000)


class CategorySkillVersionUpdateRequest(BaseModel):
    analysis_config: dict[str, object]
    listing_config: dict[str, object]
    translation_config: dict[str, object]
    image_prompt_config: dict[str, object]
    a_plus_config: dict[str, object]
    change_summary: str = Field(default="", max_length=1000)


class CategorySkillVersionResponse(BaseModel):
    id: str
    skill_id: str
    version_number: int
    status: Literal["draft", "testing", "published", "disabled", "archived"]
    analysis_config: dict[str, object]
    listing_config: dict[str, object]
    translation_config: dict[str, object]
    image_prompt_config: dict[str, object]
    a_plus_config: dict[str, object]
    full_config_snapshot: dict[str, object]
    change_summary: str
    source_version_id: str | None
    published_by: str | None
    published_at: datetime | None
    created_by: str | None
    created_at: datetime
    updated_at: datetime


class CategorySkillValidationResponse(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    referenced_variables: list[str] = Field(default_factory=list)


class CategorySkillTestRequest(BaseModel):
    product_information: str = Field(default="", max_length=10000)
    sample_analysis: dict[str, object] = Field(default_factory=dict)


class CategorySkillTestResponse(BaseModel):
    validation: CategorySkillValidationResponse
    system_prompt: str
    user_prompt: str
    structured_analysis_preview: dict[str, object]
    bilingual_listing_preview: dict[str, object]
    image_prompts: dict[str, str]
    model: str | None = None
    elapsed_ms: int


class ImagePromptVersionResponse(BaseModel):
    id: str
    version_number: int
    original_english_prompt: str
    chinese_editing_instruction: str
    optimized_english_prompt: str
    optimizer_model: str | None
    optimized_at: datetime


class OptimizeAllImagePromptsRequest(BaseModel):
    project_type: Literal["listing_image", "a_plus"]
    project_id: str
    idempotency_key: str = Field(min_length=8, max_length=140)


class OptimizeAllImagePromptsResponse(BaseModel):
    project_id: str
    items: list[ImagePromptItemResponse]
