from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.schemas.identity import AuditLogPage, AuditLogResponse, LoginAuditPage, LoginAuditResponse
from app.security.principal import Principal, require_permissions
from app.services.audit_service import list_audit_logs, list_login_audits


router = APIRouter(prefix="/audit-logs", tags=["audit logs"])


@router.get("/logins", response_model=LoginAuditPage)
async def get_login_audits(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("audit.read")),
) -> LoginAuditPage:
    organization_id = principal.organization.id if principal.organization else None
    items = await list_login_audits(session, organization_id, limit, offset)
    return LoginAuditPage(
        items=[LoginAuditResponse.model_validate(item) for item in items],
        limit=limit,
        offset=offset,
    )


@router.get("", response_model=AuditLogPage)
async def get_audit_logs(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("audit.read")),
) -> AuditLogPage:
    organization_id = principal.organization.id if principal.organization else None
    items = await list_audit_logs(session, organization_id, limit, offset)
    return AuditLogPage(
        items=[AuditLogResponse.model_validate(item) for item in items],
        limit=limit,
        offset=offset,
    )
