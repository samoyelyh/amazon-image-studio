from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Permission, Role, RolePermission, RoleScope


PERMISSIONS = {
    "platform.admin": "Platform administration",
    "users.read": "Read users",
    "users.write": "Create and update users",
    "organizations.read": "Read organizations",
    "organizations.write": "Create and update organizations",
    "organization.members.read": "Read organization members",
    "organization.members.write": "Add, update, and remove organization members",
    "roles.read": "Read roles and permissions",
    "roles.assign": "Assign organization roles",
    "audit.read": "Read audit logs",
    "profile.read": "Read own profile",
    "profile.update": "Update own profile",
}

ROLE_DEFINITIONS: dict[str, tuple[str, str, set[str]]] = {
    "platform_admin": ("Platform administrator", RoleScope.PLATFORM.value, set(PERMISSIONS)),
    "organization_admin": (
        "Organization administrator",
        RoleScope.ORGANIZATION.value,
        {
            "organizations.read", "organizations.write", "organization.members.read",
            "organization.members.write", "roles.read", "roles.assign", "audit.read",
            "profile.read", "profile.update", "users.read", "users.write",
        },
    ),
    "manager": (
        "Manager", RoleScope.ORGANIZATION.value,
        {"organizations.read", "organization.members.read", "roles.read", "profile.read", "profile.update"},
    ),
    "member": ("Member", RoleScope.ORGANIZATION.value, {"organizations.read", "roles.read", "profile.read", "profile.update"}),
    "viewer": ("Viewer", RoleScope.ORGANIZATION.value, {"organizations.read", "profile.read"}),
}


async def sync_rbac(session: AsyncSession) -> dict[str, Role]:
    existing_permissions = {item.code: item for item in (await session.scalars(select(Permission))).all()}
    for code, name in PERMISSIONS.items():
        permission = existing_permissions.get(code)
        if permission is None:
            permission = Permission(code=code, name=name, description=name)
            session.add(permission)
            existing_permissions[code] = permission
        else:
            permission.name = name
            permission.description = name

    existing_roles = {item.code: item for item in (await session.scalars(select(Role))).all()}
    for code, (name, scope, _) in ROLE_DEFINITIONS.items():
        role = existing_roles.get(code)
        if role is None:
            role = Role(code=code, name=name, scope=scope, is_system=True)
            session.add(role)
            existing_roles[code] = role
        else:
            role.name = name
            role.scope = scope
            role.is_system = True

    await session.flush()
    role_ids = [role.id for role in existing_roles.values()]
    existing_links = set(
        (await session.execute(select(RolePermission.role_id, RolePermission.permission_id).where(RolePermission.role_id.in_(role_ids)))).all()
    )
    for code, (_, _, permissions) in ROLE_DEFINITIONS.items():
        role = existing_roles[code]
        desired_ids = {existing_permissions[permission].id for permission in permissions}
        for permission_id in desired_ids:
            if (role.id, permission_id) not in existing_links:
                session.add(RolePermission(role_id=role.id, permission_id=permission_id))
    await session.flush()
    return existing_roles


def permissions_for_role(role: Role | None) -> set[str]:
    if role is None:
        return set()
    return {link.permission.code for link in role.permission_links}


def has_all_permissions(granted: Iterable[str], required: Iterable[str]) -> bool:
    granted_set = set(granted)
    return "platform.admin" in granted_set or set(required).issubset(granted_set)
