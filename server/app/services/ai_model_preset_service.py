from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.models.creative_presets import AIModelIdentityVersion, AIModelPreset, AIModelPresetReference
from app.models.tasks import Job, JobStatus
from app.schemas.creative_presets import AIModelReferencePackRequest
from app.schemas.tasks import BatchJobItemRequest, JobBatchSubmitRequest, JobSubmitRequest
from app.services.category_listing_service import resolve_bound_model_code
from app.services.task_service import submit_batch, submit_job


UTC = timezone.utc
REFERENCE_PROMPTS = {
    "FULL_BODY_FRONT": "Full-body front view, neutral standing pose, eye-level camera, clean light gray studio background.",
    "THREE_QUARTER_LEFT": "Full-body three-quarter left view, natural neutral pose, clean light gray studio background.",
    "THREE_QUARTER_RIGHT": "Full-body three-quarter right view, natural neutral pose, clean light gray studio background.",
    "PORTRAIT": "Chest-up identity portrait, direct neutral expression, even studio light, clean light gray background.",
}


async def get_model_preset(db: AsyncSession, preset_id: str) -> AIModelPreset:
    preset = await db.get(AIModelPreset, preset_id)
    if preset is None:
        raise AppError("creative_preset.model_not_found", "AI模特预设不存在", 404)
    return preset


async def start_identity_generation(
    db: AsyncSession, settings: Settings, *, preset: AIModelPreset,
    organization_id: str, user_id: str, idempotency_key: str,
) -> tuple[AIModelIdentityVersion, Job, bool]:
    model_code = await resolve_bound_model_code(
        db, organization_id=organization_id, operation_code="listing.generate", capability="image_generation",
    )
    prompt = "\n\n".join((preset.generation_prompt.strip(), preset.identity_prompt.strip(), preset.negative_constraints.strip()))
    number = int(await db.scalar(select(func.max(AIModelIdentityVersion.version_number)).where(
        AIModelIdentityVersion.model_preset_id == preset.id,
    )) or 0) + 1
    job, created = await submit_job(
        db, settings, organization_id=organization_id, user_id=user_id,
        payload=JobSubmitRequest(
            operation_code="listing.generate", workspace_type="listing", queue_name="listing_queue",
            capability="image_generation", model_code=model_code, idempotency_key=idempotency_key,
            project_id=None,
            input={
                "prompt": prompt, "n": 1, "size": "1536x2048", "aspect_ratio": "3:4",
                "requested_width": 1536, "requested_height": 2048,
                "quality": "high", "output_format": "png", "reference_asset_ids": [],
                "metadata": {
                    "workflow": "ai_model_identity_generation", "model_preset_id": preset.id,
                    "identity_version_number": number,
                },
            },
            billing_factors={"workspace": "ai_model_library", "stage": "identity"},
            client_item_id=f"ai-model:{preset.code}:identity:v{number}",
        ),
    )
    existing = await db.scalar(select(AIModelIdentityVersion).where(AIModelIdentityVersion.identity_job_id == job.id))
    if existing:
        return existing, job, created
    identity = AIModelIdentityVersion(
        organization_id=organization_id, model_preset_id=preset.id, version_number=number,
        status="GENERATING", identity_prompt_snapshot=prompt, identity_job_id=job.id,
        created_by=user_id, updated_by=user_id,
    )
    db.add(identity)
    await db.flush()
    preset.status = "GENERATING_IDENTITY"
    preset.updated_by = user_id
    job.input_json = {
        **job.input_json,
        "metadata": {**dict(job.input_json.get("metadata") or {}), "identity_version_id": identity.id},
    }
    return identity, job, created


async def confirm_identity(
    db: AsyncSession, *, preset: AIModelPreset, identity_id: str, user_id: str,
) -> AIModelIdentityVersion:
    identity = await db.get(AIModelIdentityVersion, identity_id)
    if identity is None or identity.model_preset_id != preset.id:
        raise AppError("creative_preset.identity_not_found", "模特身份版本不存在", 404)
    if not identity.identity_asset_id or identity.status not in {"AWAITING_CONFIRMATION", "CONFIRMED"}:
        raise AppError("creative_preset.identity_not_ready", "模特身份图尚未生成完成", 409)
    identity.status = "CONFIRMED"
    identity.confirmed_at = datetime.now(UTC)
    identity.updated_by = user_id
    preset.status = "IDENTITY_CONFIRMED"
    preset.cover_asset_id = identity.identity_asset_id
    preset.updated_by = user_id
    return identity


async def start_reference_pack_generation(
    db: AsyncSession, settings: Settings, *, preset: AIModelPreset,
    identity: AIModelIdentityVersion, payload: AIModelReferencePackRequest,
    organization_id: str, user_id: str,
) -> tuple[object, list[Job], bool]:
    if identity.model_preset_id != preset.id or identity.status not in {
        "CONFIRMED", "REFERENCES_GENERATING", "REFERENCES_FAILED", "REFERENCES_READY",
    }:
        raise AppError("creative_preset.identity_not_confirmed", "请先确认模特身份，再生成参考组", 409)
    if not identity.identity_asset_id:
        raise AppError("creative_preset.identity_asset_missing", "模特身份图不存在", 409)
    existing_roles = set((await db.scalars(select(AIModelPresetReference.reference_role).where(
        AIModelPresetReference.identity_version_id == identity.id,
    ))).all())
    roles = [role for role in payload.roles if role not in existing_roles]
    if not roles:
        raise AppError("creative_preset.references_complete", "所选身份参考视图已经生成完成", 409)
    model_code = await resolve_bound_model_code(
        db, organization_id=organization_id, operation_code="listing.generate", capability="image_edit",
    )
    items = [BatchJobItemRequest(
        client_item_id=f"ai-model:{preset.code}:{role}:v{identity.version_number}",
        prompt=(
            "Use Image 1 only as an immutable person identity reference. Preserve exactly the same adult face, "
            "hairstyle, skin tone, apparent age and body proportions. Ignore the clothing from Image 1. "
            "Dress the person in plain neutral unbranded clothing without logos, graphics, numbers or text. "
            f"{REFERENCE_PROMPTS[role]} Do not create a celebrity likeness."
        ),
        reference_asset_ids=[identity.identity_asset_id], size="1536x2048", aspect_ratio="3:4",
        requested_width=1536, requested_height=2048, quality="high", output_format="png",
        metadata={
            "workflow": "ai_model_reference_generation", "model_preset_id": preset.id,
            "identity_version_id": identity.id, "reference_role": role,
        },
    ) for role in roles]
    batch, jobs, created = await submit_batch(
        db, settings, organization_id=organization_id, user_id=user_id,
        payload=JobBatchSubmitRequest(
            name=f"AI模特 {preset.display_name} 身份参考组 V{identity.version_number}",
            workspace_type="listing", operation_code="listing.generate", capability="image_edit",
            model_code=model_code, idempotency_key=payload.idempotency_key,
            project_id=None, concurrency=min(4, len(items)), items=items,
        ),
    )
    identity.reference_batch_id = batch.id
    identity.status = "REFERENCES_GENERATING"
    identity.updated_by = user_id
    preset.status = "GENERATING_REFERENCES"
    preset.updated_by = user_id
    return batch, jobs, created


async def publish_identity(
    db: AsyncSession, *, preset: AIModelPreset, identity_id: str, user_id: str,
) -> AIModelIdentityVersion:
    identity = await db.get(AIModelIdentityVersion, identity_id)
    if identity is None or identity.model_preset_id != preset.id:
        raise AppError("creative_preset.identity_not_found", "模特身份版本不存在", 404)
    roles = set((await db.scalars(select(AIModelPresetReference.reference_role).where(
        AIModelPresetReference.identity_version_id == identity.id,
    ))).all())
    missing = sorted(set(REFERENCE_PROMPTS) - roles)
    if not identity.identity_asset_id or missing:
        raise AppError("creative_preset.references_incomplete", "身份参考组尚未完成，暂不能发布", 409, {"missing_roles": missing})
    now = datetime.now(UTC)
    identity.status = "PUBLISHED"
    identity.published_at = now
    identity.updated_by = user_id
    preset.current_identity_version_id = identity.id
    preset.cover_asset_id = identity.identity_asset_id
    preset.status = "PUBLISHED"
    preset.is_published = True
    preset.is_active = True
    preset.updated_by = user_id
    return identity


async def continue_ai_model_generation(
    db: AsyncSession, *, job: Job, generated_asset_id: str | None,
) -> None:
    metadata = job.input_json.get("metadata") if isinstance(job.input_json, dict) else None
    metadata = metadata if isinstance(metadata, dict) else {}
    workflow = str(metadata.get("workflow") or "")
    if workflow not in {"ai_model_identity_generation", "ai_model_reference_generation"} or not generated_asset_id:
        return
    identity_id = str(metadata.get("identity_version_id") or "")
    identity = await db.get(AIModelIdentityVersion, identity_id)
    preset = await db.get(AIModelPreset, str(metadata.get("model_preset_id") or ""))
    if identity is None or preset is None or identity.model_preset_id != preset.id:
        return
    if workflow == "ai_model_identity_generation":
        identity.identity_asset_id = generated_asset_id
        identity.status = "PERSONAL_READY" if preset.source_type in {"USER_TEMPORARY", "USER_GENERATED"} else "AWAITING_CONFIRMATION"
        identity.updated_by = job.created_by
        preset.cover_asset_id = generated_asset_id
        preset.current_identity_version_id = identity.id if preset.source_type in {"USER_TEMPORARY", "USER_GENERATED"} else preset.current_identity_version_id
        preset.status = "TEMPORARY_READY" if preset.source_type == "USER_TEMPORARY" else ("PERSONAL_SAVED" if preset.source_type == "USER_GENERATED" else "AWAITING_CONFIRMATION")
        preset.updated_by = job.created_by
        return
    role = str(metadata.get("reference_role") or "")
    existing = await db.scalar(select(AIModelPresetReference).where(
        AIModelPresetReference.identity_version_id == identity.id,
        AIModelPresetReference.reference_role == role,
    ))
    if existing is None and role in REFERENCE_PROMPTS:
        db.add(AIModelPresetReference(
            organization_id=job.organization_id, model_preset_id=preset.id,
            identity_version_id=identity.id, reference_role=role,
            asset_id=generated_asset_id, source_job_id=job.id,
            sort_order=list(REFERENCE_PROMPTS).index(role) + 1,
            created_by=job.created_by, updated_by=job.created_by,
        ))
        await db.flush()
    count = int(await db.scalar(select(func.count(AIModelPresetReference.id)).where(
        AIModelPresetReference.identity_version_id == identity.id,
    )) or 0)
    if count >= len(REFERENCE_PROMPTS):
        identity.status = "REFERENCES_READY"
        preset.status = "READY_TO_PUBLISH"
    identity.updated_by = job.created_by
    preset.updated_by = job.created_by


async def fail_ai_model_generation(db: AsyncSession, *, job: Job) -> None:
    """Reflect terminal Job failures without turning retries or resource waits into false failures."""
    if job.status not in {"failed", "cancelled"}:
        return
    metadata = job.input_json.get("metadata") if isinstance(job.input_json, dict) else None
    metadata = metadata if isinstance(metadata, dict) else {}
    workflow = str(metadata.get("workflow") or "")
    if workflow not in {"ai_model_identity_generation", "ai_model_reference_generation"}:
        return
    identity = await db.get(AIModelIdentityVersion, str(metadata.get("identity_version_id") or ""))
    preset = await db.get(AIModelPreset, str(metadata.get("model_preset_id") or ""))
    if identity is None or preset is None or identity.model_preset_id != preset.id:
        return
    if workflow == "ai_model_identity_generation":
        identity.status = "FAILED"
        preset.status = "FAILED"
    else:
        active = int(await db.scalar(select(func.count(Job.id)).where(
            Job.batch_id == job.batch_id,
            Job.status.in_([
                JobStatus.QUEUED.value,
                JobStatus.RUNNING.value,
                JobStatus.RETRY_WAITING.value,
                JobStatus.WAITING_FOR_RESOURCE.value,
            ]),
        )) or 0) if job.batch_id else 0
        if active:
            return
        completed = int(await db.scalar(select(func.count(AIModelPresetReference.id)).where(
            AIModelPresetReference.identity_version_id == identity.id,
        )) or 0)
        if completed < len(REFERENCE_PROMPTS):
            identity.status = "REFERENCES_FAILED"
            preset.status = "REFERENCES_FAILED"
    identity.updated_by = job.updated_by or job.created_by
    preset.updated_by = job.updated_by or job.created_by
