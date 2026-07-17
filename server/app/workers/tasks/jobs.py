from __future__ import annotations

from datetime import datetime, timezone
from time import monotonic

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.db.session import get_engine
from app.infrastructure.redis import get_redis_client
from app.models.content import Asset, GeneratedOutput
from app.models.tasks import ApiKeyUsageStat, JobAttempt, JobStatus
from app.providers.base import ProviderError
from app.providers.registry import get_provider_adapter
from app.services.asset_service import create_asset, get_asset
from app.services.billing_service import settle_reservation
from app.services.resource_pool_service import acquire_resource, cool_down_key, mark_key_success, release_resource
from app.services.storage_service import get_storage_service
from app.services.task_service import claim_job, create_attempt, finalize_cancelled_job, get_job, refresh_batch_status, schedule_retry_or_fail
from app.workers.celery_app import celery_app
from app.workers.runtime import run_worker_coroutine
from starlette.concurrency import run_in_threadpool


UTC = timezone.utc


@celery_app.task(name="jobs.execute", ignore_result=False, acks_late=True)
def execute_job(job_id: str) -> dict[str, object]:
    return run_worker_coroutine(lambda: _execute_job(job_id))


async def _execute_job(job_id: str) -> dict[str, object]:
    settings = get_settings()
    session_factory = async_sessionmaker(get_engine(), expire_on_commit=False, class_=AsyncSession)
    redis = get_redis_client()
    async with session_factory() as session:
        job = await claim_job(session, settings, job_id)
        await session.commit()
        if job is None:
            return {"job_id": job_id, "status": "duplicate_or_terminal"}

        excluded: set[str] = set()
        while job.attempts < job.max_attempts:
            lease = None
            attempt = None
            started = monotonic()
            try:
                lease = await acquire_resource(
                    session, redis, settings, organization_id=job.organization_id,
                    model_code=job.model_code, capability=job.capability, excluded_key_ids=excluded,
                )
                job = await get_job(session, job.organization_id, job.id, lock=True)
                if job.cancel_requested_at:
                    await finalize_cancelled_job(session, job)
                    await session.commit()
                    return {"job_id": job.id, "status": job.status}
                attempt = create_attempt(job, provider_id=lease.provider_id, pool_id=lease.pool_id, key_id=lease.key_id)
                session.add(attempt)
                job.selected_pool_id = lease.pool_id
                job.selected_key_id = lease.key_id
                await session.commit()

                adapter = get_provider_adapter(lease.provider_type, settings)
                provider_payload = await _provider_payload(session, storage=get_storage_service(), job=job)
                result = await adapter.execute(
                    base_url=lease.base_url, api_key=lease.api_key, upstream_model=lease.upstream_model,
                    capability=job.capability, payload=provider_payload,
                    config={**lease.provider_config, **lease.model_config},
                )
                stored = []
                created_records: list[tuple[Asset, GeneratedOutput]] = []
                storage = get_storage_service()
                for index, output in enumerate(result.outputs):
                    category = {"listing": "listing_output", "batch_tryon": "batch_tryon_output", "aplus": "aplus_output"}[job.workspace_type]
                    metadata = job.input_json.get("metadata") if isinstance(job.input_json.get("metadata"), dict) else {}
                    asset = await create_asset(
                        session, storage, settings, organization_id=job.organization_id, user_id=job.created_by,
                        category=category, filename=output.filename, declared_mime=output.mime_type, data=output.content,
                    )
                    generated = GeneratedOutput(
                        organization_id=job.organization_id, project_id=job.project_id, asset_id=asset.id,
                        job_id=job.id, batch_id=job.batch_id, sequence_number=index,
                        output_type=category, module_key=str(metadata.get("slot") or "") or None,
                        metadata_json={"provider_request_id": result.provider_request_id, "client_item_id": job.client_item_id},
                        created_by=job.created_by, created_at=datetime.now(UTC),
                    )
                    session.add(generated)
                    await session.flush()
                    created_records.append((asset, generated))
                    stored.append({"asset_id": asset.id, "generated_output_id": generated.id, "mime_type": asset.mime_type, "size": asset.size, "sha256": asset.sha256})

                job = await get_job(session, job.organization_id, job.id, lock=True)
                now = datetime.now(UTC)
                if job.cancel_requested_at:
                    for asset, generated in created_records:
                        await run_in_threadpool(storage.delete, asset.storage_key)
                        await session.delete(generated)
                        await session.delete(asset)
                    await finalize_cancelled_job(session, job)
                else:
                    job.status = JobStatus.SUCCEEDED.value
                    job.progress = 100
                    job.result_json = {"outputs": stored, "provider_request_id": result.provider_request_id, "metadata": result.metadata or {}}
                    job.finished_at = now
                    job.heartbeat_at = now
                    attempt.status = "succeeded"
                    attempt.finished_at = now
                    await mark_key_success(session, lease.key_id)
                    await settle_reservation(
                        session, organization_id=job.organization_id, reservation_id=job.quota_reservation_id,
                        user_id=job.updated_by, actual_quantity=1, idempotency_key=f"job-success:{job.id}",
                    )
                if job.batch_id:
                    await refresh_batch_status(session, job.batch_id)
                session.add(ApiKeyUsageStat(
                    api_key_id=lease.key_id, organization_id=job.organization_id, job_id=job.id,
                    status="succeeded", latency_ms=int((monotonic() - started) * 1000), created_at=now,
                ))
                await session.commit()
                return {"job_id": job.id, "status": job.status, "outputs": len(stored)}
            except ProviderError as error:
                now = datetime.now(UTC)
                if attempt:
                    attempt.status = "failed"
                    attempt.http_status = error.http_status
                    attempt.error_code = error.code
                    attempt.error_message = error.message[:1000]
                    attempt.finished_at = now
                    session.add(ApiKeyUsageStat(
                        api_key_id=attempt.api_key_id, organization_id=job.organization_id, job_id=job.id,
                        status="failed", http_status=error.http_status,
                        latency_ms=int((monotonic() - started) * 1000), error_code=error.code, created_at=now,
                    ))
                if lease:
                    excluded.add(lease.key_id)
                    if error.http_status == 429 or error.retryable:
                        await cool_down_key(session, redis, settings, lease.key_id)
                await session.commit()
                if not error.retryable:
                    job = await get_job(session, job.organization_id, job.id, lock=True)
                    job.attempts = job.max_attempts
                    await schedule_retry_or_fail(session, job, code=error.code, message=error.message)
                    if job.batch_id:
                        await refresh_batch_status(session, job.batch_id)
                    await session.commit()
                    return {"job_id": job.id, "status": job.status, "error": error.code}
                continue
            except Exception as error:
                await session.rollback()
                job = await get_job(session, job.organization_id, job.id, lock=True)
                if attempt is None:
                    attempt = create_attempt(job)
                    session.add(attempt)
                else:
                    attempt = await session.get(JobAttempt, attempt.id, with_for_update=True)
                attempt.status = "failed"
                attempt.error_code = getattr(error, "code", "job.execution_error")
                attempt.error_message = str(error)[:1000]
                attempt.finished_at = datetime.now(UTC)
                await schedule_retry_or_fail(session, job, code=attempt.error_code, message=attempt.error_message)
                if job.batch_id:
                    await refresh_batch_status(session, job.batch_id)
                await session.commit()
                return {"job_id": job.id, "status": job.status, "error": attempt.error_code}
            finally:
                if lease:
                    await release_resource(redis, lease)

        job = await get_job(session, job.organization_id, job.id, lock=True)
        await schedule_retry_or_fail(session, job, code="job.max_attempts", message="All provider attempts failed")
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
    return payload
