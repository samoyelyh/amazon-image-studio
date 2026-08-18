from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.listing_workflow import ImagePromptItem, ImagePromptVersion
from app.models.tasks import Job


UTC = timezone.utc


def _mark_server_update(item: ImagePromptItem) -> None:
    item.state_version += 1
    item.last_saved_at = datetime.now(UTC)

IMAGE_PROMPT_OPTIMIZER_SYSTEM_PROMPT = """You are a professional e-commerce image prompt editor.

Your task is not to translate the Chinese instructions literally.
Your task is to revise and reconstruct the original English image prompt
according to the user's latest Chinese requirements.

Treat the Chinese instructions as editing commands for the existing English prompt.

You must:
- understand what the user wants to add, remove, replace or emphasize;
- remove outdated or conflicting instructions from the original English prompt;
- merge duplicated requirements;
- preserve important product-accuracy constraints;
- rewrite the complete prompt in natural, precise and professional English;
- make the final prompt easy for an image generation model to follow;
- avoid Chinglish and word-for-word translation;
- avoid simply appending translated Chinese text to the original prompt;
- do not add product features that are not supported by the product images or analysis;
- return only the final optimized English prompt."""


def build_image_prompt_optimizer_input(
    *, category_name: str, image_type: str, product_analysis: dict[str, object],
    category_skill_rules: object, original_english_prompt: str, chinese_editing_instruction: str,
) -> tuple[str, str]:
    instruction = chinese_editing_instruction.strip()
    if not instruction:
        raise AppError("prompt_optimizer.chinese_instruction_required", "请先填写中文创作要求", 422)
    user_prompt = f"""Product category:
{category_name}

Image type:
{image_type}

Product analysis:
{product_analysis}

Category skill rules:
{category_skill_rules}

Original English prompt:
{original_english_prompt.strip()}

Latest Chinese editing instructions:
{instruction}
""".strip()
    return IMAGE_PROMPT_OPTIMIZER_SYSTEM_PROMPT, user_prompt


def clean_optimized_prompt(text: str) -> str:
    value = text.strip()
    if value.startswith("```") and value.endswith("```"):
        value = value[3:-3].strip()
        if value.lower().startswith("text\n"):
            value = value[5:].strip()
    if len(value) < 20:
        raise AppError("prompt_optimizer.invalid_result", "AI 返回的英文提示词无效，请重试", 422)
    return value


async def reconcile_prompt_item(db: AsyncSession, item: ImagePromptItem) -> ImagePromptItem:
    if item.status != "optimizing" or not item.optimizer_job_id:
        return item
    job = await db.get(Job, item.optimizer_job_id)
    if job is None:
        item.status = "needs_optimization"
        item.error_message = "优化任务不存在，请重试"
        _mark_server_update(item)
        return item
    if job.status == "failed":
        item.status = "needs_optimization"
        item.error_message = job.error_message or "AI优化失败，请重试"
        _mark_server_update(item)
        return item
    if job.status != "succeeded":
        return item
    existing = await db.scalar(select(ImagePromptVersion).where(ImagePromptVersion.optimizer_job_id == job.id))
    if existing:
        item.optimized_english_prompt = existing.optimized_english_prompt
        item.current_version_number = existing.version_number
        item.optimizer_model = existing.optimizer_model
        item.optimized_at = existing.optimized_at
        item.status = "optimized"
        item.error_message = None
        _mark_server_update(item)
        return item
    metadata = (job.result_json or {}).get("metadata")
    text = str(metadata.get("text") or "") if isinstance(metadata, dict) else ""
    try:
        optimized = clean_optimized_prompt(text)
    except AppError as error:
        item.status = "needs_optimization"
        item.error_message = error.message
        _mark_server_update(item)
        return item
    number = item.current_version_number + 1
    optimized_at = datetime.now(UTC)
    db.add(ImagePromptVersion(
        organization_id=item.organization_id, prompt_item_id=item.id, version_number=number,
        original_english_prompt=item.original_english_prompt,
        chinese_editing_instruction=item.chinese_editing_instruction,
        optimized_english_prompt=optimized, optimizer_model=job.model_code,
        optimizer_job_id=job.id, optimized_at=optimized_at,
        optimized_by=item.updated_by, created_by=item.updated_by,
    ))
    item.optimized_english_prompt = optimized
    item.current_version_number = number
    item.optimizer_model = job.model_code
    item.optimized_at = optimized_at
    item.status = "optimized"
    item.error_message = None
    _mark_server_update(item)
    return item


async def usable_project_prompts(
    db: AsyncSession, *, organization_id: str, project_type: str, project_id: str,
    base_prompts: dict[str, str], selected_items: list[str],
) -> dict[str, str]:
    rows = list((await db.scalars(select(ImagePromptItem).where(
        ImagePromptItem.organization_id == organization_id,
        ImagePromptItem.project_type == project_type,
        ImagePromptItem.project_id == project_id,
        ImagePromptItem.item_code.in_(selected_items),
    ))).all())
    indexed = {item.item_code: await reconcile_prompt_item(db, item) for item in rows}
    blocked = [code for code, item in indexed.items() if item.status in {"needs_optimization", "optimizing"}]
    if blocked:
        raise AppError(
            "prompt_optimizer.pending",
            "部分中文要求尚未同步到英文提示词，请先执行AI优化",
            409, {"items": blocked},
        )
    return {
        code: (indexed[code].optimized_english_prompt if code in indexed else base_prompts[code])
        for code in selected_items
    }
