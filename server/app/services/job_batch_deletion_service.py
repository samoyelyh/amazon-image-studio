from __future__ import annotations

from dataclasses import dataclass, field

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.base import Base
from app.models.content import Asset, GeneratedOutput, ProjectAsset
from app.models.tasks import BatchTryOnReviewItem, BatchTryOnVersion, Job, JobBatch
from app.services.storage_service import StorageService


TERMINAL_JOB_STATUSES = {"succeeded", "failed", "cancelled"}


@dataclass
class HardDeleteResult:
    deleted_batches: int = 0
    deleted_jobs: int = 0
    deleted_outputs: int = 0
    deleted_assets: int = 0
    retained_shared_assets: int = 0
    storage_delete_failures: int = 0
    storage_keys: list[str] = field(default_factory=list, repr=False)


def _metadata(job: Job) -> dict[str, object]:
    value = job.input_json.get("metadata") if isinstance(job.input_json, dict) else None
    return value if isinstance(value, dict) else {}


def _result_metadata(job: Job) -> dict[str, object]:
    result = job.result_json if isinstance(job.result_json, dict) else {}
    value = result.get("metadata")
    return value if isinstance(value, dict) else {}


def _workflow_request(job: Job) -> dict[str, object]:
    value = _metadata(job).get("workflow_request")
    return value if isinstance(value, dict) else {}


def _workflow_state(job: Job) -> dict[str, object]:
    value = _result_metadata(job).get("workflow_state")
    return value if isinstance(value, dict) else {}


async def _workflow_jobs(
    session: AsyncSession,
    *,
    organization_id: str,
    project_id: str | None,
    workspace_id: str | None,
    batch_ids: set[str],
    owner_user_id: str | None = None,
) -> list[Job]:
    if not project_id:
        return []
    filters = [
        Job.organization_id == organization_id,
        Job.project_id == project_id,
        Job.workspace_type == "batch_tryon",
        Job.batch_id.is_(None),
    ]
    if owner_user_id:
        filters.append(Job.created_by == owner_user_id)
    candidates = list((await session.scalars(select(Job).where(*filters))).all())
    root_ids = {
        job.id
        for job in candidates
        if (
            workspace_id
            and str(_workflow_request(job).get("workspace_batch_id") or "") == workspace_id
        ) or str(_workflow_state(job).get("batch_id") or "") in batch_ids
    }
    if not root_ids:
        return []
    return [
        job for job in candidates
        if job.id in root_ids or str(_metadata(job).get("workflow_root_job_id") or "") in root_ids
    ]


async def _asset_has_remaining_reference(
    session: AsyncSession,
    asset_id: str,
    *,
    ignored_project_id: str | None = None,
) -> bool:
    for table in Base.metadata.tables.values():
        for foreign_key in table.foreign_keys:
            if foreign_key.column.table.name != Asset.__tablename__:
                continue
            column = foreign_key.parent
            condition = column == asset_id
            # A generated output is linked into its project asset list for browsing. That
            # link is owned by the output and may be removed only after every other
            # reference has disappeared. Links from any other project remain protective.
            if table.name == ProjectAsset.__tablename__ and ignored_project_id:
                condition = condition & (table.c.project_id != ignored_project_id)
            found = await session.scalar(select(column).select_from(table).where(condition).limit(1))
            if found is not None:
                return True
    return False


def _clean_parent_workspace_config(
    workspace: JobBatch,
    *,
    deleted_batch_ids: set[str],
    deleted_job_ids: set[str],
    deleted_review_item_ids: set[str],
    deleted_workflow_job_ids: set[str],
) -> None:
    config = dict(workspace.workspace_config_json or {})
    batch = dict(config.get("batch") or {})
    if batch.get("serverBatchId") in deleted_batch_ids:
        batch.pop("serverBatchId", None)
    batch["serverBatchIds"] = [
        value for value in (batch.get("serverBatchIds") or []) if value not in deleted_batch_ids
    ]
    if batch.get("serverWorkflowId") in deleted_workflow_job_ids:
        batch.pop("serverWorkflowId", None)
    items = batch.get("items")
    if isinstance(items, list):
        batch["items"] = [
            item for item in items
            if not isinstance(item, dict) or (
                item.get("taskId") not in deleted_job_ids
                and item.get("outputTaskId") not in deleted_job_ids
                and item.get("serverReviewItemId") not in deleted_review_item_ids
            )
        ]
    if not batch.get("items"):
        batch["queuePaused"] = True
    config["batch"] = batch
    workspace.workspace_config_json = config


async def hard_delete_job_batch(
    session: AsyncSession,
    *,
    organization_id: str,
    batch_id: str,
    include_workspace_children: bool,
    owner_user_id: str | None = None,
) -> HardDeleteResult:
    root_filters = [
        JobBatch.id == batch_id,
        JobBatch.organization_id == organization_id,
    ]
    if owner_user_id:
        root_filters.append(JobBatch.created_by == owner_user_id)
    root = await session.scalar(select(JobBatch).where(*root_filters).with_for_update())
    if root is None:
        raise AppError("job.batch_not_found", "批次不存在或已被删除。", 404)
    if include_workspace_children and root.batch_kind != "workspace":
        raise AppError("job.workspace_batch_required", "该记录不是批次工作区。", 409)
    if not include_workspace_children and root.batch_kind == "workspace":
        raise AppError("job.task_batch_required", "请从顶部批次标签执行整个工作区的永久删除。", 409)

    batches = [root]
    if include_workspace_children:
        batches.extend(list((await session.scalars(select(JobBatch).where(
            JobBatch.organization_id == organization_id,
            JobBatch.parent_batch_id == root.id,
            JobBatch.created_by == root.created_by,
        ).with_for_update())).all()))
    batch_ids = {item.id for item in batches}
    direct_jobs = list((await session.scalars(select(Job).where(
        Job.organization_id == organization_id,
        Job.batch_id.in_(batch_ids),
        Job.created_by == root.created_by,
    ))).all())
    workflow_jobs = await _workflow_jobs(
        session,
        organization_id=organization_id,
        project_id=root.project_id,
        workspace_id=root.id if include_workspace_children else None,
        batch_ids=batch_ids,
        owner_user_id=root.created_by,
    )
    jobs_by_id = {item.id: item for item in [*direct_jobs, *workflow_jobs]}
    active_jobs = [item for item in jobs_by_id.values() if item.status not in TERMINAL_JOB_STATUSES]
    if active_jobs:
        raise AppError(
            "job.batch_delete_active",
            "批次仍有正在运行、排队或取消中的任务，请先取消并等待任务结束后再永久删除。",
            409,
            {"active_jobs": len(active_jobs)},
        )

    job_ids = set(jobs_by_id)
    review_items = list((await session.scalars(select(BatchTryOnReviewItem).where(
        BatchTryOnReviewItem.batch_id.in_(batch_ids),
    ))).all())
    review_item_ids = {item.id for item in review_items}
    versions = list((await session.scalars(select(BatchTryOnVersion).where(
        BatchTryOnVersion.item_id.in_(review_item_ids),
    ))).all()) if review_item_ids else []
    output_filter = [GeneratedOutput.batch_id.in_(batch_ids)]
    if job_ids:
        output_filter.append(GeneratedOutput.job_id.in_(job_ids))
    outputs = list((await session.scalars(select(GeneratedOutput).where(or_(*output_filter)))).all())
    output_ids = {item.id for item in outputs}
    candidate_asset_ids = {
        *[item.asset_id for item in outputs],
        *[item.generated_asset_id for item in versions if item.generated_asset_id],
    }

    if output_ids:
        await session.execute(delete(GeneratedOutput).where(GeneratedOutput.id.in_(output_ids)))
    if review_item_ids:
        await session.execute(delete(BatchTryOnReviewItem).where(BatchTryOnReviewItem.id.in_(review_item_ids)))
    if job_ids:
        await session.execute(delete(Job).where(Job.id.in_(job_ids)))

    parent_workspace = None
    if not include_workspace_children and root.parent_batch_id:
        parent_workspace = await session.get(JobBatch, root.parent_batch_id, with_for_update=True)
    child_ids = {item.id for item in batches if item.id != root.id}
    if child_ids:
        await session.execute(delete(JobBatch).where(JobBatch.id.in_(child_ids)))
    await session.delete(root)
    await session.flush()

    if parent_workspace is not None:
        _clean_parent_workspace_config(
            parent_workspace,
            deleted_batch_ids=batch_ids,
            deleted_job_ids=job_ids,
            deleted_review_item_ids=review_item_ids,
            deleted_workflow_job_ids={item.id for item in workflow_jobs},
        )

    result = HardDeleteResult(
        deleted_batches=len(batch_ids),
        deleted_jobs=len(job_ids),
        deleted_outputs=len(output_ids),
    )
    for asset_id in candidate_asset_ids:
        asset = await session.get(Asset, asset_id, with_for_update=True)
        if asset is None:
            continue
        if await _asset_has_remaining_reference(
            session,
            asset.id,
            ignored_project_id=root.project_id,
        ):
            result.retained_shared_assets += 1
            continue
        if root.project_id:
            await session.execute(delete(ProjectAsset).where(
                ProjectAsset.project_id == root.project_id,
                ProjectAsset.asset_id == asset.id,
            ))
            await session.flush()
        result.storage_keys.append(asset.storage_key)
        await session.delete(asset)
        result.deleted_assets += 1
    await session.flush()
    return result


async def delete_storage_objects(storage: StorageService, result: HardDeleteResult) -> None:
    for storage_key in result.storage_keys:
        try:
            await run_in_threadpool(storage.delete, storage_key)
        except Exception:
            result.storage_delete_failures += 1
