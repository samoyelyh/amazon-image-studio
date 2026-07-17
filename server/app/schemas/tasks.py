from datetime import datetime
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


CAPABILITIES = Literal[
    "text_generation", "image_generation", "image_edit", "multi_image_reference",
    "mask_edit", "custom_aspect_ratio", "transparent_background",
]
QUEUES = Literal["planning_queue", "listing_queue", "batch_tryon_queue", "aplus_queue"]
WORKSPACES = Literal["listing", "batch_tryon", "aplus"]


class ProviderCreateRequest(BaseModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_-]*$", max_length=80)
    name: str = Field(min_length=1, max_length=160)
    provider_type: Literal["openai_compatible", "new_api", "custom"]
    base_url: HttpUrl
    config: dict[str, object] = Field(default_factory=dict)

    @field_validator("config")
    @classmethod
    def config_cannot_contain_credentials(cls, value: dict[str, object]) -> dict[str, object]:
        forbidden = {"api_key", "apikey", "token", "secret", "authorization", "password"}
        if _contains_key(value, forbidden):
            raise ValueError("provider credentials must be stored through the API key endpoint")
        return value


class ProviderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    code: str
    name: str
    provider_type: str
    base_url: str
    enabled: bool
    config_json: dict[str, object]


class ProviderModelCreateRequest(BaseModel):
    code: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$", max_length=120)
    upstream_model: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=160)
    capabilities: list[CAPABILITIES] = Field(min_length=1)
    config: dict[str, object] = Field(default_factory=dict)

    @field_validator("capabilities")
    @classmethod
    def unique_capabilities(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class ProviderModelResponse(BaseModel):
    id: str
    provider_id: str
    code: str
    upstream_model: str
    name: str
    enabled: bool
    capabilities: list[str]
    config: dict[str, object]


class ResourcePoolCreateRequest(BaseModel):
    model_id: str
    code: str = Field(pattern=r"^[a-z][a-z0-9_-]*$", max_length=100)
    name: str = Field(min_length=1, max_length=160)
    organization_id: str | None = None
    priority: int = Field(default=100, ge=0, le=10000)
    weight: int = Field(default=100, ge=1, le=10000)


class ApiKeyCreateRequest(BaseModel):
    provider_id: str
    label: str = Field(min_length=1, max_length=160)
    secret: str = Field(min_length=8, max_length=1000)
    organization_id: str | None = None
    max_concurrency: int = Field(default=1, ge=1, le=1000)
    rpm_limit: int | None = Field(default=None, ge=1, le=1_000_000)
    daily_limit: int | None = Field(default=None, ge=1, le=100_000_000)


class ApiKeyResponse(BaseModel):
    id: str
    provider_id: str
    organization_id: str | None
    label: str
    fingerprint: str
    masked_secret: str
    enabled: bool
    status: str
    max_concurrency: int
    rpm_limit: int | None
    daily_limit: int | None
    cooldown_until: datetime | None
    consecutive_failures: int
    current_concurrency: int = 0


class PoolKeyAttachRequest(BaseModel):
    api_key_id: str
    priority: int = Field(default=100, ge=0, le=10000)
    weight: int = Field(default=100, ge=1, le=10000)


class ResourcePoolResponse(BaseModel):
    id: str
    organization_id: str | None
    model_id: str
    model_code: str
    code: str
    name: str
    enabled: bool
    priority: int
    weight: int
    capabilities: list[str]
    key_count: int = 0


class JobSubmitRequest(BaseModel):
    operation_code: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$", max_length=120)
    workspace_type: WORKSPACES
    queue_name: QUEUES
    capability: CAPABILITIES
    model_code: str = Field(min_length=1, max_length=120)
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$", min_length=8, max_length=160)
    project_id: str | None = None
    input: dict[str, object]
    billing_factors: dict[str, str] = Field(default_factory=dict)
    client_item_id: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def validate_queue(self) -> "JobSubmitRequest":
        expected = {
            "listing": "listing_queue", "batch_tryon": "batch_tryon_queue", "aplus": "aplus_queue",
        }[self.workspace_type]
        if self.queue_name not in {expected, "planning_queue"}:
            raise ValueError(f"queue_name must be {expected} or planning_queue for this workspace")
        expected_operation = {
            "listing": "listing.plan" if self.capability == "text_generation" else "listing.generate",
            "batch_tryon": "batch_tryon.generate",
            "aplus": "aplus.plan" if self.capability == "text_generation" else "aplus.generate",
        }[self.workspace_type]
        if self.operation_code != expected_operation:
            raise ValueError(f"operation_code must be {expected_operation} for this workspace and capability")
        image_capabilities = {"image_generation", "image_edit", "multi_image_reference", "mask_edit"}
        if self.capability in image_capabilities and not str(self.input.get("prompt", "")).strip():
            raise ValueError("input.prompt is required for image tasks")
        if self.capability in image_capabilities and self.input.get("n", 1) != 1:
            raise ValueError("one job must generate exactly one image; use a batch for multiple images")
        references = self.input.get("reference_asset_ids", [])
        if not isinstance(references, list) or len(references) > 10 or any(not isinstance(item, str) or not item for item in references):
            raise ValueError("reference_asset_ids must be a list of at most 10 asset IDs")
        if self.capability in {"image_edit", "multi_image_reference", "mask_edit"} and not references:
            raise ValueError("reference_asset_ids are required for image editing")
        if self.capability == "multi_image_reference" and (not isinstance(references, list) or len(references) < 2):
            raise ValueError("multi_image_reference requires at least two reference assets")
        if self.capability == "mask_edit" and not self.input.get("mask_asset_id"):
            raise ValueError("mask_asset_id is required for mask editing")
        if self.input.get("metadata") is not None and not isinstance(self.input.get("metadata"), dict):
            raise ValueError("input.metadata must be an object")
        if len(json.dumps(self.input, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > 131072:
            raise ValueError("job input exceeds 128 KiB")
        forbidden = {"api_key", "apikey", "token", "secret", "authorization", "password"}
        if _contains_key(self.input, forbidden):
            raise ValueError("credentials are not allowed in job input")
        return self


def _contains_key(value: object, forbidden: set[str]) -> bool:
    if isinstance(value, dict):
        return any(str(key).lower() in forbidden or _contains_key(item, forbidden) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_key(item, forbidden) for item in value)
    return False


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    organization_id: str
    batch_id: str | None
    project_id: str | None
    quota_reservation_id: str
    operation_code: str
    workspace_type: str
    queue_name: str
    capability: str
    model_code: str
    client_item_id: str | None
    status: str
    progress: int
    result_json: dict[str, object] | None
    attempts: int
    max_attempts: int
    error_code: str | None
    error_message: str | None
    cancel_requested_at: datetime | None
    started_at: datetime | None
    heartbeat_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime
    outputs: list["JobOutputResponse"] = Field(default_factory=list)


class JobOutputResponse(BaseModel):
    id: str
    asset_id: str
    filename: str
    mime_type: str
    width: int
    height: int
    size: int
    sequence_number: int
    url: str
    url_expires_at: datetime


class JobPage(BaseModel):
    items: list[JobResponse]
    total: int
    limit: int
    offset: int


class BatchJobItemRequest(BaseModel):
    client_item_id: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=30000)
    reference_asset_ids: list[str] = Field(default_factory=list, max_length=10)
    mask_asset_id: str | None = None
    size: str = Field(default="1024x1024", max_length=40)
    quality: str | None = Field(default=None, max_length=40)
    output_format: Literal["png", "jpeg", "webp"] = "png"
    metadata: dict[str, object] = Field(default_factory=dict)


class JobBatchSubmitRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    workspace_type: WORKSPACES
    operation_code: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$", max_length=120)
    capability: CAPABILITIES
    model_code: str = Field(min_length=1, max_length=120)
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$", min_length=8, max_length=160)
    project_id: str | None = None
    concurrency: int = Field(default=2, ge=1, le=10)
    items: list[BatchJobItemRequest] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def validate_batch(self) -> "JobBatchSubmitRequest":
        expected_operation = {
            "listing": "listing.generate", "batch_tryon": "batch_tryon.generate", "aplus": "aplus.generate",
        }[self.workspace_type]
        if self.operation_code != expected_operation:
            raise ValueError(f"operation_code must be {expected_operation}")
        ids = [item.client_item_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("client_item_id values must be unique within a batch")
        return self


class JobBatchResponse(BaseModel):
    id: str
    organization_id: str
    project_id: str | None
    workspace_type: str
    operation_code: str
    name: str | None
    model_code: str | None
    capability: str | None
    status: str
    concurrency: int
    total_jobs: int
    succeeded_jobs: int
    failed_jobs: int
    cancelled_jobs: int
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime
    jobs: list[JobResponse] = Field(default_factory=list)


class JobBatchPage(BaseModel):
    items: list[JobBatchResponse]
    total: int
    limit: int
    offset: int
