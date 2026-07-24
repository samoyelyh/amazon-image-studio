from app.models.identity import OrganizationMember, Role
from app.schemas.identity import (
    CurrentIdentityResponse,
    MembershipResponse,
    OrganizationResponse,
    RoleResponse,
    UserResponse,
)
from app.security.principal import Principal
from app.security.rbac import permissions_for_role


def role_response(role: Role) -> RoleResponse:
    return RoleResponse(
        id=role.id,
        code=role.code,
        name=role.name,
        scope=role.scope,
        permissions=sorted(permissions_for_role(role)),
    )


def membership_response(membership: OrganizationMember) -> MembershipResponse:
    return MembershipResponse(
        id=membership.id,
        user=UserResponse.model_validate(membership.user),
        organization=OrganizationResponse.model_validate(membership.organization),
        role=role_response(membership.role),
        status=membership.status,
        invited_by=membership.invited_by,
        created_at=membership.created_at,
    )


def current_identity_response(principal: Principal) -> CurrentIdentityResponse:
    memberships = [
        membership_response(item)
        for item in principal.user.memberships
        if item.status == "active" and item.organization.status == "active"
    ]
    return CurrentIdentityResponse(
        user=UserResponse.model_validate(principal.user),
        organization=OrganizationResponse.model_validate(principal.organization) if principal.organization else None,
        role_codes=sorted(principal.role_codes),
        permissions=sorted(principal.permissions),
        memberships=memberships,
    )
