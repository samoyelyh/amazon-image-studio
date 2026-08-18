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
    continue_detailed_review_auto_regeneration,
    prepare_batch_try_on_output_filename,
    sync_batch_try_on_version_for_job,
)
from app.services.image_delivery_service import (
    delivery_prompt_contract, delivery_transform, image_dimensions, reinforce_delivery_prompt, render_delivery_output,
)
from app.services.material_extract_service import render_material_extract_output
from app.services.resource_pool_service import (
    acquire_resource, cool_down_key, mark_key_success, release_resource, renew_resource_lease,
)
from app.services.region_replace_service import composite_mask_edit_output, precompose_region_replace_base
from app.services.storage_service import get_storage_service
from app.services.task_service import (
    claim_job,
    create_attempt,
    finalize_cancelled_job,
    get_job,
    refresh_batch_status,
    schedule_retry_or_fail,
    transition_job_status,
    wait_for_resource,
)
from app.workers.celery_app import celery_app
from app.workers.runtime import run_worker_coroutine
from starlette.concurrency import run_in_threadpool


UTC = timezone.utc
logger = logging.getLogger(__name__)


@celery_app.task(name="jobs.execute", ignore_result=False, acks_late=True)
def execute_job(job_id: str, dispatch_token: str | None = None) -> dict[str, object]:
    return run_worker_coroutine(lambda: _execute_job(job_id, dispatch_token))


async def _execute_job(
    job_id: str,
    dispatch_token: str | None = None,
) -> dict[str, object]:
    settings = get_settings()
    session_factory = async_sessionmaker(get_engine(), expire_on_commit=False, class_=AsyncSession)
    redis = get_redis_client()
    async with session_factory() as session:
        job = await claim_job(session, settings, job_id, dispatch_token)
        if job is not None:
            await sync_batch_try_on_version_for_job(session, job)
        await session.commit()
        if job is None:
            return {"job_id": job_id, "status": "duplicate_or_terminal"}

        excluded: set[str] = set()
        last_provider_error: ProviderError | None = None
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
                    additional_capabilities={"vision_input"} if job.capability == "text_generation"
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
                if job.capability in {"image_generation", "image_edit", "multi_image_reference", "mask_edit"}:
                    business_prompt = str(job.input_json.get("business_prompt") or job.input_json.get("prompt") or "").strip()
                    technical_contract = delivery_prompt_contract(job.input_json)
                    effective_prompt = str(provider_payload.get("prompt") or business_prompt)
                    metadata = job.input_json.get("metadata") if isinstance(job.input_json.get("metadata"), dict) else {}
                    job.input_json = {
                        **job.input_json,
                        "business_prompt": business_prompt,
                        "technical_delivery_contract": technical_contract,
                        "effective_prompt": effective_prompt,
                        "metadata": {
                            **metadata,
                            "business_prompt": business_prompt,
                            "technical_delivery_contract": technical_contract,
                            "effective_prompt": effective_prompt,
                        },
                    }
                attempt.phase_timings_json = {
                    **(attempt.phase_timings_json or {}),
                    "input_download_ms": max(0, int((monotonic() - input_started) * 1000)),
                }
                provider_started = monotonic()
                attempt.provider_requested_at = datetime.now(UTC)
                # Persist the true upstream-active boundary before entering the
                # potentially long synchronous HTTP request. Diagnostics and
                # crash recovery can then distinguish active I/O from dispatch.
                await session.commit()
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
                if job.operation_code == "asset.extract":
                    job.progress = 80
                    await session.commit()
                stored = []
                provider_dimensions: list[tuple[int, int]] = []
                created_records: list[tuple[Asset, GeneratedOutput]] = []
                storage = get_storage_service()
                for index, output in enumerate(result.outputs):
                    provider_dimensions.append(await run_in_threadpool(image_dimensions, output.content))
                    if job.capability == "mask_edit" and job.input_json.get("mask_asset_id"):
                        base_ids = job.input_json.get("reference_asset_ids", []) or []
                        if base_ids:
                            base_asset = await get_asset(session, job.organization_id, str(base_ids[0]))
                            mask_asset = await get_asset(session, job.organization_id, str(job.input_json["mask_asset_id"]))
                            metadata = job.input_json.get("metadata") if isinstance(job.input_json.get("metadata"), dict) else {}
                            composite_base = storage.download(base_asset.storage_key)
                            if str(metadata.get("workflow") or "").startswith("print_design_") and metadata.get("composite_asset_id"):
                                composite_asset = await get_asset(
                                    session, job.organization_id, str(metadata["composite_asset_id"])
                                )
                                composite_base = storage.download(composite_asset.storage_key)
                            if metadata.get("workflow") == "batch_region_replace" and len(base_ids) >= 2:
                                patch_asset = await get_asset(session, job.organization_id, str(base_ids[1]))
                                composite_base = await run_in_threadpool(
                                    precompose_region_replace_base,
                                    composite_base,
                                    storage.download(patch_asset.storage_key),
                                    metadata.get("target_mask_metadata"),
                                )
                            output = await run_in_threadpool(
                                composite_mask_edit_output,
                                composite_base,
                                storage.download(mask_asset.storage_key),
                                output,
                            )
                    output = await run_in_threadpool(render_delivery_output, output, job.input_json)
                    metadata = job.input_json.get("metadata") if isinstance(job.input_json.get("metadata"), dict) else {}
                    if job.operation_code == "asset.extract":
                        output = await run_in_threadpool(
                            render_material_extract_output,
                            output,
                            str(metadata.get("background_color") or "#00FF00"),
                        )
                    friendly_filename = await prepare_batch_try_on_output_filename(
                        session, job, output.mime_type,
                    ) or ("material-extracted.png" if job.operation_code == "asset.extract" else output.filename)
                    category = {
                        "listing": "listing_output",
                        "batch_tryon": "batch_tryon_output",
                        "aplus": "aplus_output",
                        "material_extract": "material_extract_output",
                        "print_design": "print_design_output",
                    }[job.workspace_type]
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
                            "listing_session_id": metadata.get("listing_session_id"),
                            "category_code": metadata.get("category_code"),
                            "image_type": metadata.get("image_type"),
                            "source_asset_id": metadata.get("source_asset_id"),
                            "roi_asset_id": metadata.get("roi_asset_id"),
                            "background_color": metadata.get("background_color"),
                            "selection_bounds": metadata.get("selection_bounds"),
                            "print_design_workflow": metadata.get("workflow") if str(metadata.get("workflow") or "").startswith("print_design_") else None,
                            "composite_asset_id": metadata.get("composite_asset_id"),
                            "asset_alpha_mask_asset_id": metadata.get("asset_alpha_mask_asset_id"),
                            "protect_mask_asset_id": metadata.get("protect_mask_asset_id"),
                            "edit_mask_asset_id": metadata.get("edit_mask_asset_id"),
                            "blend_ring_only": metadata.get("blend_ring_only"),
                            "protect_core": metadata.get("protect_core"),
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
                    transition_job_status(
                        job,
                        JobStatus.SUCCEEDED.value,
                        reason="provider.succeeded",
                        provider_id=lease.provider_id,
                        resource_pool_id=lease.pool_id,
                        api_key_id=lease.key_id,
                        attempt_number=attempt.attempt_number,
                    )
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
                job_metadata = job.input_json.get("metadata") if isinstance(job.input_json, dict) else None
                if (
                    job.operation_code == "listing.plan"
                    and isinstance(job_metadata, dict)
                    and job_metadata.get("quick_mode")
                    and job_metadata.get("workflow") == "category_listing_analysis"
                ):
                    try:
                        from app.services.quick_listing_service import continue_quick_listing_generation

                        await continue_quick_listing_generation(session, settings, planning_job=job)
                    except Exception as quick_error:
                        # The planning Job is already successfully committed.
                        # A maintenance probe retries the idempotent continuation,
                        # so never rewrite the successful Job as failed here.
                        logger.exception(
                            "quick_listing_continuation_failed planning_job_id=%s error_type=%s",
                            job.id,
                            type(quick_error).__name__,
                        )
                if job.operation_code in {
                    "batch_tryon.style_analyze", "batch_tryon.prompt_analyze", "batch_tryon.prompt_analyze_detailed",
                } and isinstance(job_metadata, dict) and job_metadata.get("workflow") == "batch_tryon_server_workflow":
                    try:
                        from app.services.batch_tryon_workflow_service import continue_batch_tryon_workflow

                        await continue_batch_tryon_workflow(session, settings, planning_job=job)
                    except Exception as workflow_error:
                        # The analysis job is durable and already succeeded. GET
                        # recovery retries this idempotent continuation.
                        logger.exception(
                            "batch_tryon_workflow_continuation_failed planning_job_id=%s error_type=%s",
                            job.id,
                            type(workflow_error).__name__,
                        )
                if (
                    job.operation_code == "batch_tryon.prompt_analyze_detailed"
                    and isinstance(job_metadata, dict)
                    and job_metadata.get("workflow") == "batch_tryon_review_analysis"
                    and job_metadata.get("auto_regenerate")
                ):
                    try:
                        image_job, created = await continue_detailed_review_auto_regeneration(
                            session, settings, analysis_job=job,
                        )
                        await session.commit()
                        if image_job is not None and created:
                            await dispatch_jobs(session, [image_job])
                    except Exception as continuation_error:
                        await session.rollback()
                        logger.exception(
                            "batch_review_auto_regeneration_failed analysis_job_id=%s error_type=%s",
                            job.id,
                            type(continuation_error).__name__,
                        )
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
                last_provider_error = error
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
                        http_status=error.http_status,
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
                if (
                    isinstance(error, AppError)
                    and error.code == "resource_pool.no_available_key"
                    and last_provider_error is None
                ):
                    await wait_for_resource(session, job)
                    await sync_batch_try_on_version_for_job(session, job)
                    if job.batch_id:
                        await refresh_batch_status(session, job.batch_id)
                    await session.commit()
                    logger.info(
                        "resource_wait job_id=%s operation_code=%s queue_name=%s attempts=%s "
                        "technical_retry_count=%s next_dispatch_at=%s",
                        job.id,
                        job.operation_code,
                        job.queue_name,
                        job.attempts,
                        job.technical_retry_count,
                        job.next_dispatch_at,
                    )
                    return {"job_id": job.id, "status": job.status, "error": "resource_pool.waiting"}
                persisted_attempt = (
                    await session.get(JobAttempt, attempt_id, with_for_update=True)
                    if attempt_id else None
                )
                if (
                    isinstance(error, AppError)
                    and error.code == "resource_pool.no_available_key"
                    and last_provider_error is not None
                ):
                    error_code = last_provider_error.code
                    error_message = last_provider_error.message[:1000]
                    retry_after_seconds = last_provider_error.retry_after_seconds
                    retry_http_status = last_provider_error.http_status
                else:
                    error_code = error.code if isinstance(error, AppError) else "job.execution_error"
                    error_message = str(error)[:1000]
                    retry_after_seconds = None
                    retry_http_status = None
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
                    retry_delay_seconds=retry_after_seconds,
                    http_status=retry_http_status,
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
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    if metadata.get("workflow") == "batch_region_replace" and len(references) >= 2:
        references[0] = {
            **references[0],
            "content": await run_in_threadpool(
                precompose_region_replace_base,
                references[0]["content"],
                references[1]["content"],
                metadata.get("target_mask_metadata"),
            ),
            "filename": "pixel-precomposed-base.png",
            "mime_type": "image/png",
        }
        metadata = {
            **metadata,
            "pixel_precomposition_applied": True,
            "pixel_transfer_mode": "stretch_to_target_frame",
        }
        payload["metadata"] = metadata
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
