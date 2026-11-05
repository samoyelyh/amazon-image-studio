from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.tasks import BatchTryOnPromptPreset, BatchTryOnTemplatePrompt
from app.prompts.batch_tryon_prompt_templates import SUPPORTED_TEMPLATE_TYPES
from app.prompts.batch_tryon_direct import DIRECT_REPLACEMENT_PRESET_ID, DIRECT_REPLACEMENT_LABEL, DIRECT_REPLACEMENT_PROMPT
from app.schemas.batch_tryon_workflow import (
    BatchTryOnPromptPresetResponse,
    BatchTryOnTemplatePromptResponse,
    BatchTryOnWorkflowTemplate,
)


PROMPT_STATUSES = {"draft", "analyzing", "ready", "effective", "stale", "failed"}


async def seed_direct_replacement_preset(session: AsyncSession) -> None:
    # Insert only. Admin edits and disabled presets must survive restarts.
    if await session.get(BatchTryOnPromptPreset, DIRECT_REPLACEMENT_PRESET_ID) is None:
        session.add(BatchTryOnPromptPreset(id=DIRECT_REPLACEMENT_PRESET_ID,
            scope="system", template_type="casual_scene", label=DIRECT_REPLACEMENT_LABEL,
            analysis_prompt_template=DIRECT_REPLACEMENT_PROMPT, enabled=True, sort_order=51,
            is_system_preset=True))
        await session.flush()


def prompt_preset_response(value: BatchTryOnPromptPreset) -> BatchTryOnPromptPresetResponse:
    return BatchTryOnPromptPresetResponse(
        id=value.id,
        scope=value.scope,
        organization_id=value.organization_id,
        owner_user_id=value.owner_user_id,
        template_type=value.template_type,
        label=value.label,
        analysis_prompt_template=value.analysis_prompt_template,
        enabled=value.enabled,
        sort_order=value.sort_order,
        is_system_preset=value.is_system_preset,
        execution_mode="direct_output" if value.id == DIRECT_REPLACEMENT_PRESET_ID else "standard",
    )


def template_prompt_response(value: BatchTryOnTemplatePrompt, analysis_job=None) -> BatchTryOnTemplatePromptResponse:
    metadata = (analysis_job.result_json or {}).get("metadata", {}) if analysis_job else {}
    return BatchTryOnTemplatePromptResponse(
        id=value.id,
        workflow_job_id=value.workflow_job_id,
        template_id=value.template_id,
        garment_id=value.garment_id,
        client_item_id=value.client_item_id,
        template_type=value.template_type,
        preset_id=value.preset_id,
        template_asset_id=value.template_asset_id,
        first_garment_asset_id=value.first_garment_asset_id,
        font_reference_asset_id=value.font_reference_asset_id,
        analysis_job_id=value.analysis_job_id,
        analysis_prompt_used=value.analysis_prompt_used,
        generated_final_prompt=value.generated_final_prompt,
        edited_final_prompt=value.edited_final_prompt,
        prompt_status=value.prompt_status,
        prompt_version=value.prompt_version,
        error_code=value.error_code,
        error_message=value.error_message,
        structured_analysis=metadata.get("structured_analysis"),
        requires_manual_review=bool(metadata.get("requires_manual_review")) and value.prompt_status != "effective",
    )


async def list_available_prompt_presets(
    session: AsyncSession, *, organization_id: str, user_id: str, include_disabled: bool = False,
) -> list[BatchTryOnPromptPreset]:
    statement = select(BatchTryOnPromptPreset).where(or_(
        BatchTryOnPromptPreset.scope == "system",
        (BatchTryOnPromptPreset.scope == "organization") & (BatchTryOnPromptPreset.organization_id == organization_id),
        (BatchTryOnPromptPreset.scope == "user") & (BatchTryOnPromptPreset.owner_user_id == user_id),
    ))
    if not include_disabled:
        statement = statement.where(BatchTryOnPromptPreset.enabled.is_(True))
    return list((await session.scalars(statement.order_by(
        BatchTryOnPromptPreset.sort_order, BatchTryOnPromptPreset.label, BatchTryOnPromptPreset.id,
    ))).all())


async def resolve_prompt_preset(
    session: AsyncSession, *, organization_id: str, user_id: str,
    preset_id: str | None, template_type: str,
) -> BatchTryOnPromptPreset:
    if template_type not in SUPPORTED_TEMPLATE_TYPES:
        raise AppError("batch_tryon.template_type_unavailable", "当前模板类型尚未开放。", 422)
    if preset_id:
        preset = await session.scalar(select(BatchTryOnPromptPreset).where(
            BatchTryOnPromptPreset.id == preset_id,
            or_(
                BatchTryOnPromptPreset.scope == "system",
                (BatchTryOnPromptPreset.scope == "organization") & (BatchTryOnPromptPreset.organization_id == organization_id),
                (BatchTryOnPromptPreset.scope == "user") & (BatchTryOnPromptPreset.owner_user_id == user_id),
            ),
        ))
    else:
        preset = await session.scalar(select(BatchTryOnPromptPreset).where(
            BatchTryOnPromptPreset.scope == "system",
            BatchTryOnPromptPreset.template_type == template_type,
            BatchTryOnPromptPreset.enabled.is_(True),
        ).order_by(BatchTryOnPromptPreset.sort_order, BatchTryOnPromptPreset.id))
    if preset is None or not preset.enabled:
        raise AppError("batch_tryon.prompt_preset_not_found", "提示词分析预设不存在或已停用。", 404)
    if preset.template_type != template_type:
        raise AppError("batch_tryon.prompt_preset_type_mismatch", "提示词预设与模板类型不匹配。", 422)
    return preset


async def resolve_optional_template_preset(session: AsyncSession, *, organization_id: str,
                                           user_id: str, template: BatchTryOnWorkflowTemplate) -> BatchTryOnPromptPreset | None:
    custom = template.prompt_source == "custom" or (not template.prompt_preset_id and bool(template.analysis_prompt))
    if custom:
        if template.prompt_preset_id:
            raise AppError("batch_tryon.prompt_source_conflict", "自定义提示词模式不应同时绑定预设。", 422)
        if not str(template.analysis_prompt or "").strip():
            raise AppError("batch_tryon.prompt_empty", "请填写当前模板的提示词，预设可以不选。", 422)
        return None
    # Legacy requests which omit both fields retain their existing defaults.
    return await resolve_prompt_preset(session, organization_id=organization_id,
        user_id=user_id, preset_id=template.prompt_preset_id, template_type=template.template_type)


def validate_generated_final_prompt(value: str) -> str:
    prompt = str(value or "").strip()
    if not prompt:
        raise AppError("batch_tryon.prompt_empty", "最终换衣提示词不能为空。", 422)

    # Vision models commonly wrap an otherwise valid final prompt in one outer
    # Markdown code fence.  That is presentation formatting, not evidence that
    # the model returned its analysis.  Remove only a complete outer fence so
    # genuine analysis-only responses are still rejected below.
    lines = prompt.splitlines()
    if len(lines) >= 3 and lines[0].strip().lower() in {"```", "```text", "```markdown", "```md"} \
            and lines[-1].strip() == "```":
        prompt = "\n".join(lines[1:-1]).strip()
        if not prompt:
            raise AppError("batch_tryon.prompt_empty", "最终换衣提示词不能为空。", 422)

    if len(prompt) > 30000:
        raise AppError("batch_tryon.prompt_analysis_invalid", "AI返回的最终换衣提示词过长，请重新分析。", 422)
    lowered = prompt.lower()
    if lowered.startswith("analysis:") or prompt.startswith("分析过程"):
        raise AppError("batch_tryon.prompt_analysis_invalid", "AI返回了分析说明而不是最终换衣提示词，请重新分析。", 422)
    return prompt


def prompt_analysis_preset_only(value: str) -> str:
    """Return the original preset text from snapshots created by older workers.

    Older Luna jobs appended service-owned detailed-analysis and reference-order
    instructions to the selected preset. New jobs must send the preset verbatim;
    trimming these exact legacy suffix markers keeps old workflows re-analysable
    without reintroducing those instructions.
    """
    prompt = str(value or "").strip()
    markers = (
        "\n\n精细逐图分析要求：图A是当前组合的模板图",
        "\n\nREFERENCE IMAGE ORDER:\n",
    )
    positions = [position for marker in markers if (position := prompt.find(marker)) >= 0]
    return prompt[:min(positions)].rstrip() if positions else prompt


def effective_prompt_text(value: BatchTryOnTemplatePrompt) -> str | None:
    edited = str(value.edited_final_prompt or "").strip()
    generated = str(value.generated_final_prompt or "").strip()
    return edited or generated or None
