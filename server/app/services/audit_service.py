from datetime import datetime, timezone

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import AuditLog, LoginAudit


UTC = timezone.utc


def client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()[:64]
    return request.client.host[:64] if request.client else None


def user_agent(request: Request) -> str | None:
    value = request.headers.get("user-agent")
    return value[:500] if value else None


def add_login_audit(
    session: AsyncSession,
    *,
    request: Request,
    event: str,
    outcome: str,
    account: str | None = None,
    user_id: str | None = None,
    organization_id: str | None = None,
    detail: str | None = None,
) -> None:
    session.add(LoginAudit(
        user_id=user_id,
        organization_id=organization_id,
        account=account,
        event=event,
        outcome=outcome,
        ip_address=client_ip(request),
        user_agent=user_agent(request),
        detail=detail[:500] if detail else None,
        created_at=datetime.now(UTC),
    ))


def add_audit_log(
    session: AsyncSession,
    *,
    request: Request,
    actor_user_id: str | None,
    organization_id: str | None,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    metadata: dict[str, object] | None = None,
) -> None:
    session.add(AuditLog(
        actor_user_id=actor_user_id,
        organization_id=organization_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        request_id=getattr(request.state, "request_id", None),
        ip_address=client_ip(request),
        metadata_json=metadata,
        created_at=datetime.now(UTC),
    ))


async def list_audit_logs(
    session: AsyncSession,
    organization_id: str | None,
    limit: int,
    offset: int,
) -> list[AuditLog]:
    statement = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
    if organization_id is not None:
        statement = statement.where(AuditLog.organization_id == organization_id)
    return list((await session.scalars(statement)).all())


async def list_login_audits(
    session: AsyncSession,
    organization_id: str | None,
    limit: int,
    offset: int,
) -> list[LoginAudit]:
    statement = select(LoginAudit).order_by(LoginAudit.created_at.desc()).limit(limit).offset(offset)
    if organization_id is not None:
        statement = statement.where(LoginAudit.organization_id == organization_id)
    return list((await session.scalars(statement)).all())
