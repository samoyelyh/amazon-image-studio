from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class PermissionResponse(BaseModel):
    code: str
    name: str


class RoleResponse(BaseModel):
    id: str
    code: str
    name: str
    scope: str
    permissions: list[str] = Field(default_factory=list)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr
    display_name: str
    status: str
    auth_provider: str
    created_at: datetime
    updated_at: datetime


class OrganizationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str
    status: str
    created_at: datetime
    updated_at: datetime


class MembershipResponse(BaseModel):
    id: str
    user: UserResponse
    organization: OrganizationResponse
    role: RoleResponse
    status: str
    created_at: datetime


class CurrentIdentityResponse(BaseModel):
    user: UserResponse
    organization: OrganizationResponse | None
    role_codes: list[str]
    permissions: list[str]
    memberships: list[MembershipResponse]


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)
    organization_id: str | None = None


class SwitchOrganizationRequest(BaseModel):
    organization_id: str


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    identity: CurrentIdentityResponse


class ProfileUpdateRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)


class OrganizationCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", min_length=2, max_length=80)


class MemberCreateRequest(BaseModel):
    email: EmailStr
    role_code: str = Field(pattern=r"^[a-z_]+$", max_length=80)
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    temporary_password: str | None = Field(default=None, min_length=12, max_length=256)


class MemberRoleUpdateRequest(BaseModel):
    role_code: str = Field(pattern=r"^[a-z_]+$", max_length=80)


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str | None
    actor_user_id: str | None
    action: str
    resource_type: str
    resource_id: str | None
    request_id: str | None
    ip_address: str | None
    metadata_json: dict[str, object] | None
    created_at: datetime


class AuditLogPage(BaseModel):
    items: list[AuditLogResponse]
    limit: int
    offset: int


class LoginAuditResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str | None
    organization_id: str | None
    email: str | None
    event: str
    outcome: str
    ip_address: str | None
    user_agent: str | None
    detail: str | None
    created_at: datetime


class LoginAuditPage(BaseModel):
    items: list[LoginAuditResponse]
    limit: int
    offset: int
