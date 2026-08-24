from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.models.attachment_planning import (
    AttachmentOutputEditRevision,
    AttachmentProductIdentityLockVersion,
    AttachmentReferenceLibraryItem,
)
from app.models.content import Asset, GeneratedOutput
from app.models.listing_workflow import ListingImageProject, ListingImageTaskGroup, ListingVersion
from app.models.tasks import Job, JobBatch
from app.schemas.attachment_output_edit import AttachmentOutputEditItemRequest
from app.schemas.attachment_output_edit import AttachmentOutputEditRevisionResponse
from app.schemas.tasks import BatchJobItemRequest, JobBatchSubmitRequest
from app.services.attachment_reference_library_service import latest_library_understanding
from app.services.category_listing_service import resolve_bound_model_code
from app.services.listing_image_task_group_service import build_input_asset_snapshot, create_group_for_batch
from app.services.task_service import submit_batch


UTC = timezone.utc
MAX_EDIT_REFERENCES = 10
VALID_SOURCE_WORKFLOWS = {"attachment_workbench_generation", "attachment_output_edit"}


def revision_response(item: AttachmentOutputEditRevision) -> AttachmentOutputEditRevisionResponse:
    return AttachmentOutputEditRevisionResponse(
        id=item.id, listing_image_project_id=item.listing_image_project_id,
        module_key=item.module_key, root_output_id=item.root_output_id,
        parent_output_id=item.parent_output_id, result_output_id=item.result_output_id,
        job_id=item.job_id, batch_id=item.batch_id, revision_number=item.revision_number,
        status=item.status, instruction=item.instruction, edit_scope=item.edit_scope,
        explicit_overrides=list(item.explicit_overrides or []),
        override_confirmed=item.override_confirmed,
        execution_snapshot=dict(item.execution_snapshot or {}),
        error_message=item.error_message, created_at=item.created_at,
    )


def _metadata(job: Job) -> dict[str, object]:
    value = job.input_json.get("metadata") if isinstance(job.input_json, dict) else None
    return value if isinstance(value, dict) else {}


async def _source_context(
    db: AsyncSession, *, project: ListingImageProject, output_id: str,
) -> tuple[GeneratedOutput, Job, ListingImageTaskGroup, Asset, str]:
    row = (await db.execute(
        select(GeneratedOutput, Job, ListingImageTaskGroup, Asset)
        .join(Job, GeneratedOutput.job_id == Job.id)
        .join(ListingImageTaskGroup, GeneratedOutput.batch_id == ListingImageTaskGroup.job_batch_id)
        .join(Asset, GeneratedOutput.asset_id == Asset.id)
        .where(
            GeneratedOutput.id == output_id,
            GeneratedOutput.organization_id == project.organization_id,
            GeneratedOutput.discarded_at.is_(None),
            ListingImageTaskGroup.listing_image_project_id == project.id,
            Asset.deleted_at.is_(None),
        )
    )).first()
    if row is None:
        raise AppError("attachment_output_edit.source_not_found", "待修改图片不存在或无权访问", 404)
    output, job, group, asset = row
    metadata = _metadata(job)
    if metadata.get("workflow") not in VALID_SOURCE_WORKFLOWS:
        raise AppError("attachment_output_edit.source_invalid", "该图片不是附图生成工作台的有效结果", 422)
    module_key = str(metadata.get("item_code") or output.module_key or "")
    if not module_key:
        raise AppError("attachment_output_edit.module_missing", "图片缺少模块信息，无法创建可追溯编辑版本", 409)
    return output, job, group, asset, module_key


def _detect_explicit_overrides(instruction: str) -> list[str]:
    text = instruction.lower()
    rules = {
        "product_identity": ("更换商品", "替换商品", "换成另一件", "change product", "replace product"),
        "product_color": ("改变商品颜色", "修改衣服颜色", "换颜色", "change product color", "recolor garment"),
        "product_text_or_logo": ("修改logo", "替换logo", "修改号码", "修改文字", "replace logo", "change number", "change text"),
        "model_identity": ("更换模特", "换一个人", "改变脸", "replace model", "change face", "different person"),
    }
    return [key for key, words in rules.items() if any(word in text for word in words)]


def compile_output_edit_prompt(
    *, instruction: str, edit_scope: str, product_lock: dict[str, object],
    model_snapshot: list[dict[str, object]], overrides: list[str],
    library_context: list[dict[str, object]] | None = None,
) -> str:
    preserved = "、".join(str(item) for key in (
        "colors", "patterns", "logos", "texts", "numbers", "silhouette", "construction_details",
    ) for item in (product_lock.get(key) if isinstance(product_lock.get(key), list) else [])[:8])
    model_names = "、".join(str(item.get("name") or item.get("model_name") or "") for item in model_snapshot if isinstance(item, dict))
    override_note = "；".join(overrides) if overrides else "无"
    library_note = json.dumps(library_context or [], ensure_ascii=False, separators=(",", ":"))
    return f"""你正在编辑一张已生成的电商附图。必须以第一张参考图（当前生成结果）为编辑底图，而不是重新策划整张图片。

用户修改要求：{instruction.strip()}
修改范围：{edit_scope}

默认保护规则：除用户明确要求修改的内容外，保持商品身份、商品设计、模特身份、构图、镜头、背景、文字排版和所有未涉及区域不变。禁止凭空新增商品卖点或改变商品事实。
商品事实快照摘要：{preserved or '沿用当前商品事实锁'}
模特身份快照摘要：{model_names or '沿用当前结果中的人物身份'}
本次已确认显式覆盖：{override_note}
本次公共参考图库快照（Role硬规则优先于Guidance）：{library_note}

请直接完成图片编辑。当前结果图优先级最高；其余参考图只用于用户指明的局部方向，不得覆盖受保护的商品与模特事实。"""


async def _refresh_revision(db: AsyncSession, revision: AttachmentOutputEditRevision) -> None:
    if not revision.job_id:
        return
    job = await db.get(Job, revision.job_id)
    if job is None:
        return
    if job.status == "succeeded":
        output = await db.scalar(select(GeneratedOutput).where(
            GeneratedOutput.job_id == job.id,
            GeneratedOutput.organization_id == revision.organization_id,
        ).order_by(GeneratedOutput.sequence_number).limit(1))
        revision.result_output_id = output.id if output else None
        revision.status = "succeeded" if output else "failed"
        revision.error_message = None if output else "任务成功但未找到生成结果"
        result_meta = (job.result_json or {}).get("metadata") if isinstance(job.result_json, dict) else {}
        revision.execution_snapshot = {
            **dict(revision.execution_snapshot or {}),
            "provider_request_id": (job.result_json or {}).get("provider_request_id") if isinstance(job.result_json, dict) else None,
            "resolved_provider_size": result_meta.get("resolved_provider_size") if isinstance(result_meta, dict) else None,
            "actual_width": result_meta.get("actual_width") if isinstance(result_meta, dict) else None,
            "actual_height": result_meta.get("actual_height") if isinstance(result_meta, dict) else None,
            "generation_duration_ms": job.generation_duration_ms,
        }
    elif job.status in {"failed", "cancelled"}:
        revision.status = job.status
        revision.error_message = job.error_message
    else:
        revision.status = job.status


async def list_output_edit_revisions(
    db: AsyncSession, *, project: ListingImageProject, output_id: str,
) -> list[AttachmentOutputEditRevision]:
    source, _, _, _, _ = await _source_context(db, project=project, output_id=output_id)
    result_revision = await db.scalar(select(AttachmentOutputEditRevision).where(
        AttachmentOutputEditRevision.organization_id == project.organization_id,
        AttachmentOutputEditRevision.result_output_id == source.id,
    ).order_by(AttachmentOutputEditRevision.created_at.desc()).limit(1))
    root_id = result_revision.root_output_id if result_revision else source.id
    rows = list((await db.scalars(select(AttachmentOutputEditRevision).where(
        AttachmentOutputEditRevision.organization_id == project.organization_id,
        AttachmentOutputEditRevision.listing_image_project_id == project.id,
        AttachmentOutputEditRevision.root_output_id == root_id,
    ).order_by(AttachmentOutputEditRevision.revision_number, AttachmentOutputEditRevision.created_at))).all())
    for row in rows:
        await _refresh_revision(db, row)
    return rows


async def create_output_edits(
    db: AsyncSession, settings: Settings, *, project: ListingImageProject, version: ListingVersion,
    requests: list[AttachmentOutputEditItemRequest], idempotency_key: str,
    concurrency: int, user_id: str,
) -> tuple[JobBatch, ListingImageTaskGroup, list[AttachmentOutputEditRevision], bool]:
    existing_batch = await db.scalar(select(JobBatch).where(
        JobBatch.organization_id == project.organization_id,
        JobBatch.idempotency_key == idempotency_key,
    ))
    if existing_batch is not None:
        existing_group = await db.scalar(select(ListingImageTaskGroup).where(
            ListingImageTaskGroup.organization_id == project.organization_id,
            ListingImageTaskGroup.job_batch_id == existing_batch.id,
            ListingImageTaskGroup.listing_image_project_id == project.id,
        ))
        existing_revisions = list((await db.scalars(select(AttachmentOutputEditRevision).where(
            AttachmentOutputEditRevision.organization_id == project.organization_id,
            AttachmentOutputEditRevision.batch_id == existing_batch.id,
        ).order_by(AttachmentOutputEditRevision.created_at))).all())
        if existing_group is None or not existing_revisions:
            raise AppError("attachment_output_edit.idempotency_conflict", "该幂等键已被其他请求使用", 409)
        return existing_batch, existing_group, existing_revisions, False
    model_code = await resolve_bound_model_code(
        db, organization_id=project.organization_id,
        operation_code="listing.generate", capability="image_edit",
    )
    prepared: list[tuple[AttachmentOutputEditRevision, BatchJobItemRequest, str, str]] = []
    all_reference_ids: list[str] = []
    source_group_ids: set[str] = set()
    generic_project_id: str | None = None
    for request in requests:
        source, source_job, source_group, source_asset, module_key = await _source_context(
            db, project=project, output_id=request.source_output_id,
        )
        source_group_ids.add(source_group.id)
        generic_project_id = generic_project_id or source_job.project_id
        source_metadata = _metadata(source_job)
        parent_revision = await db.scalar(select(AttachmentOutputEditRevision).where(
            AttachmentOutputEditRevision.organization_id == project.organization_id,
            AttachmentOutputEditRevision.result_output_id == source.id,
        ).order_by(AttachmentOutputEditRevision.created_at.desc()).limit(1))
        root_id = parent_revision.root_output_id if parent_revision else source.id
        next_number = int(await db.scalar(select(func.max(AttachmentOutputEditRevision.revision_number)).where(
            AttachmentOutputEditRevision.organization_id == project.organization_id,
            AttachmentOutputEditRevision.root_output_id == root_id,
        )) or 0) + 1
        overrides = _detect_explicit_overrides(request.instruction)
        if overrides and not request.override_confirmed:
            raise AppError(
                "attachment_output_edit.override_confirmation_required",
                "这条修改会覆盖已锁定的商品或模特信息，请确认后再提交。",
                409, {"source_output_id": source.id, "explicit_overrides": overrides},
            )
        lock_id = str(source_metadata.get("product_identity_lock_version_id") or "") or None
        lock = await db.get(AttachmentProductIdentityLockVersion, lock_id) if lock_id else None
        product_lock = dict(lock.structured_json or {}) if lock else {}
        model_snapshot = list(source_metadata.get("model_identity_snapshot") or [])
        library_ids = list(dict.fromkeys(request.library_item_ids))
        library_rows = list((await db.scalars(select(AttachmentReferenceLibraryItem).where(
            AttachmentReferenceLibraryItem.organization_id == project.organization_id,
            AttachmentReferenceLibraryItem.id.in_(library_ids),
            AttachmentReferenceLibraryItem.is_active.is_(True),
        ))).all()) if library_ids else []
        if len(library_rows) != len(library_ids):
            raise AppError("attachment_output_edit.library_reference_invalid", "部分公共参考图不存在、已停用或无权访问", 422)
        library_by_id = {item.id: item for item in library_rows}
        library_snapshots: list[dict[str, object]] = []
        for library_id in library_ids:
            library_item = library_by_id[library_id]
            understanding = await latest_library_understanding(db, library_item.id)
            library_snapshots.append({
                "library_item_id": library_item.id,
                "asset_id": library_item.asset_id,
                "reference_role": library_item.reference_role,
                "guidance": library_item.guidance,
                "tags": list(library_item.tags or []),
                "state_version": library_item.state_version,
                "understanding": {
                    "id": understanding.id,
                    "version_number": understanding.version_number,
                    "status": understanding.status,
                    "structured": dict(understanding.structured_json or {}),
                    "analysis_prompt_version": understanding.analysis_prompt_version,
                } if understanding else None,
            })
        optional_ids = list(dict.fromkeys([*request.reference_asset_ids, *(item.asset_id for item in library_rows)]))
        source_reference_ids = [str(item) for item in source_job.input_json.get("reference_asset_ids", []) if item]
        reference_ids = list(dict.fromkeys([source.asset_id, *optional_ids, *source_reference_ids]))[:MAX_EDIT_REFERENCES]
        assets_found = set((await db.scalars(select(Asset.id).where(
            Asset.organization_id == project.organization_id,
            Asset.id.in_(reference_ids), Asset.deleted_at.is_(None),
        ))).all())
        if set(reference_ids) != assets_found:
            raise AppError("attachment_output_edit.reference_invalid", "部分编辑参考图不存在或无权访问", 422)
        prompt = compile_output_edit_prompt(
            instruction=request.instruction, edit_scope=request.edit_scope,
            product_lock=product_lock, model_snapshot=model_snapshot, overrides=overrides,
            library_context=library_snapshots,
        )
        revision = AttachmentOutputEditRevision(
            organization_id=project.organization_id, listing_image_project_id=project.id,
            module_key=module_key, root_output_id=root_id, parent_output_id=source.id,
            revision_number=next_number, status="queued", instruction=request.instruction.strip(),
            edit_scope=request.edit_scope, compiled_prompt=prompt, explicit_overrides=overrides,
            override_confirmed=request.override_confirmed, product_identity_lock_version_id=lock_id,
            model_identity_snapshot=model_snapshot,
            reference_snapshot={
                "source_output_id": source.id, "source_asset_id": source.asset_id,
                "reference_asset_ids": reference_ids, "library_item_ids": library_ids,
                "library_items": library_snapshots,
            },
            execution_snapshot={
                "source_output_id": source.id, "source_asset_id": source.asset_id,
                "compiled_prompt": prompt, "model_code": model_code,
                "requested_aspect_ratio": source_job.input_json.get("aspect_ratio"),
                "requested_width": source_job.input_json.get("requested_width") or source_asset.width,
                "requested_height": source_job.input_json.get("requested_height") or source_asset.height,
                "product_identity_lock_version_id": lock_id,
                "model_identity_snapshot": model_snapshot,
                "reference_asset_ids": reference_ids, "library_item_ids": library_ids,
                "library_items": library_snapshots,
            },
            created_by=user_id, created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        )
        db.add(revision); await db.flush()
        item = BatchJobItemRequest(
            client_item_id=f"attachment-edit:{revision.id}", prompt=prompt,
            reference_asset_ids=reference_ids,
            size=str(source_job.input_json.get("size") or "1024x1024"),
            aspect_ratio=str(source_job.input_json.get("aspect_ratio") or "auto"),
            requested_width=int(source_job.input_json.get("requested_width") or source_asset.width or 1024),
            requested_height=int(source_job.input_json.get("requested_height") or source_asset.height or 1024),
            quality=str(source_job.input_json.get("quality") or "high"), output_format="png",
            metadata={
                "workflow": "attachment_output_edit", "output_project_id": project.id,
                "item_code": module_key, "module_name": source_metadata.get("module_name") or module_key,
                "slot_index": source_metadata.get("slot_index"),
                "generation_mode": "conversation_edit", "attachment_output_edit_revision_id": revision.id,
                "root_output_id": root_id, "parent_output_id": source.id,
                "product_identity_lock_version_id": lock_id,
                "model_identity_snapshot": model_snapshot, "reference_snapshot": revision.reference_snapshot,
                "effective_prompt_snapshot": prompt,
                "prompt_snapshot": request.instruction.strip(),
                "product_mode": source_metadata.get("product_mode"),
                "product_count": source_metadata.get("product_count"),
            },
        )
        prepared.append((revision, item, source.asset_id, module_key))
        all_reference_ids.extend(reference_ids)

    batch, jobs, created = await submit_batch(
        db, settings, organization_id=project.organization_id, user_id=user_id,
        payload=JobBatchSubmitRequest(
            name=f"附图对话修改 · {len(prepared)}张", workspace_type="listing",
            operation_code="listing.generate", capability="image_edit", model_code=model_code,
            idempotency_key=idempotency_key, project_id=generic_project_id,
            concurrency=min(concurrency, len(prepared)), items=[item for _, item, _, _ in prepared],
        ),
    )
    jobs_by_client = {job.client_item_id: job for job in jobs}
    for revision, item, _, _ in prepared:
        job = jobs_by_client[item.client_item_id]
        revision.job_id = job.id; revision.batch_id = batch.id
    snapshot = await build_input_asset_snapshot(
        db, organization_id=project.organization_id, product_asset_ids=[],
        reference_asset_ids=list(dict.fromkeys(all_reference_ids)), template_asset_ids=[],
    )
    snapshot.update({"workflow": "attachment_output_edit", "source_output_ids": [item.parent_output_id for item, _, _, _ in prepared]})
    group = await create_group_for_batch(
        db, project=project, batch=batch, version=version,
        selected_image_types=list(dict.fromkeys(module_key for _, _, _, module_key in prepared)),
        product_asset_ids=[], reference_asset_ids=list(dict.fromkeys(all_reference_ids)),
        template_asset_ids=[], input_asset_snapshot=snapshot, user_id=user_id,
        source_task_group_id=next(iter(source_group_ids)) if len(source_group_ids) == 1 else None,
    )
    group.group_name = f"附图对话修改任务组 #{group.group_number}"
    for job in jobs:
        metadata = _metadata(job)
        job.input_json = {**job.input_json, "metadata": {**metadata, "listing_image_task_group_id": group.id}}
    project.last_batch_id = batch.id
    project.status = "generating"
    project.task_count = int(project.task_count or 0) + (len(jobs) if created else 0)
    project.updated_by = user_id
    await db.flush()
    return batch, group, [item for item, _, _, _ in prepared], created
