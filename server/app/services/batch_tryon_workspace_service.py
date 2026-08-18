from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.content import Project
from app.models.tasks import JobBatch


MAX_WORKSPACE_CONFIG_BYTES = 1_000_000
WORKSPACE_KIND = "workspace"
VALID_STATUSES = {"draft", "validating", "ready", "queued", "running", "review", "completed", "failed"}


def _validate_config(config: dict[str, object]) -> dict[str, object]:
    try:
        encoded = json.dumps(config, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise AppError("batch_tryon.workspace_config_invalid", "批次工作台配置包含无法保存的数据。", 422) from error
    if len(encoded) > MAX_WORKSPACE_CONFIG_BYTES:
        raise AppError("batch_tryon.workspace_config_too_large", "批次工作台配置不能超过 1MB。", 422)
    return config


async def _project(
    session: AsyncSession, organization_id: str, project_id: str, user_id: str,
) -> Project:
    project = await session.scalar(select(Project).where(
        Project.id == project_id,
        Project.organization_id == organization_id,
        Project.project_type == "batch_tryon",
        Project.deleted_at.is_(None),
        Project.created_by == user_id,
    ))
    if project is None:
        raise AppError("project.not_found", "批量套图项目不存在。", 404)
    return project


async def create_workspace(
    session: AsyncSession, *, organization_id: str, user_id: str, project_id: str,
    name: str | None, config: dict[str, object],
) -> JobBatch:
    await _project(session, organization_id, project_id, user_id)
    count = int(await session.scalar(select(func.count(JobBatch.id)).where(
        JobBatch.organization_id == organization_id,
        JobBatch.project_id == project_id,
        JobBatch.batch_kind == WORKSPACE_KIND,
        JobBatch.created_by == user_id,
    )) or 0)
    batch = JobBatch(
        organization_id=organization_id,
        project_id=project_id,
        workspace_type="batch_tryon",
        operation_code="batch_tryon.generate",
        name=(name or f"批次 {datetime.now().strftime('%m%d')}-{count + 1:02d}").strip(),
        status="draft",
        batch_kind=WORKSPACE_KIND,
        workspace_hidden=False,
        workspace_config_json=_validate_config(config),
        concurrency=max(1, min(12, int(config.get("concurrency") or 12))),
        total_jobs=0,
        created_by=user_id,
        updated_by=user_id,
    )
    session.add(batch)
    await session.flush()
    return batch


async def get_workspace(
    session: AsyncSession, *, organization_id: str, user_id: str, workspace_id: str,
    lock: bool = False,
) -> JobBatch:
    statement = select(JobBatch).where(
        JobBatch.id == workspace_id,
        JobBatch.organization_id == organization_id,
        JobBatch.batch_kind == WORKSPACE_KIND,
        JobBatch.created_by == user_id,
    )
    if lock:
        statement = statement.with_for_update()
    batch = await session.scalar(statement)
    if batch is None:
        raise AppError("batch_tryon.workspace_not_found", "批次工作台不存在。", 404)
    return batch


async def list_workspaces(
    session: AsyncSession, *, organization_id: str, user_id: str, project_id: str,
    include_hidden: bool,
) -> list[JobBatch]:
    await _project(session, organization_id, project_id, user_id)
    filters = [
        JobBatch.organization_id == organization_id,
        JobBatch.project_id == project_id,
        JobBatch.batch_kind == WORKSPACE_KIND,
        JobBatch.created_by == user_id,
    ]
    if not include_hidden:
        filters.append(JobBatch.workspace_hidden.is_(False))
    # Keep the sort narrow because workspace_config can be very large.
    workspace_ids = list((await session.scalars(
        select(JobBatch.id)
        .where(*filters)
        .order_by(JobBatch.updated_at.desc(), JobBatch.id)
    )).all())
    workspaces_by_id = {
        item.id: item
        for item in (await session.scalars(select(JobBatch).where(JobBatch.id.in_(workspace_ids)))).all()
    } if workspace_ids else {}
    return [workspaces_by_id[workspace_id] for workspace_id in workspace_ids if workspace_id in workspaces_by_id]


async def update_workspace(
    session: AsyncSession, *, organization_id: str, user_id: str, workspace_id: str,
    name: str | None, status: str | None, config: dict[str, object] | None,
) -> JobBatch:
    batch = await get_workspace(
        session, organization_id=organization_id, user_id=user_id,
        workspace_id=workspace_id, lock=True,
    )
    if name is not None:
        batch.name = name.strip()
    if status is not None:
        if status not in VALID_STATUSES:
            raise AppError("batch_tryon.workspace_status_invalid", "批次工作台状态无效。", 422)
        batch.status = status
    if config is not None:
        batch.workspace_config_json = _validate_config(config)
        batch.concurrency = max(1, min(12, int(config.get("concurrency") or batch.concurrency or 12)))
    batch.updated_by = user_id
    await session.flush()
    return batch


async def child_batches(session: AsyncSession, workspace: JobBatch) -> list[JobBatch]:
    return list((await session.scalars(select(JobBatch).where(
        JobBatch.organization_id == workspace.organization_id,
        JobBatch.parent_batch_id == workspace.id,
        JobBatch.created_by == workspace.created_by,
    ).order_by(JobBatch.created_at))).all())
