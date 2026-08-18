from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.session import get_db_session
from app.models.tasks import BatchTryOnPromptPreset
from app.schemas.batch_tryon_workflow import (
    BatchTryOnPromptPresetCreateRequest,
    BatchTryOnPromptPresetResponse,
    BatchTryOnPromptPresetUpdateRequest,
)
from app.security.principal import Principal, require_permissions
from app.services.audit_service import add_audit_log
from app.services.batch_tryon_prompt_template_service import (
    list_available_prompt_presets,
    prompt_preset_response,
)


router = APIRouter(prefix="/batch-tryon/prompt-presets", tags=["batch-tryon-prompt-presets"])


def _organization_id(principal: Principal) -> str:
    if principal.organization is None:
        raise AppError("organization.required", "请先选择团队。", 409)
    return principal.organization.id


async def _editable_preset(
    db: AsyncSession, *, preset_id: str, principal: Principal,
) -> BatchTryOnPromptPreset:
    preset = await db.get(BatchTryOnPromptPreset, preset_id)
    if preset is None:
        raise AppError("batch_tryon.prompt_preset_not_found", "提示词预设不存在。", 404)
    organization_id = _organization_id(principal)
    can_edit_system = principal.is_platform_admin
    can_edit_organization = bool(
        preset.scope == "organization"
        and preset.organization_id == organization_id
        and principal.role_codes.intersection({"platform_admin", "organization_admin"})
    )
    can_edit_user = preset.scope == "user" and preset.owner_user_id == principal.user.id
    if not (can_edit_system or can_edit_organization or can_edit_user):
        raise AppError("batch_tryon.prompt_preset_forbidden", "无权修改该提示词预设。", 403)
    if preset.is_system_preset and not can_edit_system:
        raise AppError("batch_tryon.system_prompt_preset_readonly", "系统预设不可被普通用户覆盖，请另存为个人预设。", 403)
    return preset


@router.get("", response_model=list[BatchTryOnPromptPresetResponse])
async def list_prompt_presets(
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.read")),
) -> list[BatchTryOnPromptPresetResponse]:
    rows = await list_available_prompt_presets(
        db, organization_id=_organization_id(principal), user_id=principal.user.id,
    )
    return [prompt_preset_response(row) for row in rows]


@router.post("", response_model=BatchTryOnPromptPresetResponse, status_code=status.HTTP_201_CREATED)
async def create_prompt_preset(
    payload: BatchTryOnPromptPresetCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> BatchTryOnPromptPresetResponse:
    organization_id = _organization_id(principal)
    if payload.scope == "system" and not principal.is_platform_admin:
        raise AppError("batch_tryon.system_prompt_preset_forbidden", "只有平台管理员可以新增系统预设。", 403)
    if payload.scope == "organization" and not principal.role_codes.intersection({"platform_admin", "organization_admin"}):
        raise AppError("batch_tryon.organization_prompt_preset_forbidden", "只有团队管理员可以新增团队预设。", 403)
    preset = BatchTryOnPromptPreset(
        organization_id=None if payload.scope == "system" else organization_id,
        owner_user_id=principal.user.id if payload.scope == "user" else None,
        scope=payload.scope,
        template_type=payload.template_type,
        label=payload.label.strip(),
        analysis_prompt_template=payload.analysis_prompt_template.strip(),
        enabled=True,
        sort_order=100,
        is_system_preset=payload.scope == "system",
        created_by=principal.user.id,
        updated_by=principal.user.id,
    )
    db.add(preset)
    await db.flush()
    add_audit_log(
        db, request=request, actor_user_id=principal.user.id, organization_id=organization_id,
        action="batch_tryon.prompt_preset.create", resource_type="batch_tryon_prompt_preset",
        resource_id=preset.id, metadata={"scope": preset.scope, "template_type": preset.template_type},
    )
    await db.commit()
    return prompt_preset_response(preset)


@router.patch("/{preset_id}", response_model=BatchTryOnPromptPresetResponse)
async def update_prompt_preset(
    preset_id: str,
    payload: BatchTryOnPromptPresetUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("jobs.submit")),
) -> BatchTryOnPromptPresetResponse:
    preset = await _editable_preset(db, preset_id=preset_id, principal=principal)
    values = payload.model_dump(exclude_unset=True)
    if "label" in values:
        preset.label = str(values["label"]).strip()
    if "analysis_prompt_template" in values:
        preset.analysis_prompt_template = str(values["analysis_prompt_template"]).strip()
    if "enabled" in values:
        preset.enabled = bool(values["enabled"])
    if "sort_order" in values:
        preset.sort_order = int(values["sort_order"])
    preset.updated_by = principal.user.id
    add_audit_log(
        db, request=request, actor_user_id=principal.user.id,
        organization_id=_organization_id(principal), action="batch_tryon.prompt_preset.update",
        resource_type="batch_tryon_prompt_preset", resource_id=preset.id,
        metadata={"changed_fields": sorted(values)},
    )
    await db.commit()
    return prompt_preset_response(preset)
