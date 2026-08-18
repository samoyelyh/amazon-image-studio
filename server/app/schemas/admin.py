from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_serializer

from app.schemas.identity import AuditLogResponse, LoginAuditResponse
from app.schemas.quota import QuotaAccountResponse, QuotaTransactionResponse


class AdminOverviewResponse(BaseModel):
    users_total: int
    users_active: int
    organizations_total: int
    organizations_active: int
    jobs_total: int
    jobs_active: int
    jobs_failed: int
    jobs_succeeded: int
    quota_balance_total: int
    quota_reserved_total: int
    providers_enabled: int
    pools_enabled: int
    keys_enabled: int


class AdminMembershipSummary(BaseModel):
    id: str
    organization_id: str
    organization_name: str
    role_code: str
    status: str
    invited_by: str | None


class AdminUserResponse(BaseModel):
    id: str
    email: EmailStr
    display_name: str
    status: str
    auth_provider: str
    platform_role: str | None
    memberships: list[AdminMembershipSummary]
    must_change_password: bool
    password_changed_at: datetime | None
    temporary_password_created_at: datetime | None
    created_by: str | None
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AdminUserPage(BaseModel):
    items: list[AdminUserResponse]
    total: int
    limit: int
    offset: int


class AdminUserUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    status: Literal["active", "disabled"] | None = None
    platform_admin: bool | None = None


class AdminOrganizationResponse(BaseModel):
    id: str
    name: str
    slug: str
    status: str
    member_count: int
    job_count: int
    active_job_count: int
    quota_balance: int
    quota_reserved: int
    created_at: datetime
    updated_at: datetime


class AdminOrganizationPage(BaseModel):
    items: list[AdminOrganizationResponse]
    total: int
    limit: int
    offset: int


class AdminOrganizationUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    status: Literal["active", "disabled"] | None = None


class AdminQuotaAdjustmentResponse(BaseModel):
    account: QuotaAccountResponse
    transaction: QuotaTransactionResponse


class AdminProviderResponse(BaseModel):
    id: str
    code: str
    name: str
    provider_type: str
    base_url: str
    enabled: bool
    model_count: int
    key_count: int


class AdminProviderTestResponse(BaseModel):
    provider_id: str
    test_type: str = "base"
    model_id: str | None = None
    success: bool
    status_code: int | None
    error_code: str | None
    message: str
    models: list[str]
    checked_at: datetime


class AdminProviderTestRequest(BaseModel):
    test_type: Literal["base", "text_generation", "image_generation", "image_edit", "multi_image_reference"] = "base"
    model_id: str | None = None


class AdminModelResponse(BaseModel):
    id: str
    provider_id: str
    code: str
    upstream_model: str
    name: str
    enabled: bool
    capabilities: list[str]


class AdminPoolResponse(BaseModel):
    id: str
    organization_id: str | None
    organization_name: str | None
    model_id: str
    model_code: str
    code: str
    name: str
    enabled: bool
    priority: int
    weight: int
    key_ids: list[str]
    operation_bindings: dict[str, list[str]] = Field(default_factory=dict)


class AdminApiKeyResponse(BaseModel):
    id: str
    provider_id: str
    organization_id: str | None
    organization_name: str | None
    label: str
    masked_secret: str
    fingerprint: str
    enabled: bool
    status: str
    max_concurrency: int
    rpm_limit: int | None
    daily_limit: int | None
    current_concurrency: int
    consecutive_failures: int
    cooldown_until: datetime | None
    last_used_at: datetime | None


class AdminResourceInventoryResponse(BaseModel):
    providers: list[AdminProviderResponse]
    models: list[AdminModelResponse]
    pools: list[AdminPoolResponse]
    keys: list[AdminApiKeyResponse]


class AdminEnabledUpdateRequest(BaseModel):
    enabled: bool


class AdminJobResponse(BaseModel):
    id: str
    organization_id: str
    organization_name: str
    operation_code: str
    workspace_type: str
    queue_name: str
    capability: str
    model_code: str
    status: str
    progress: int
    attempts: int
    max_attempts: int
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    generation_duration_ms: int
    requested_aspect_ratio: str | None
    requested_width: int | None
    requested_height: int | None
    resolved_provider_size: str | None
    submitted_dimension_field: str | None
    submitted_dimension_value: str | None
    actual_width: int | None
    actual_height: int | None
    size_mismatch: bool
    resource_pool_id: str | None
    provider_id: str | None
    provider_model_id: str | None
    worker_name: str | None
    upstream_request_id: str | None

    @field_serializer("created_at", "started_at", "finished_at", when_used="json")
    def serialize_utc_datetime(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        return aware.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class AdminJobPage(BaseModel):
    items: list[AdminJobResponse]
    total: int
    limit: int
    offset: int


class AdminQueueResponse(BaseModel):
    name: str
    broker_depth: int
    queued_jobs: int
    waiting_for_resource_jobs: int
    running_jobs: int
    retry_waiting_jobs: int
    failed_jobs: int


class AdminQueuePage(BaseModel):
    items: list[AdminQueueResponse]
    redis_ok: bool
    checked_at: datetime


class AdminAuditLogPage(BaseModel):
    items: list[AuditLogResponse]
    total: int
    limit: int
    offset: int


class AdminLoginAuditPage(BaseModel):
    items: list[LoginAuditResponse]
    total: int
    limit: int
    offset: int
