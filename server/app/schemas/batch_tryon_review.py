from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.tasks import JobResponse


ReviewStatus = Literal["pending", "approved", "rejected", "regenerating", "generation_failed"]
RetryMode = Literal["direct", "with_review_notes", "with_detailed_prompt"]
RegionReplaceType = Literal[
    "back_name", "back_number", "wearer_left_shoulder_number",
    "wearer_right_shoulder_number", "custom_region",
]
ManualErrorCode = Literal["left_right_sleeve", "front_back", "text_number", "color", "detail_composition"]
ReviewTemplateType = Literal[
    "pure_white", "gift_scene", "stadium_scene", "detail_display", "casual_scene", "custom_process",
]


class ReviewAssetResponse(BaseModel):
    id: str
    filename: str
    display_filename: str
    download_filename: str
    download_url: str
    preview_url: str
    width: int
    height: int
    mime_type: str
    size: int


class BatchTryOnVersionResponse(BaseModel):
    id: str
    version_number: int
    parent_version_id: str | None
    generated_asset_id: str | None
    task_id: str | None
    source_filename: str | None
    display_filename: str | None
    download_filename: str | None
    output_format: str | None
    prompt_snapshot: str
    review_notes: str | None
    retry_mode: str
    generation_status: str
    review_status: str
    generated_asset: ReviewAssetResponse | None
    created_at: datetime
    completed_at: datetime | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    generation_duration_ms: int | None = None


class BatchTryOnReviewDetailResponse(BaseModel):
    item_id: str
    batch_id: str
    client_item_id: str
    template_id: str | None = None
    review_status: str
    current_version_id: str | None
    approved_version_id: str | None
    regeneration_count: int
    template_name: str | None = None
    preset_summary: str | None = None
    preset_codes: dict[str, object] | None = None
    template_type: str | None = None
    template_prompt_id: str | None = None
    prompt_version: int | None = None
    effective_prompt_snapshot: str | None = None
    garment_asset: ReviewAssetResponse
    model_asset: ReviewAssetResponse
    image_c_asset: ReviewAssetResponse | None = None
    current_version: BatchTryOnVersionResponse | None
    versions: list[BatchTryOnVersionResponse]


class BatchTryOnApproveRequest(BaseModel):
    source_version_id: str


class BatchTryOnRegenerateRequest(BaseModel):
    source_version_id: str
    retry_mode: RetryMode
    review_notes: str | None = Field(default=None, max_length=10000)
    error_codes: list[ManualErrorCode] = Field(default_factory=list, max_length=5)
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$", min_length=8, max_length=160)

    @model_validator(mode="after")
    def validate_notes(self) -> "BatchTryOnRegenerateRequest":
        notes = self.review_notes.strip() if self.review_notes else None
        if self.retry_mode == "with_review_notes" and not notes and not self.error_codes:
            raise ValueError("review_notes or error_codes is required when retry_mode is with_review_notes")
        if self.retry_mode == "with_detailed_prompt" and not notes:
            raise ValueError("review_notes is required when retry_mode is with_detailed_prompt")
        self.review_notes = notes
        return self


class BatchTryOnRegenerateResponse(BaseModel):
    review: BatchTryOnReviewDetailResponse
    job: JobResponse


class BatchTryOnRegionReplaceRequest(BaseModel):
    source_version_id: str = Field(min_length=1, max_length=36)
    target_mask_asset_id: str = Field(min_length=1, max_length=36)
    image_c_asset_id: str = Field(min_length=1, max_length=36)
    source_reference_mask_asset_id: str | None = Field(default=None, min_length=1, max_length=36)
    reference_patch_asset_id: str = Field(min_length=1, max_length=36)
    edit_region_type: RegionReplaceType
    edit_prompt: str = Field(min_length=1, max_length=10000)
    target_mask_metadata: dict[str, object] = Field(default_factory=dict)
    source_reference_metadata: dict[str, object] = Field(default_factory=dict)
    idempotency_key: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$", min_length=8, max_length=160,
    )

    @model_validator(mode="after")
    def normalize_prompt(self) -> "BatchTryOnRegionReplaceRequest":
        self.edit_prompt = self.edit_prompt.strip()
        if not self.edit_prompt:
            raise ValueError("edit_prompt is required")
        return self


class BatchTryOnRegionReplaceResponse(BaseModel):
    review: BatchTryOnReviewDetailResponse
    job: JobResponse


class BatchTryOnSelectVersionRequest(BaseModel):
    version_id: str = Field(min_length=1, max_length=36)


class BatchTryOnDetailedReviewAnalysisRequest(BaseModel):
    source_version_id: str = Field(min_length=1, max_length=36)
    focus_notes: str | None = Field(default=None, max_length=3000)
    template_type: ReviewTemplateType | None = None
    prompt_preset_id: str | None = Field(default=None, max_length=36)
    template_prompt_override: str | None = Field(default=None, min_length=20, max_length=30000)
    idempotency_key: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
        min_length=8,
        max_length=160,
    )

    @model_validator(mode="after")
    def normalize_focus_notes(self) -> "BatchTryOnDetailedReviewAnalysisRequest":
        self.focus_notes = self.focus_notes.strip() if self.focus_notes else None
        self.template_prompt_override = (
            self.template_prompt_override.strip() if self.template_prompt_override else None
        )
        return self


class BatchTryOnBatchDetailedAnalysisItem(BaseModel):
    item_id: str = Field(min_length=1, max_length=36)
    version_id: str = Field(min_length=1, max_length=36)


class BatchTryOnBatchDetailedAnalysisRequest(BaseModel):
    items: list[BatchTryOnBatchDetailedAnalysisItem] = Field(min_length=1, max_length=200)
    focus_notes: str | None = Field(default=None, max_length=3000)
    template_type: ReviewTemplateType | None = None
    prompt_preset_id: str | None = Field(default=None, max_length=36)
    template_prompt_override: str | None = Field(default=None, min_length=20, max_length=30000)
    auto_regenerate: bool = True
    idempotency_key: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$", min_length=8, max_length=160,
    )

    @model_validator(mode="after")
    def normalize_batch(self) -> "BatchTryOnBatchDetailedAnalysisRequest":
        self.focus_notes = self.focus_notes.strip() if self.focus_notes else None
        self.template_prompt_override = (
            self.template_prompt_override.strip() if self.template_prompt_override else None
        )
        keys = [(item.item_id, item.version_id) for item in self.items]
        if len(keys) != len(set(keys)):
            raise ValueError("items contains duplicate item/version pairs")
        return self


class BatchTryOnBatchDetailedAnalysisTask(BaseModel):
    item_id: str
    source_version_id: str
    analysis_job_id: str
    client_item_id: str
    created: bool
    auto_regenerate: bool


class BatchTryOnBatchDetailedAnalysisError(BaseModel):
    item_id: str
    version_id: str
    code: str
    message: str


class BatchTryOnBatchDetailedAnalysisResponse(BaseModel):
    requested_count: int
    created_count: int
    replayed_count: int
    failed_count: int
    auto_regenerate: bool
    analysis_tasks: list[BatchTryOnBatchDetailedAnalysisTask]
    errors: list[BatchTryOnBatchDetailedAnalysisError]


class BatchTryOnBatchRegenerateItem(BaseModel):
    item_id: str = Field(min_length=1, max_length=36)
    version_id: str = Field(min_length=1, max_length=36)


class BatchTryOnBatchRegenerateRequest(BaseModel):
    items: list[BatchTryOnBatchRegenerateItem] = Field(min_length=1, max_length=500)
    review_notes: str = Field(min_length=1, max_length=10000)
    idempotency_key: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
        min_length=8,
        max_length=160,
    )

    @model_validator(mode="after")
    def validate_batch(self) -> "BatchTryOnBatchRegenerateRequest":
        self.review_notes = self.review_notes.strip()
        if not self.review_notes:
            raise ValueError("review_notes is required")
        keys = [(item.item_id, item.version_id) for item in self.items]
        if len(keys) != len(set(keys)):
            raise ValueError("items contains duplicate item/version pairs")
        return self


class BatchTryOnTemplateExportRequest(BaseModel):
    item_ids: list[str] = Field(min_length=1, max_length=500)
    scope: Literal["approved", "all_succeeded"] = "approved"

    @model_validator(mode="after")
    def validate_items(self) -> "BatchTryOnTemplateExportRequest":
        if any(len(item_id) < 1 or len(item_id) > 36 for item_id in self.item_ids):
            raise ValueError("item_ids contains an invalid review item id")
        if len(self.item_ids) != len(set(self.item_ids)):
            raise ValueError("item_ids contains duplicates")
        return self


class BatchTryOnBatchRegenerateTask(BaseModel):
    item_id: str
    source_version_id: str
    version_id: str
    task_id: str
    client_item_id: str
    template_id: str | None = None
    garment_asset_id: str
    created: bool


class BatchTryOnBatchRegenerateError(BaseModel):
    item_id: str
    version_id: str
    code: str
    message: str


class BatchTryOnBatchRegenerateResponse(BaseModel):
    requested_count: int
    created_count: int
    replayed_count: int
    failed_count: int
    created_tasks: list[BatchTryOnBatchRegenerateTask]
    errors: list[BatchTryOnBatchRegenerateError]
