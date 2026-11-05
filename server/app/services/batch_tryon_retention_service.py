"""Scoped retention of existing batches. No image calls and no second task system."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import logging
from time import monotonic

from sqlalchemy import select
from starlette.concurrency import run_in_threadpool
from app.core.errors import AppError
from app.models.identity import AuditLog
from app.models.tasks import Job, JobBatch
from app.models.batch_tryon_queue_policy import BatchTryOnQueuePolicy
from app.schemas.batch_tryon_queue_policy import RetentionRule, RetentionSettings
from app.services.job_batch_deletion_service import _workflow_jobs, hard_delete_job_batch
from app.services.task_service import finalize_cancelled_job, TERMINAL_JOB_STATUSES

UTC = timezone.utc
MARKER = "queue_retention"
BUSY = {"running", "dispatching"}
logger = logging.getLogger(__name__)


def aware(value):
    return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value


def marker(batch):
    return (batch.workspace_config_json or {}).get(MARKER) or {}


def settings_response(policy, can_manage=False):
    if policy is None:
        return RetentionSettings(can_manage=can_manage)
    return RetentionSettings(enabled=policy.enabled, days=policy.days, age_basis=policy.age_basis,
        action=policy.action, revision=policy.revision, can_manage=can_manage, last_run_at=aware(policy.last_run_at),
        last_run_summary=policy.last_run_summary or {}, pending_storage_count=len(policy.pending_storage_keys or []))


async def read_policy(session, org, lock=False):
    statement = select(BatchTryOnQueuePolicy).where(BatchTryOnQueuePolicy.organization_id == org)
    return await session.scalar(statement.with_for_update().execution_options(populate_existing=True) if lock else statement)


async def _groups(session, org, rule, now):
    # Select only narrow candidate columns, never copy entire workspace drafts.
    rows = (await session.execute(select(JobBatch.id, JobBatch.parent_batch_id, JobBatch.batch_kind,
        JobBatch.created_by, JobBatch.created_at, JobBatch.updated_at).where(
        JobBatch.organization_id == org, JobBatch.workspace_type == "batch_tryon"))).all()
    by_id = {r.id: r for r in rows}
    roots = [r for r in rows if not (r.parent_batch_id in by_id and
        by_id[r.parent_batch_id].batch_kind == "workspace" and by_id[r.parent_batch_id].created_by == r.created_by)]
    cutoff = now - timedelta(days=rule.days)
    for root in roots:
        # Recent drafts and new child batches must not be collected from an old tab.
        group = [root] + [r for r in rows if r.parent_batch_id == root.id and r.created_by == root.created_by]
        initial = max(aware(r.created_at) for r in group)
        if initial >= cutoff:
            continue
        yield root, group, cutoff


async def _inspect_group(session, org, root_id, rule, now, *, lock=False):
    query = select(JobBatch).where(JobBatch.id == root_id, JobBatch.organization_id == org,
        JobBatch.workspace_type == "batch_tryon")
    if lock:
        query = query.with_for_update(skip_locked=True).execution_options(populate_existing=True)
    root = await session.scalar(query)
    if root is None:
        return None, [], [], "locked_or_deleted", None
    children_query = select(JobBatch).where(JobBatch.parent_batch_id == root.id,
        JobBatch.organization_id == org, JobBatch.created_by == root.created_by)
    expected_children = list((await session.scalars(select(JobBatch.id).where(JobBatch.parent_batch_id == root.id,
        JobBatch.organization_id == org, JobBatch.created_by == root.created_by))).all()) if root.batch_kind == "workspace" else []
    children = list((await session.scalars(children_query.with_for_update(skip_locked=True).execution_options(populate_existing=True) if lock else children_query)).all()) if root.batch_kind == "workspace" else []
    if lock and len(children) != len(expected_children):
        return root, [], [], "locked_or_deleted", None
    batches = [root, *children]
    ids = {b.id for b in batches}
    jobs_query = select(Job).where(Job.organization_id == org, Job.batch_id.in_(ids), Job.created_by == root.created_by)
    jobs = list((await session.scalars(jobs_query)).all())
    jobs += await _workflow_jobs(session, organization_id=org, project_id=root.project_id,
        workspace_id=root.id if root.batch_kind == "workspace" else None, batch_ids=ids, owner_user_id=root.created_by)
    jobs_by_id = {j.id: j for j in jobs}
    if lock and jobs_by_id:
        locked = list((await session.scalars(select(Job).where(Job.id.in_(jobs_by_id)).with_for_update(skip_locked=True)
            .execution_options(populate_existing=True))).all())
        if len(locked) != len(jobs_by_id):
            return root, batches, [], "locked_or_deleted", None
        jobs_by_id = {j.id: j for j in locked}
    jobs = list(jobs_by_id.values())
    if any(j.status in BUSY for j in jobs):
        return root, batches, jobs, "active", None
    # Even a long-lived tab is not expired if a result or worker heartbeat is recent.
    progress = [aware(t) for j in jobs for t in (j.created_at, j.started_at, j.finished_at, j.heartbeat_at) if t]
    if progress and max(progress) >= now - timedelta(days=rule.days):
        return root, batches, jobs, "recent", max(progress)
    stamp = marker(root)
    exemption = stamp.get("exempt_until")
    if exemption:
        try:
            if aware(datetime.fromisoformat(exemption)) > now:
                return root, batches, jobs, "recent", None
        except ValueError:
            pass
    dates = [aware(b.created_at) for b in batches]
    if rule.age_basis == "last_activity":
        dates += [aware(b.updated_at) for b in batches]
        dates += [aware(t) for j in jobs for t in (j.created_at, j.started_at, j.finished_at, j.heartbeat_at) if t]
    reference = max(dates)
    if reference >= now - timedelta(days=rule.days):
        return root, batches, jobs, "recent", reference
    pending = [j for j in jobs if j.status not in TERMINAL_JOB_STATUSES]
    if rule.action == "archive" and pending:
        return root, batches, jobs, "unfinished", reference
    if rule.action == "pause_archive" and any(j.batch_id is None for j in pending):
        return root, batches, jobs, "pending_analysis", reference
    if rule.action != "delete" and stamp.get("archived_at"):
        return root, batches, jobs, "already_archived", reference
    return root, batches, jobs, "eligible", reference


async def preview_retention(session, org, rule, revision=0, now=None):
    now = now or datetime.now(UTC)
    eligible, skipped, samples = [], {}, []
    async for root, _, _ in _groups(session, org, rule, now):
        row, batches, jobs, reason, reference = await _inspect_group(session, org, root.id, rule, now)
        if reason != "eligible":
            skipped[reason] = skipped.get(reason, 0) + 1
            continue
        eligible.append((row.id, reference.isoformat(), len(batches), len(jobs)))
        if len(samples) < 10:
            samples.append({"id": row.id, "name": row.name or "未命名批次", "reference_at": reference.isoformat()})
    token = sha256(json.dumps({"org": org, "rule": rule.model_dump(), "revision": revision,
        "groups": sorted(eligible)}, sort_keys=True).encode()).hexdigest()
    return {"eligible_count": len(eligible), "batch_count": sum(e[2] for e in eligible),
        "job_count": sum(e[3] for e in eligible), "skipped": skipped, "samples": samples,
        "preview_token": token, "per_run_limit": 20}


async def retry_pending_storage(session, policy, storage):
    # Record keys in the same DB commit as deletions, then remove objects. A crash
    # or MinIO outage leaves a durable retry list instead of silent orphaned files.
    current = await read_policy(session, policy.organization_id, lock=True)
    pending = list(dict.fromkeys(current.pending_storage_keys or []))
    org = policy.organization_id
    await session.commit()  # Never hold an admin settings lock during MinIO I/O.
    successes, failures, started = set(), 0, monotonic()
    for key in pending[:200]:
        try:
            await run_in_threadpool(storage.delete, key)
            successes.add(key)
        except Exception:
            failures += 1
        if failures >= 3 or monotonic() - started > 30:
            break
    current = await read_policy(session, org, lock=True)
    current.pending_storage_keys = [key for key in (current.pending_storage_keys or []) if key not in successes]
    current.last_run_summary = {**(current.last_run_summary or {}), "storage_pending": len(current.pending_storage_keys)}
    await session.commit()


async def execute_retention(session, storage, org, *, expected_revision=None, preview_token=None, now=None):
    now = now or datetime.now(UTC)
    policy = await read_policy(session, org, lock=True)
    if policy is None or not policy.enabled:
        return {"disabled": True}
    if expected_revision is not None and expected_revision != policy.revision:
        raise AppError("queue.policy_changed", "清理设置已变化，请重新预览。", 409)
    rule = RetentionRule(enabled=policy.enabled, days=policy.days, age_basis=policy.age_basis, action=policy.action)
    preview = await preview_retention(session, org, rule, policy.revision, now)
    if preview_token is not None and preview_token != preview["preview_token"]:
        raise AppError("queue.preview_changed", "队列状态已有变化，请重新预览后再执行。", 409)
    result = {"archived": 0, "paused_batches": 0, "deleted_batches": 0, "deleted_results": 0,
        "cancelled_jobs": 0, "retained_shared_assets": 0, "skipped": 0, "errors": 0}
    pending_keys = list(policy.pending_storage_keys or [])
    async for root_info, _, _ in _groups(session, org, rule, now):
        if result["archived"] + result["deleted_batches"] >= 20 or len(pending_keys) >= 5000:
            break
        try:
            changes = {}
            group_keys = []
            async with session.begin_nested():
                root, batches, jobs, reason, _ = await _inspect_group(session, org, root_info.id, rule, now, lock=True)
                if reason != "eligible":
                    result["skipped"] += 1
                    continue
                audit = {"policy_revision": policy.revision, "action": policy.action, "days": policy.days,
                    "age_basis": policy.age_basis, "owner_user_id": root.created_by}
                if policy.action == "delete":
                    cancelled = 0
                    for job in jobs:
                        if job.status not in TERMINAL_JOB_STATUSES:
                            job.cancel_requested_at = now
                            await finalize_cancelled_job(session, job)
                            cancelled += 1
                    root_id = root.id
                    deleted = await hard_delete_job_batch(session, organization_id=org, batch_id=root.id,
                        include_workspace_children=root.batch_kind == "workspace", owner_user_id=root.created_by)
                    group_keys = deleted.storage_keys
                    changes = {"deleted_batches": deleted.deleted_batches, "deleted_results": deleted.deleted_assets,
                        "cancelled_jobs": cancelled, "retained_shared_assets": deleted.retained_shared_assets}
                else:
                    if policy.action == "pause_archive":
                        for batch in batches:
                            if batch.batch_kind != "workspace" and any(j.batch_id == batch.id and j.status not in TERMINAL_JOB_STATUSES for j in jobs):
                                batch.status = "paused"
                                changes["paused_batches"] = changes.get("paused_batches", 0) + 1
                    root_id = root.id
                    root.workspace_config_json = {**(root.workspace_config_json or {}), MARKER: {
                        "archived_at": now.isoformat(), "previous_hidden": root.workspace_hidden,
                        "action": policy.action, "policy_revision": policy.revision}}
                    root.workspace_hidden = True
                    changes["archived"] = 1
                session.add(AuditLog(organization_id=org, actor_user_id=policy.updated_by,
                    action="batch_tryon.queue.retention", resource_type="job_batch", resource_id=root_id,
                    metadata_json=audit, created_at=now))
            pending_keys.extend(group_keys)
            for key, count in changes.items():
                result[key] += count
        except Exception as error:
            # Savepoint protects other groups; no raw provider/storage errors in summaries.
            result["errors"] += 1
            logger.warning("queue_retention_group_failed org_id=%s batch_id=%s error_type=%s", org, root_info.id, type(error).__name__)
            session.add(AuditLog(organization_id=org, actor_user_id=policy.updated_by,
                action="batch_tryon.queue.retention_failed", resource_type="job_batch", resource_id=root_info.id,
                metadata_json={"error_type": type(error).__name__}, created_at=now))
    policy.pending_storage_keys = list(dict.fromkeys(pending_keys))
    policy.last_run_at = now
    policy.last_run_summary = result
    await session.commit()
    await retry_pending_storage(session, policy, storage)
    return {**result, "storage_pending": len(policy.pending_storage_keys or [])}


async def restore_retained_batch(session, org, batch_id, user_id, is_admin):
    row = await session.scalar(select(JobBatch).where(JobBatch.id == batch_id, JobBatch.organization_id == org,
        JobBatch.workspace_type == "batch_tryon").with_for_update())
    if row is None or (row.created_by != user_id and not is_admin):
        raise AppError("job.batch_not_found", "批次不存在或不属于当前账号。", 404)
    info = marker(row)
    if not info.get("archived_at"):
        raise AppError("queue.not_archived", "该批次未自动归档。", 409)
    policy = await read_policy(session, org)
    now = datetime.now(UTC)
    row.workspace_hidden = bool(info.get("previous_hidden", False))
    row.workspace_config_json = {**(row.workspace_config_json or {}), MARKER: {
        "restored_at": now.isoformat(), "exempt_until": (now + timedelta(days=policy.days if policy else 3)).isoformat()}}
    session.add(AuditLog(organization_id=org, actor_user_id=user_id, action="batch_tryon.queue.restore",
        resource_type="job_batch", resource_id=row.id, metadata_json={}, created_at=now))
    await session.commit()
    return {"restored": True, "tasks_remain_paused": True}
