from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime, timedelta, timezone
import logging
import socket
from time import monotonic

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.session import get_engine
from app.infrastructure.redis import get_redis_client
from app.models.content import Asset, GeneratedOutput
from app.models.quota import QuotaReservation, QuotaReservationStatus
from app.models.tasks import ApiKeyUsageStat, Job, JobAttempt, JobStatus
from app.providers.base import ProviderError
from app.providers.registry import get_provider_adapter
from app.services.asset_service import create_asset, get_asset
from app.services.billing_service import settle_reservation
from app.services.batch_tryon_review_service import (
    prepare_batch_try_on_output_filename,
    sync_batch_try_on_version_for_job,
)
from app.services.image_delivery_service import delivery_transform, image_dimensions, reinforce_delivery_prompt, render_delivery_output
from app.services.resource_pool_service import (
    acquire_resource, cool_down_key, mark_key_success, release_resource, renew_resource_lease,
)
from app.services.storage_service import get_storage_service
from app.services.task_service import claim_job, create_attempt, finalize_cancelled_job, get_job, refresh_batch_status, schedule_retry_or_fail
from app.workers.celery_app import celery_app
from app.workers.runtime import run_worker_coroutine
from starlette.concurrency import run_in_threadpool


UTC = timezone.utc
logger = logging.getLogger(__name__)


@celery_app.task(name="jobs.execute", ignore_result=False, acks_late=True)
def execute_job(job_id: str) -> dict[str, object]:
    return run_worker_coroutine(lambda: _execute_job(job_id))


async def _execute_job(job_id: str) -> dict[str, object]:
    settings = get_settings()
    session_factory = async_sessionmaker(get_engine(), expire_on_commit=False, class_=AsyncSession)
    redis = get_redis_client()
    async with session_factory() as session:
        job = await claim_job(session, settings, job_id)
        if job is not None:
            await sync_batch_try_on_version_for_job(session, job)
        await session.commit()
        if job is None:
            return {"job_id": job_id, "status": "duplicate_or_terminal"}

        excluded: set[str] = set()
        while job.attempts < job.max_attempts:
            current_job_id = job.id
            current_organization_id = job.organization_id
            lease = None
            attempt = None
            provider_started: float | None = None
            heartbeat_task: asyncio.Task[None] | None = None
            try:
                lease = await acquire_resource(
                    session, redis, settings, organization_id=job.organization_id,
                    operation_code=job.operation_code, model_code=job.model_code,
                    capability=job.capability,
                    additional_capabilities={"vision_input"} if job.operation_code.endswith(".plan")
                    and bool(job.input_json.get("reference_asset_ids")) else set(),
                    excluded_key_ids=excluded,
                )
                job = await get_job(session, job.organization_id, job.id, lock=True)
                if job.cancel_requested_at:
                    await finalize_cancelled_job(session, job)
                    await session.commit()
                    return {"job_id": job.id, "status": job.status}
                job.started_at = datetime.now(UTC)
                attempt = await create_attempt(
                    session, job, provider_id=lease.provider_id, pool_id=lease.pool_id, key_id=lease.key_id,
                )
                attempt.model_id = lease.model_id
                attempt.worker_name = socket.gethostname()
                attempt.normalized_base_url = lease.base_url
                session.add(attempt)
                job.selected_pool_id = lease.pool_id
                job.selected_key_id = lease.key_id
                await session.commit()
                heartbeat_task = asyncio.create_task(
                    _job_heartbeat_loop(
                        session_factory,
                        redis,
                        settings,
                        job_id=current_job_id,
                        reservation_id=job.quota_reservation_id,
                        lease=lease,
                    )
                )

                logger.info(
                    "provider_request job_id=%s operation_code=%s resource_pool_id=%s provider_id=%s "
                    "model_id=%s queue_name=%s worker_name=%s attempt=%s normalized_base_url=%s",
                    job.id, job.operation_code, lease.pool_id, lease.provider_id, lease.model_id,
                    job.queue_name, attempt.worker_name, attempt.attempt_number, lease.base_url,
                )

                adapter = get_provider_adapter(lease.provider_type, settings)
                input_started = monotonic()
                provider_payload = await _provider_payload(session, storage=get_storage_service(), job=job)
                attempt.phase_timings_json = {
                    **(attempt.phase_timings_json or {}),
                    "input_download_ms": max(0, int((monotonic() - input_started) * 1000)),
                }
                provider_started = monotonic()
                attempt.provider_requested_at = datetime.now(UTC)
                result = await adapter.execute(
                    base_url=lease.base_url, api_key=lease.api_key, upstream_model=lease.upstream_model,
                    capability=job.capability, payload=provider_payload,
                    config={**lease.provider_config, **lease.model_config},
                )
                attempt.provider_responded_at = datetime.now(UTC)
                attempt.phase_timings_json = {
                    **(attempt.phase_timings_json or {}),
                    "provider_ms": max(0, int((monotonic() - provider_started) * 1000)),
                }
                postprocess_started = monotonic()
                stored = []
                provider_dimensions: list[tuple[int, int]] = []
                created_records: list[tuple[Asset, GeneratedOutput]] = []
                storage = get_storage_service()
                for index, output in enumerate(result.outputs):
                    provider_dimensions.append(await run_in_threadpool(image_dimensions, output.content))
                    output = await run_in_threadpool(render_delivery_output, output, job.input_json)
                    friendly_filename = await prepare_batch_try_on_output_filename(
                        session, job, output.mime_type,
                    ) or output.filename
                    category = {"listing": "listing_output", "batch_tryon": "batch_tryon_output", "aplus": "aplus_output"}[job.workspace_type]
                    metadata = job.input_json.get("metadata") if isinstance(job.input_json.get("metadata"), dict) else {}
                    asset = await create_asset(
                        session, storage, settings, organization_id=job.organization_id, user_id=job.created_by,
                        category=category, filename=friendly_filename, declared_mime=output.mime_type, data=output.content,
                        max_bytes=settings.generated_asset_max_bytes,
                    )
                    generated = GeneratedOutput(
                        organization_id=job.organization_id, project_id=job.project_id, asset_id=asset.id,
                        job_id=job.id, batch_id=job.batch_id, sequence_number=index,
                        output_type=category, module_key=str(metadata.get("slot") or "") or None,
                        metadata_json={
                            "provider_request_id": result.provider_request_id,
                            "client_item_id": job.client_item_id,
                            "batch_tryon_review_item_id": metadata.get("batch_tryon_review_item_id"),
                            "batch_tryon_version_id": metadata.get("batch_tryon_version_id"),
                            "source_filename": metadata.get("source_filename"),
                            "display_filename": friendly_filename,
                            "output_format": asset.mime_type,
                        },
                        created_by=job.created_by, created_at=datetime.now(UTC),
                    )
                    session.add(generated)
                    await session.flush()
                    created_records.append((asset, generated))
                    stored.append({
                        "asset_id": asset.id, "generated_output_id": generated.id,
                        "mime_type": asset.mime_type, "size": asset.size, "sha256": asset.sha256,
                        "width": asset.width, "height": asset.height,
                    })
                attempt.phase_timings_json = {
                    **(attempt.phase_timings_json or {}),
                    "postprocess_and_storage_ms": max(
                        0, int((monotonic() - postprocess_started) * 1000)
                    ),
                }

                job = await get_job(session, job.organization_id, job.id, lock=True)
                now = datetime.now(UTC)
                attempt_duration_ms = max(0, int((monotonic() - provider_started) * 1000))
                job.generation_duration_ms = int(job.generation_duration_ms or 0) + attempt_duration_ms
                if job.cancel_requested_at:
                    for asset, generated in created_records:
                        await run_in_threadpool(storage.delete, asset.storage_key)
                        await session.delete(generated)
                        await session.delete(asset)
                    await finalize_cancelled_job(session, job)
                else:
                    job.status = JobStatus.SUCCEEDED.value
                    job.progress = 100
                    requested_width = job.input_json.get("requested_width")
                    requested_height = job.input_json.get("requested_height")
                    actual_width = stored[0]["width"] if stored else None
                    actual_height = stored[0]["height"] if stored else None
                    job.result_json = {
                        "outputs": stored,
                        "provider_request_id": result.provider_request_id,
                        "metadata": {
                            **(result.metadata or {}),
                            "requested_aspect_ratio": job.input_json.get("aspect_ratio"),
                            "provider_aspect_ratio": job.input_json.get("provider_aspect_ratio"),
                            "requested_width": requested_width,
                            "requested_height": requested_height,
                            "resolved_provider_size": job.input_json.get("provider_size") or job.input_json.get("size"),
                            "provider_actual_width": provider_dimensions[0][0] if provider_dimensions else None,
                            "provider_actual_height": provider_dimensions[0][1] if provider_dimensions else None,
                            "delivery_transform": delivery_transform(
                                provider_dimensions[0][0], provider_dimensions[0][1],
                                int(requested_width), int(requested_height),
                            ) if provider_dimensions and requested_width and requested_height else "none",
                            "actual_width": actual_width,
                            "actual_height": actual_height,
                            "size_mismatch": bool(
                                requested_width and requested_height and actual_width and actual_height
                                and (requested_width != actual_width or requested_height != actual_height)
                            ),
                        },
                    }
                    job.finished_at = now
                    job.heartbeat_at = now
                    attempt.status = "succeeded"
                    attempt.upstream_request_id = result.provider_request_id
                    attempt.finished_at = now
                    await mark_key_success(session, lease.key_id)
                    await settle_reservation(
                        session, organization_id=job.organization_id, reservation_id=job.quota_reservation_id,
                        user_id=job.updated_by, actual_quantity=1, idempotency_key=f"job-success:{job.id}",
                    )
                    await sync_batch_try_on_version_for_job(
                        session, job, generated_asset_id=created_records[0][0].id if created_records else None,
                    )
                if job.batch_id:
                    await refresh_batch_status(session, job.batch_id)
                session.add(ApiKeyUsageStat(
                    api_key_id=lease.key_id, organization_id=job.organization_id, job_id=job.id,
                    status="succeeded", latency_ms=attempt_duration_ms, created_at=now,
                ))
                await session.commit()
                logger.info(
                    "provider_result job_id=%s operation_code=%s resource_pool_id=%s provider_id=%s "
                    "model_id=%s queue_name=%s worker_name=%s attempt=%s upstream_request_id=%s "
                    "delivery_size=%s provider_working_size=%s actual_size=%sx%s generation_duration_ms=%s status=succeeded",
                    job.id, job.operation_code, lease.pool_id, lease.provider_id, lease.model_id,
                    job.queue_name, attempt.worker_name, attempt.attempt_number, result.provider_request_id,
                    job.input_json.get("delivery_size") or job.input_json.get("size"),
                    job.input_json.get("provider_size") or "auto",
                    stored[0]["width"] if stored else None, stored[0]["height"] if stored else None,
                    job.generation_duration_ms,
                )
                return {"job_id": job.id, "status": job.status, "outputs": len(stored)}
            except ProviderError as error:
                now = datetime.now(UTC)
                if attempt:
                    attempt_duration_ms = max(0, int((monotonic() - provider_started) * 1000)) if provider_started is not None else 0
                    job.generation_duration_ms = int(job.generation_duration_ms or 0) + attempt_duration_ms
                    attempt.status = "failed"
                    attempt.http_status = error.http_status
                    attempt.retry_after_seconds = error.retry_after_seconds
                    attempt.error_code = error.code
                    attempt.error_message = error.message[:1000]
                    attempt.finished_at = now
                    logger.warning(
                        "provider_result job_id=%s operation_code=%s resource_pool_id=%s provider_id=%s "
                        "model_id=%s queue_name=%s worker_name=%s attempt=%s error_code=%s http_status=%s status=failed",
                        job.id, job.operation_code, attempt.resource_pool_id, attempt.provider_id,
                        attempt.model_id, job.queue_name, attempt.worker_name, attempt.attempt_number,
                        error.code, error.http_status,
                    )
                    session.add(ApiKeyUsageStat(
                        api_key_id=attempt.api_key_id, organization_id=job.organization_id, job_id=job.id,
                        status="failed", http_status=error.http_status,
                        latency_ms=attempt_duration_ms, error_code=error.code, created_at=now,
                    ))
                if lease:
                    excluded.add(lease.key_id)
                    if error.http_status == 429 or error.retryable:
                        await cool_down_key(session, redis, settings, lease.key_id)
                await session.commit()
                if not error.retryable:
                    job = await get_job(session, job.organization_id, job.id, lock=True)
                    job.attempts = job.max_attempts
                    await schedule_retry_or_fail(
                        session,
                        job,
                        code=error.code,
                        message=error.message,
                        retry_delay_seconds=error.retry_after_seconds,
                    )
                    await sync_batch_try_on_version_for_job(session, job)
                    if job.batch_id:
                        await refresh_batch_status(session, job.batch_id)
                    await session.commit()
                    return {"job_id": job.id, "status": job.status, "error": error.code}
                continue
            except Exception as error:
                attempt_id = attempt.id if attempt is not None else None
                await session.rollback()
                job = await get_job(session, current_organization_id, current_job_id, lock=True)
                persisted_attempt = (
                    await session.get(JobAttempt, attempt_id, with_for_update=True)
                    if attempt_id else None
                )
                error_code = error.code if isinstance(error, AppError) else "job.execution_error"
                error_message = (
                    "等待队列中，系统将自动继续生成"
                    if error_code == "resource_pool.no_available_key"
                    else str(error)[:1000]
                )
                if persisted_attempt is not None:
                    persisted_attempt.status = "failed"
                    persisted_attempt.error_code = error_code
                    persisted_attempt.error_message = error_message
                    persisted_attempt.finished_at = datetime.now(UTC)
                if provider_started is not None and persisted_attempt is not None and persisted_attempt.provider_id:
                    job.generation_duration_ms = int(job.generation_duration_ms or 0) + max(0, int((monotonic() - provider_started) * 1000))
                await schedule_retry_or_fail(
                    session,
                    job,
                    code=error_code,
                    message=error_message,
                    retry_delay_seconds=60 if isinstance(error, AppError)
                    and error.code == "resource_pool.no_available_key" else None,
                )
                await sync_batch_try_on_version_for_job(session, job)
                if job.batch_id:
                    await refresh_batch_status(session, job.batch_id)
                await session.commit()
                return {"job_id": job.id, "status": job.status, "error": error_code}
            finally:
                if heartbeat_task:
                    heartbeat_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await heartbeat_task
                if lease:
                    await release_resource(redis, lease)

        job = await get_job(session, job.organization_id, job.id, lock=True)
        await schedule_retry_or_fail(session, job, code="job.max_attempts", message="All provider attempts failed")
        await sync_batch_try_on_version_for_job(session, job)
        if job.batch_id:
            await refresh_batch_status(session, job.batch_id)
        await session.commit()
        return {"job_id": job.id, "status": job.status, "error": job.error_code}


async def _provider_payload(session: AsyncSession, *, storage, job) -> dict[str, object]:
    payload = dict(job.input_json)
    references = []
    for asset_id in payload.pop("reference_asset_ids", []) or []:
        asset = await get_asset(session, job.organization_id, str(asset_id))
        references.append({
            "content": await run_in_threadpool(storage.download, asset.storage_key), "filename": asset.filename, "mime_type": asset.mime_type,
        })
    if references:
        payload["reference_images"] = references
    mask_id = payload.pop("mask_asset_id", None)
    if mask_id:
        mask = await get_asset(session, job.organization_id, str(mask_id))
        payload["mask_image"] = {
            "content": await run_in_threadpool(storage.download, mask.storage_key), "filename": mask.filename, "mime_type": mask.mime_type,
        }
    return reinforce_delivery_prompt(payload)


async def _job_heartbeat_loop(
    session_factory,
    redis,
    settings,
    *,
    job_id: str,
    reservation_id: str,
    lease,
) -> None:
    interval = max(10, min(30, settings.job_heartbeat_timeout_seconds // 3))
    while True:
        try:
            now = datetime.now(UTC)
            await redis.set(f"worker:heartbeat:{socket.gethostname()}", now.isoformat(), ex=180)
            async with session_factory() as heartbeat_session:
                await heartbeat_session.execute(
                    update(Job)
                    .where(Job.id == job_id, Job.status == JobStatus.RUNNING.value)
                    .values(heartbeat_at=now)
                )
                await heartbeat_session.execute(
                    update(QuotaReservation)
                    .where(
                        QuotaReservation.id == reservation_id,
                        QuotaReservation.status == QuotaReservationStatus.RESERVED.value,
                    )
                    .values(expires_at=now + timedelta(minutes=settings.quota_reservation_ttl_minutes))
                )
                await heartbeat_session.commit()
            await renew_resource_lease(redis, settings, lease)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning(
                "job_heartbeat_failed job_id=%s worker_name=%s error_type=%s",
                job_id, socket.gethostname(), type(error).__name__,
            )
        await asyncio.sleep(interval)
