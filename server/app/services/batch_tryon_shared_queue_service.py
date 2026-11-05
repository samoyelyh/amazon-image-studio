"""Read-only organization queue projection. Never call scheduling/state mutation APIs.

Workspace totals use current production versions, or validation if there is no
production batch. Analysis and auxiliary work are separate, not duplicate images.
Only explicitly constructed summary DTOs can leave this service.
"""
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from math import ceil
from statistics import median
from types import SimpleNamespace

from sqlalchemy import func, or_, select

from app.models.identity import User
from app.models.tasks import (
    ApiKey, BatchTryOnReviewItem, BatchTryOnVersion, Job, JobAttempt, JobBatch,
    OperationResourcePool, Provider, ProviderModel, ResourcePool, ResourcePoolKey,
)
from app.schemas.batch_tryon_queue import (
    QueueNavigation, QueueWaitEstimate, SharedQueueBoard, SharedQueueCapacity, SharedQueueEntry,
)

UTC = timezone.utc
ACTIVE = {"running", "dispatching"}
WAITING = {"queued", "waiting_for_resource", "retry_waiting"}
TERMINAL = {"succeeded", "failed", "cancelled"}


def aware(value):
    return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value


async def _capacity_and_history(session, redis, settings, organization_id, now):
    rows = (await session.execute(select(
        ApiKey.id, ApiKey.max_concurrency, ApiKey.consecutive_failures, ApiKey.cooldown_until, ApiKey.remaining_balance,
        OperationResourcePool.operation_code,
        ApiKey.rpm_limit, ApiKey.daily_limit,
    ).select_from(OperationResourcePool)
        .join(ResourcePool, ResourcePool.id == OperationResourcePool.resource_pool_id)
        .join(ProviderModel, ProviderModel.id == ResourcePool.model_id)
        .join(Provider, Provider.id == ProviderModel.provider_id)
        .join(ResourcePoolKey, ResourcePoolKey.resource_pool_id == ResourcePool.id)
        .join(ApiKey, ApiKey.id == ResourcePoolKey.api_key_id)
        .where(OperationResourcePool.operation_code.in_([
            "batch_tryon.generate", "batch_tryon.prompt_analyze_detailed", "batch_tryon.prompt_analyze", "batch_tryon.style_analyze",
        ]), OperationResourcePool.enabled.is_(True), ResourcePool.enabled.is_(True), ProviderModel.enabled.is_(True),
            Provider.enabled.is_(True), ResourcePoolKey.enabled.is_(True), ApiKey.enabled.is_(True), ApiKey.status != "disabled",
            or_(OperationResourcePool.organization_id.is_(None), OperationResourcePool.organization_id == organization_id),
            or_(ResourcePool.organization_id.is_(None), ResourcePool.organization_id == organization_id),
            or_(ApiKey.organization_id.is_(None), ApiKey.organization_id == organization_id),
        ))).all()
    keys = {r.id: r for r in rows}  # Shared image/Luna pools do not multiply capacity.
    operation_keys = defaultdict(set)
    for row in rows:
        operation_keys[row.operation_code].add(row.id)
    attempts = (await session.execute(select(
        JobAttempt.api_key_id, Job.operation_code, JobAttempt.provider_requested_at, JobAttempt.finished_at,
    ).join(Job, Job.id == JobAttempt.job_id).where(
        JobAttempt.api_key_id.in_(list(keys)), JobAttempt.status == "running", Job.status == "running",
        JobAttempt.finished_at.is_(None), JobAttempt.provider_requested_at.is_not(None),
    ))).all() if keys else []
    source, used, available = "redis_lease", 0, 0
    for key in keys.values():
        healthy = (key.cooldown_until is None or aware(key.cooldown_until) <= now) and (
            key.remaining_balance is None or key.remaining_balance > 0)
        effective = (1 if key.consecutive_failures else key.max_concurrency) if healthy else 0
        try:
            active = await redis.get(f"resource:key:{key.id}:inflight")
            cooling = await redis.get(f"resource:key:{key.id}:cooldown")
            rpm = int(await redis.get(f"resource:key:{key.id}:rpm") or 0) if key.rpm_limit else 0
            daily = int(await redis.get(f"resource:key:{key.id}:daily:{now:%Y%m%d}") or 0) if key.daily_limit else 0
            used += max(0, int(active or 0))
            if cooling or (key.rpm_limit and rpm >= key.rpm_limit) or (key.daily_limit and daily >= key.daily_limit):
                effective = 0
        except Exception:
            source = "database_attempts"
            used += sum(a.api_key_id == key.id for a in attempts)
        available += effective
    cap = min(available, settings.job_system_max_concurrency, settings.job_organization_max_concurrency,
              settings.celery_worker_concurrency)
    history = (await session.execute(select(
        Job.operation_code, JobAttempt.provider_requested_at, JobAttempt.finished_at,
    ).join(Job, Job.id == JobAttempt.job_id).where(
        JobAttempt.api_key_id.in_(list(keys)), JobAttempt.status == "succeeded",
        JobAttempt.finished_at >= now - timedelta(days=7), JobAttempt.provider_requested_at.is_not(None),
    ).order_by(JobAttempt.finished_at.desc()).limit(400))).all() if keys else []
    samples = defaultdict(list)
    for row in history:
        seconds = (aware(row.finished_at) - aware(row.provider_requested_at)).total_seconds()
        if 0 < seconds <= settings.job_timeout_seconds * 2:
            samples[row.operation_code].append(seconds)
    reason = "共享图片与Luna资源；失败恢复探针按1槽计算" if cap else "等待可用资源或冷却恢复"
    if source == "redis_lease" and any(ids != operation_keys.get("batch_tryon.generate", set()) for ids in operation_keys.values()):
        source, reason = "mixed_pools", "图片与分析通道不完全相同；总体槽位仅供参考，等待时间暂不估算"
    if source == "redis_lease":
        try:
            heartbeat_keys = [key async for key in redis.scan_iter(match="worker:heartbeat:*", count=100)] if hasattr(redis, "scan_iter") else []
            heartbeats = [await redis.get(key) for key in heartbeat_keys]
            if not any(value and now - aware(datetime.fromisoformat(value.decode() if isinstance(value, bytes) else value)) < timedelta(seconds=180) for value in heartbeats):
                source, reason = "worker_unconfirmed", "尚未确认Worker实时心跳；容量为配置上限，等待时间暂不估算"
        except Exception:
            source, reason = "worker_unconfirmed", "Worker心跳暂不可用，等待时间暂不估算"
    # Other workspaces share the existing global/user scheduler too. Never infer
    # an immediate start from a free key when another workload fills that limit.
    if source == "redis_lease":
        system_active = int(await session.scalar(select(func.count(Job.id)).where(Job.status.in_(ACTIVE))) or 0)
        org_active = int(await session.scalar(select(func.count(Job.id)).where(
            Job.status.in_(ACTIVE), Job.organization_id == organization_id)) or 0)
        if (system_active >= settings.job_system_max_concurrency or org_active >= settings.job_organization_max_concurrency) and system_active > len(attempts):
            source, reason = "scheduler_busy", "系统或组织并发被其他工作占用，暂无可靠等待估计"
    capacity = SharedQueueCapacity(configured=sum(k.max_concurrency for k in keys.values()), effective=cap,
        in_use=used, source=source, reason=reason)
    return capacity, samples, attempts


def estimate_wait(*, capacity, samples, active_attempts, ahead, now, reason=None):
    if reason:
        return QueueWaitEstimate(reason=reason)
    if not capacity.effective:
        return QueueWaitEstimate(reason="等待资源或冷却恢复，暂无可靠估计")
    if capacity.source != "redis_lease":
        return QueueWaitEstimate(reason=capacity.reason)
    operations = [j.operation_code for j in ahead] + [a.operation_code for a in active_attempts]
    if not operations:
        return QueueWaitEstimate(minimum_seconds=0, maximum_seconds=15, reason="当前无已知前序任务，仍受实际调度影响")
    if any(len(samples.get(op, [])) < 5 for op in operations):
        return QueueWaitEstimate(reason="近期成功请求样本不足，暂无可靠估计")
    if any((now - aware(a.provider_requested_at)).total_seconds() > median(samples[a.operation_code]) * 1.75 for a in active_attempts):
        return QueueWaitEstimate(reason="有请求明显超出历史耗时区间，等待返回，暂无可靠估计")
    # The interval deliberately widens historical medians; this is not a countdown.
    estimates = []
    for multiplier in (0.5, 1.75):
        slots = [0.0] * capacity.effective
        for index, active in enumerate(active_attempts):
            remaining = max(0.0, median(samples[active.operation_code]) * multiplier -
                (now - aware(active.provider_requested_at)).total_seconds())
            slots[index % len(slots)] += remaining
        # Lease occupancy can include input preparation, not present in provider attempts.
        if capacity.in_use > len(active_attempts):
            return QueueWaitEstimate(reason="部分资源仍在准备或状态同步中，暂无可靠估计")
        for job in ahead:
            index = min(range(len(slots)), key=slots.__getitem__)
            slots[index] += median(samples[job.operation_code]) * multiplier
        estimates.append(min(slots))
    low, high = int(max(0, estimates[0]) // 15 * 15), ceil(max(0, estimates[1]) / 15) * 15
    return QueueWaitEstimate(minimum_seconds=low, maximum_seconds=max(low + 15, high),
        sample_count=min(len(samples[op]) for op in operations), reason="历史耗时区间估计；含共享资源竞争，不保证上游开始时间")


async def shared_queue_snapshot(session, redis, settings, *, organization_id, user_id, limit=100, include_archived=False):
    now = datetime.now(UTC)
    # Keep the ordered projection narrow: even JSON_EXTRACT of a tiny flag can
    # make MySQL carry a large workspace_config through filesort (error 1038).
    # Read only that flag in a separate, unordered, organization-scoped query.
    batches = (await session.execute(select(
        JobBatch.id, JobBatch.parent_batch_id, JobBatch.batch_kind, JobBatch.name, JobBatch.status,
        JobBatch.created_at, JobBatch.created_by, JobBatch.project_id, JobBatch.workspace_hidden, JobBatch.concurrency,
        User.display_name.label("creator_name"),
    ).outerjoin(User, User.id == JobBatch.created_by).where(
        JobBatch.organization_id == organization_id, JobBatch.workspace_type == "batch_tryon",
    ).order_by(JobBatch.created_at.desc()).limit(1000))).all()
    archived_at = dict((await session.execute(select(
        JobBatch.id, JobBatch.workspace_config_json["queue_retention"]["archived_at"].as_string(),
    ).where(JobBatch.organization_id == organization_id, JobBatch.workspace_type == "batch_tryon",
        JobBatch.id.in_([batch.id for batch in batches])))).all()) if batches else {}
    batches = [SimpleNamespace(**batch._mapping, archived_at=archived_at.get(batch.id)) for batch in batches]
    by_id = {b.id: b for b in batches}
    roots, children = {}, defaultdict(list)
    for batch in batches:
        parent = by_id.get(batch.parent_batch_id)
        root = parent if parent and parent.batch_kind == "workspace" and parent.created_by == batch.created_by else batch
        roots[root.id] = root
        if batch.batch_kind != "workspace":
            children[root.id].append(batch)
    versions = (await session.execute(select(
        BatchTryOnReviewItem.batch_id, BatchTryOnVersion.task_id,
    ).outerjoin(BatchTryOnVersion, BatchTryOnVersion.id == BatchTryOnReviewItem.current_version_id).where(
        BatchTryOnReviewItem.organization_id == organization_id, BatchTryOnReviewItem.batch_id.in_(list(by_id)),
    ))).all() if by_id else []
    current_tasks, item_counts = defaultdict(set), Counter()
    for batch_id, task_id in versions:
        item_counts[batch_id] += 1
        if task_id:
            current_tasks[batch_id].add(task_id)
    job_columns = [Job.id, Job.batch_id, Job.operation_code, Job.status, Job.created_at, Job.started_at,
                   Job.next_retry_at, Job.next_dispatch_at, Job.attempts, Job.created_by,
                   Job.input_json["metadata"]["awaiting_luna"].as_boolean().label("awaiting_luna")]
    jobs = (await session.execute(select(*job_columns).where(
        Job.organization_id == organization_id, Job.batch_id.in_(list(by_id)),
    ))).all() if by_id else []
    by_batch = defaultdict(list)
    all_waiting = []
    for job in jobs:
        if job.operation_code == "batch_tryon.generate" and (not item_counts[job.batch_id] or job.id in current_tasks[job.batch_id]):
            by_batch[job.batch_id].append(job)
    # Active analyses share the same resources, but are not counted as additional generated images.
    analyses = (await session.execute(select(*job_columns,
        Job.input_json["metadata"]["workflow_request"]["workspace_batch_id"].as_string().label("workspace_id"),
        Job.input_json["metadata"]["workflow_root_job_id"].as_string().label("workflow_root_id"),
        Job.input_json["metadata"]["review_item_id"].as_string().label("review_item_id"),
    ).where(Job.organization_id == organization_id, Job.workspace_type == "batch_tryon",
            Job.capability == "text_generation", Job.status.in_(ACTIVE | WAITING)))).all()
    root_ids = {a.workflow_root_id for a in analyses if a.workflow_root_id and not a.workspace_id}
    analysis_roots = dict((await session.execute(select(Job.id,
        Job.input_json["metadata"]["workflow_request"]["workspace_batch_id"].as_string(),
    ).where(Job.id.in_(root_ids), Job.organization_id == organization_id))).all()) if root_ids else {}
    analyses_by_workspace = defaultdict(list)
    review_ids = {a.review_item_id for a in analyses if a.review_item_id}
    review_batches = dict((await session.execute(select(BatchTryOnReviewItem.id, BatchTryOnReviewItem.batch_id).where(
        BatchTryOnReviewItem.id.in_(review_ids), BatchTryOnReviewItem.organization_id == organization_id,
    ))).all()) if review_ids else {}
    for analysis in analyses:
        workspace_id = analysis.workspace_id or analysis_roots.get(analysis.workflow_root_id)
        if not workspace_id:
            review_batch = by_id.get(review_batches.get(analysis.review_item_id))
            if review_batch:
                workspace_id = review_batch.parent_batch_id or review_batch.id
        if workspace_id in roots and roots[workspace_id].created_by == analysis.created_by:
            analyses_by_workspace[workspace_id].append(analysis)
    counted_by_root = {}
    for root_id, root in roots.items():
        if root.archived_at and not include_archived:
            continue
        groups = children[root_id]
        counted = [b for b in groups if b.batch_kind == "production"] or groups
        counted_by_root[root_id] = counted
        # Auxiliary samples still compete for resources, without adding to production image totals.
        for child in groups:
            if child.status == "paused":
                continue
            for job in by_batch[child.id]:
                if job.status in WAITING and not job.awaiting_luna and (
                    not job.next_retry_at or aware(job.next_retry_at) <= now) and (
                    not job.next_dispatch_at or aware(job.next_dispatch_at) <= now):
                    all_waiting.append(job)
    all_waiting.extend(a for a in analyses if a.status in WAITING and
        (not a.next_retry_at or aware(a.next_retry_at) <= now) and
        (not a.next_dispatch_at or aware(a.next_dispatch_at) <= now))
    priority = {"queued": 0, "waiting_for_resource": 1, "retry_waiting": 2}
    all_waiting.sort(key=lambda j: (priority.get(j.status, 3), j.attempts, aware(j.created_at), j.id))
    ranks = {job.id: index for index, job in enumerate(all_waiting)}
    capacity, samples, active_attempts = await _capacity_and_history(session, redis, settings, organization_id, now)
    entries = []
    for root_id, root in roots.items():
        if root_id not in counted_by_root:
            continue
        counted = counted_by_root[root_id]
        counted_jobs = [j for b in counted for j in by_batch[b.id]]
        statuses = Counter(j.status for j in counted_jobs)
        total = sum(item_counts[b.id] or len(by_batch[b.id]) for b in counted)
        missing = total - len(counted_jobs)
        running = sum(statuses[s] for s in ACTIVE)
        waiting = sum(statuses[s] for s in WAITING)
        planning = analyses_by_workspace[root_id]
        analyzing = sum(a.status in ACTIVE for a in planning)
        auxiliary = sum(j.status in ACTIVE and j.id not in {c.id for c in counted_jobs}
                        for j in jobs if j.batch_id in {b.id for b in children[root_id]})
        processed = sum(statuses[s] for s in TERMINAL)
        paused = bool(waiting and counted and all(b.status == "paused" for b in counted if by_batch[b.id]))
        status = ("running" if running or auxiliary else "analyzing" if planning else "paused" if paused else
                  "queued" if waiting else "failed" if missing or statuses["failed"] else
                  "cancelled" if total and statuses["cancelled"] == total else "completed" if total else "draft")
        if root.workspace_hidden and not root.archived_at and not (running or waiting or planning or auxiliary):
            continue
        indices = [ranks[j.id] for j in counted_jobs if j.id in ranks]
        first_index = min(indices) if indices else None
        reason = ("当前批次已暂停" if paused else "等待AI分析完成" if first_index is None and any(j.awaiting_luna for j in counted_jobs) else
                  "等待技术重试窗口" if waiting and first_index is None else "当前没有排队任务" if not waiting else None)
        if not reason and (any(b.concurrency < capacity.effective for b in counted) or settings.job_user_max_concurrency < capacity.effective):
            reason = "仍受批次或用户并发上限影响，暂无可靠估计"
        estimate = estimate_wait(capacity=capacity, samples=samples, active_attempts=active_attempts,
            ahead=all_waiting[:first_index] if first_index is not None else [], now=now, reason=reason)
        own = root.created_by == user_id
        entries.append(SharedQueueEntry(id=root_id, name=root.name or "未命名批次", creator_name=root.creator_name or "已停用用户",
            created_at=aware(root.created_at), status="archived" if root.archived_at else status, archived=bool(root.archived_at),
            archived_at=root.archived_at, total_count=total, completed_count=statuses["succeeded"],
            processed_count=processed, running_count=running, waiting_count=waiting,
            failed_count=statuses["failed"] + max(0, missing), cancelled_count=statuses["cancelled"],
            retrying_count=statuses["retry_waiting"], analysis_running=analyzing, auxiliary_running=auxiliary,
            ahead_count=first_index, progress_percent=round(processed / total * 100) if total else 0,
            can_open=own, navigation=QueueNavigation(project_id=root.project_id,
                workspace_id=root.id if root.batch_kind == "workspace" else None,
                batch_id=root.id if root.batch_kind != "workspace" else None) if own else None, estimate=estimate))
    entries.sort(key=lambda e: (e.status not in {"running", "analyzing", "queued", "paused"}, -e.created_at.timestamp(), e.id))
    return SharedQueueBoard(snapshot_at=now, entries=entries[:limit],
        running_count=sum(e.running_count + e.auxiliary_running for e in entries if not e.archived),
        waiting_count=sum(e.waiting_count for e in entries if not e.archived), failed_count=sum(e.failed_count for e in entries if not e.archived),
        analysis_running=sum(e.analysis_running for e in entries if not e.archived), capacity=capacity, truncated=len(entries) > limit or len(batches) == 1000)
