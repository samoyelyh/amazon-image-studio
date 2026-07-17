from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.session import get_db_session
from app.models.identity import Permission, Role
from app.schemas.identity import PermissionResponse, RoleResponse
from app.security.principal import Principal, require_permissions
from app.services.identity_views import role_response


router = APIRouter(prefix="/rbac", tags=["roles and permissions"])


@router.get("/roles", response_model=list[RoleResponse])
async def list_roles(
    session: AsyncSession = Depends(get_db_session),
    _: Principal = Depends(require_permissions("roles.read")),
) -> list[RoleResponse]:
    roles = list((await session.scalars(select(Role).options(selectinload(Role.permission_links)).order_by(Role.code))).all())
    return [role_response(role) for role in roles]


@router.get("/permissions", response_model=list[PermissionResponse])
async def list_permissions(
    session: AsyncSession = Depends(get_db_session),
    _: Principal = Depends(require_permissions("roles.read")),
) -> list[PermissionResponse]:
    permissions = list((await session.scalars(select(Permission).order_by(Permission.code))).all())
    return [PermissionResponse(code=item.code, name=item.name) for item in permissions]
