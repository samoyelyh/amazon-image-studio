from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.hermes_client import HermesClient
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.session import get_db_session
from app.models.hermes_agent import HermesConversation, HermesMessage, HermesProposal
from app.schemas.hermes_agent import (
    HermesAction,
    HermesChatRequest,
    HermesConversationCreateRequest,
    HermesConversationResponse,
    HermesMessageResponse,
    HermesProposalApplyResponse,
    HermesProposalResponse,
    HermesStatusResponse,
)
from app.security.principal import Principal, require_permissions
from app.services.audit_service import add_audit_log
from app.services.hermes_agent_service import (
    apply_hermes_proposal,
    conversation_messages,
    get_or_create_conversation,
    send_hermes_message,
)
from app.services.hermes_tool_registry import load_hermes_workbench_context


router = APIRouter(prefix="/attachment-workbench/projects/{project_id}/hermes", tags=["attachment-hermes"])


def _org(principal: Principal) -> str:
    if principal.organization is None:
        raise AppError("organization.required", "请先选择团队", 409)
    return principal.organization.id


def _proposal_response(row: HermesProposal) -> HermesProposalResponse:
    return HermesProposalResponse(
        id=row.id, summary=row.summary,
        actions=[HermesAction.model_validate(item) for item in list(row.actions_json or [])],
        expected_state_signature=row.expected_state_signature, status=row.status,
        result=dict(row.result_json or {}), error_message=row.error_message,
        created_at=row.created_at, applied_at=row.applied_at,
    )


async def _conversation_response(db: AsyncSession, row: HermesConversation) -> HermesConversationResponse:
    messages = await conversation_messages(db, row)
    message_ids = [item.id for item in messages]
    proposals = list((await db.scalars(select(HermesProposal).where(
        HermesProposal.source_message_id.in_(message_ids),
        HermesProposal.organization_id == row.organization_id,
        HermesProposal.user_id == row.user_id,
    ))).all()) if message_ids else []
    by_message = {item.source_message_id: item for item in proposals}
    return HermesConversationResponse(
        id=row.id, project_id=row.listing_image_project_id, title=row.title,
        mode=row.mode, status=row.status, created_at=row.created_at, updated_at=row.updated_at,
        messages=[HermesMessageResponse(
            id=item.id, role=item.role, content=item.content,
            metadata=dict(item.metadata_json or {}), external_response_id=item.external_response_id,
            created_at=item.created_at,
            proposal=_proposal_response(by_message[item.id]) if item.id in by_message else None,
        ) for item in messages],
    )


async def _conversation(
    db: AsyncSession, *, conversation_id: str, project_id: str, principal: Principal,
) -> HermesConversation:
    row = await db.scalar(select(HermesConversation).where(
        HermesConversation.id == conversation_id,
        HermesConversation.organization_id == _org(principal),
        HermesConversation.user_id == principal.user.id,
        HermesConversation.listing_image_project_id == project_id,
    ))
    if row is None:
        raise AppError("hermes.conversation_not_found", "对话不存在或无权访问", 404)
    return row


@router.get("/status", response_model=HermesStatusResponse)
async def hermes_status(
    project_id: str, db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> HermesStatusResponse:
    await load_hermes_workbench_context(db, organization_id=_org(principal), project_id=project_id, user_id=principal.user.id)
    available = await HermesClient(settings).health() if settings.hermes_enabled else False
    if not settings.hermes_enabled:
        message = "Hermes 智能助理尚未启用，现有手工工作台不受影响。"
    elif not available:
        message = "Hermes 服务暂时不可用，现有手工工作台仍可正常使用。"
    else:
        message = "Hermes 智能助理已连接，默认使用建议确认模式。"
    return HermesStatusResponse(
        enabled=settings.hermes_enabled, available=available,
        model=settings.hermes_model, profile=settings.hermes_profile, message=message,
    )


@router.get("/conversations", response_model=list[HermesConversationResponse])
async def list_conversations(
    project_id: str, db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> list[HermesConversationResponse]:
    await load_hermes_workbench_context(db, organization_id=_org(principal), project_id=project_id, user_id=principal.user.id)
    rows = list((await db.scalars(select(HermesConversation).where(
        HermesConversation.organization_id == _org(principal),
        HermesConversation.user_id == principal.user.id,
        HermesConversation.listing_image_project_id == project_id,
    ).order_by(HermesConversation.updated_at.desc()).limit(20))).all())
    return [await _conversation_response(db, item) for item in rows]


@router.post("/conversations", response_model=HermesConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    project_id: str, payload: HermesConversationCreateRequest, request: Request,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> HermesConversationResponse:
    await load_hermes_workbench_context(db, organization_id=_org(principal), project_id=project_id, user_id=principal.user.id)
    row = await get_or_create_conversation(
        db, organization_id=_org(principal), user_id=principal.user.id,
        project_id=project_id, title=payload.title,
    )
    add_audit_log(
        db, request=request, actor_user_id=principal.user.id, organization_id=_org(principal),
        action="hermes.conversation.open", resource_type="hermes_conversation", resource_id=row.id,
        metadata={"project_id": project_id, "mode": row.mode},
    )
    await db.commit()
    await db.refresh(row)
    return await _conversation_response(db, row)


@router.get("/conversations/{conversation_id}", response_model=HermesConversationResponse)
async def get_conversation(
    project_id: str, conversation_id: str, db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> HermesConversationResponse:
    row = await _conversation(db, conversation_id=conversation_id, project_id=project_id, principal=principal)
    return await _conversation_response(db, row)


@router.post("/conversations/{conversation_id}/messages", response_model=HermesConversationResponse)
async def create_message(
    project_id: str, conversation_id: str, payload: HermesChatRequest, request: Request,
    db: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> HermesConversationResponse:
    row = await _conversation(db, conversation_id=conversation_id, project_id=project_id, principal=principal)
    assistant, proposal = await send_hermes_message(
        db, settings, conversation=row, organization_id=_org(principal),
        user_id=principal.user.id, project_id=project_id, content=payload.content,
    )
    add_audit_log(
        db, request=request, actor_user_id=principal.user.id, organization_id=_org(principal),
        action="hermes.message.create", resource_type="hermes_conversation", resource_id=row.id,
        metadata={"assistant_message_id": assistant.id, "proposal_id": proposal.id if proposal else None},
    )
    await db.commit()
    return await _conversation_response(db, row)


@router.post("/proposals/{proposal_id}/apply", response_model=HermesProposalApplyResponse)
async def apply_proposal(
    project_id: str, proposal_id: str, request: Request,
    db: AsyncSession = Depends(get_db_session), settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> HermesProposalApplyResponse:
    proposal = await db.scalar(select(HermesProposal).where(
        HermesProposal.id == proposal_id,
        HermesProposal.organization_id == _org(principal),
        HermesProposal.user_id == principal.user.id,
        HermesProposal.listing_image_project_id == project_id,
    ))
    if proposal is None:
        raise AppError("hermes.proposal_not_found", "提案不存在或无权访问", 404)
    results, signature = await apply_hermes_proposal(
        db, settings, proposal=proposal, organization_id=_org(principal), user_id=principal.user.id,
        permissions=principal.permissions,
    )
    add_audit_log(
        db, request=request, actor_user_id=principal.user.id, organization_id=_org(principal),
        action="hermes.proposal.apply", resource_type="hermes_proposal", resource_id=proposal.id,
        metadata={"project_id": project_id, "tools": [item.get("tool") for item in proposal.actions_json]},
    )
    await db.commit()
    return HermesProposalApplyResponse(proposal=_proposal_response(proposal), state_signature=signature, results=results)


@router.post("/proposals/{proposal_id}/cancel", response_model=HermesProposalResponse)
async def cancel_proposal(
    project_id: str, proposal_id: str, request: Request,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> HermesProposalResponse:
    proposal = await db.scalar(select(HermesProposal).where(
        HermesProposal.id == proposal_id,
        HermesProposal.organization_id == _org(principal),
        HermesProposal.user_id == principal.user.id,
        HermesProposal.listing_image_project_id == project_id,
    ))
    if proposal is None:
        raise AppError("hermes.proposal_not_found", "提案不存在或无权访问", 404)
    if proposal.status != "pending":
        raise AppError("hermes.proposal_not_pending", "该提案已处理，不能重复取消", 409)
    proposal.status = "cancelled"
    add_audit_log(
        db, request=request, actor_user_id=principal.user.id, organization_id=_org(principal),
        action="hermes.proposal.cancel", resource_type="hermes_proposal", resource_id=proposal.id,
        metadata={"project_id": project_id},
    )
    await db.commit()
    return _proposal_response(proposal)
