import json
from datetime import datetime, timezone
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.core.errors import AppError
from app.models.content import (
    Asset,
    GeneratedOutput,
    ListingOutputTransfer,
    Project,
    ProjectAsset,
)
from app.models.tasks import Job
from app.schemas.listing_transfer import SendListingOutputRequest, SendListingOutputResponse
from app.services.project_service import create_project, create_project_version, get_project
from app.services.storage_service import StorageService


UTC = timezone.utc
MODEL_TEMPLATE_ROLE = "model_template"


def transfer_request_hash(output_id: str, payload: SendListingOutputRequest) -> str:
    encoded = json.dumps(
        {"output_id": output_id, **payload.model_dump(exclude={"idempotency_key"})},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(encoded.encode("utf-8")).hexdigest()


def template_draft(
    base: dict[str, object], *, asset_id: str, output: GeneratedOutput, updated_at: datetime,
) -> dict[str, object]:
    return {
        **base,
        "model_asset_id": asset_id,
        "template_source_type": "listing_generated_output",
        "template_source_id": output.id,
        "template_source_project_id": output.project_id,
        "template_updated_at": updated_at.isoformat(),
    }


def suitability_warnings(asset: Asset) -> list[str]:
    warnings: list[str] = []
    if asset.width < 1024 or asset.height < 1024:
        warnings.append("当前图片分辨率较低，批量套图结果可能受到影响。")
    return warnings


async def _transfer_response(
    session: AsyncSession, transfer: ListingOutputTransfer, *, replayed: bool,
) -> SendListingOutputResponse:
    if not transfer.target_project_id:
        raise AppError("listing.transfer_incomplete", "发送记录尚未完成，请稍后重试", 409)
    project = await get_project(session, transfer.organization_id, transfer.target_project_id)
    asset = await session.get(Asset, transfer.source_asset_id)
    output = await session.get(GeneratedOutput, transfer.listing_output_id)
    if asset is None or output is None:
        raise AppError("listing.transfer_source_missing", "原 Listing 生成结果已不存在", 404)
    return SendListingOutputResponse(
        batch_project_id=project.id,
        batch_project_name=project.name,
        model_asset_id=asset.id,
        listing_output_id=output.id,
        listing_project_id=output.project_id,
        redirect_path=f"/workspaces/batch-tryon?project_id={project.id}&source=listing&template_updated=true",
        template_replaced=transfer.template_replaced,
        created_project=transfer.created_project,
        replayed=replayed,
        warnings=suitability_warnings(asset),
    )


async def send_listing_output_to_batch_tryon(
    session: AsyncSession,
    settings: Settings,
    storage: StorageService,
    *,
    organization_id: str,
    user_id: str,
    output_id: str,
    payload: SendListingOutputRequest,
) -> tuple[SendListingOutputResponse, str | None]:
    fingerprint = transfer_request_hash(output_id, payload)
    existing = await session.scalar(select(ListingOutputTransfer).where(
        ListingOutputTransfer.organization_id == organization_id,
        ListingOutputTransfer.idempotency_key == payload.idempotency_key,
    ))
    if existing:
        if existing.request_hash != fingerprint:
            raise AppError("listing.transfer_idempotency_conflict", "幂等键已用于不同的发送请求", 409)
        return await _transfer_response(session, existing, replayed=True), None

    output = await session.scalar(select(GeneratedOutput).where(
        GeneratedOutput.id == output_id,
        GeneratedOutput.organization_id == organization_id,
        GeneratedOutput.output_type == "listing_output",
    ))
    if output is None:
        raise AppError("listing.output_not_found", "Listing 生成结果不存在或无权访问", 404)
    if not output.job_id:
        raise AppError("listing.output_job_missing", "当前生成结果没有可验证的服务端任务", 409)
    job = await session.scalar(select(Job).where(
        Job.id == output.job_id,
        Job.organization_id == organization_id,
    ))
    if job is None or job.status != "succeeded":
        raise AppError("listing.output_not_succeeded", "只有生成成功的 Listing 图片才能发送", 409)
    asset = await session.scalar(select(Asset).where(
        Asset.id == output.asset_id,
        Asset.organization_id == organization_id,
        Asset.deleted_at.is_(None),
    ))
    if asset is None:
        raise AppError("asset.not_found", "Listing 结果对应的图片素材不存在", 404)
    if asset.mime_type not in {"image/png", "image/jpeg", "image/webp"}:
        raise AppError("asset.unsupported_format", "当前生成图片格式不支持作为模特模板", 422)
    try:
        exists = await run_in_threadpool(storage.exists, asset.storage_key)
    except Exception as error:
        raise AppError("asset.storage_unavailable", "对象存储暂时不可用，请稍后重试", 502) from error
    if not exists:
        raise AppError("asset.content_missing", "当前生成图片无法读取，请重新生成或联系管理员", 404)

    if output.project_id:
        listing_project = await get_project(session, organization_id, output.project_id)
        if listing_project.project_type != "listing":
            raise AppError("listing.output_project_invalid", "生成结果不属于 Listing 项目", 409)

    transfer = ListingOutputTransfer(
        organization_id=organization_id,
        listing_output_id=output.id,
        source_asset_id=asset.id,
        target_project_id=None,
        idempotency_key=payload.idempotency_key,
        request_hash=fingerprint,
        template_replaced=False,
        created_project=payload.target_mode == "create_project",
        created_by=user_id,
        created_at=datetime.now(UTC),
    )
    session.add(transfer)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        existing = await session.scalar(select(ListingOutputTransfer).where(
            ListingOutputTransfer.organization_id == organization_id,
            ListingOutputTransfer.idempotency_key == payload.idempotency_key,
        ))
        if existing is None:
            raise
        if existing.request_hash != fingerprint:
            raise AppError("listing.transfer_idempotency_conflict", "幂等键已用于不同的发送请求", 409)
        return await _transfer_response(session, existing, replayed=True), None

    now = datetime.now(UTC)
    old_template_asset_id: str | None = None
    if payload.target_mode == "create_project":
        project = await create_project(
            session,
            settings,
            organization_id=organization_id,
            user_id=user_id,
            project_type="batch_tryon",
            name=(payload.project_name or "").strip(),
            description=payload.project_description,
            draft=template_draft({}, asset_id=asset.id, output=output, updated_at=now),
        )
    else:
        project = await get_project(session, organization_id, payload.target_project_id or "", lock=True)
        if project.project_type != "batch_tryon":
            raise AppError("batch_tryon.project_type_invalid", "目标项目不是批量套图项目", 409)
        if project.status != "draft":
            raise AppError("batch_tryon.project_not_editable", "目标项目当前不可编辑", 409)
        old_links = [link for link in project.asset_links if link.role == MODEL_TEMPLATE_ROLE]
        old_template_asset_id = old_links[0].asset_id if old_links else None
        if old_template_asset_id and old_template_asset_id != asset.id and not payload.replace_existing_template:
            raise AppError(
                "batch_tryon.template_replace_confirmation_required",
                "该项目已经设置了模特模板图，确认替换后再继续",
                409,
                {"old_template_asset_id": old_template_asset_id},
            )
        latest = max(project.versions, key=lambda item: item.version_number)
        draft = template_draft(latest.draft_json, asset_id=asset.id, output=output, updated_at=now)
        if latest.draft_json != draft:
            await create_project_version(
                session,
                settings,
                organization_id=organization_id,
                project_id=project.id,
                user_id=user_id,
                draft=draft,
                expected_version=latest.version_number,
                change_summary="Listing 生成结果设为批量套图模特模板",
            )

    template_links = [link for link in project.asset_links if link.role == MODEL_TEMPLATE_ROLE]
    matching_link = next((link for link in template_links if link.asset_id == asset.id), None)
    for link in template_links:
        if link is not matching_link:
            await session.delete(link)
    if template_links:
        await session.flush()
    if matching_link is None:
        session.add(ProjectAsset(
            organization_id=organization_id,
            project_id=project.id,
            asset_id=asset.id,
            role=MODEL_TEMPLATE_ROLE,
            sort_order=0,
            created_by=user_id,
            created_at=now,
        ))

    project.updated_by = user_id
    project.updated_at = now
    transfer.target_project_id = project.id
    transfer.template_replaced = bool(old_template_asset_id and old_template_asset_id != asset.id)
    await session.flush()
    return await _transfer_response(session, transfer, replayed=False), old_template_asset_id
