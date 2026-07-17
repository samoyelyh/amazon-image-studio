import json
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.core.errors import AppError
from app.models.content import Asset, Project, ProjectAsset, ProjectVersion
from app.schemas.content import (
    AssetResponse,
    ProjectAssetResponse,
    ProjectPage,
    ProjectResponse,
    ProjectVersionResponse,
)


UTC = timezone.utc


def validate_draft(draft: dict[str, object], settings: Settings) -> None:
    try:
        encoded = json.dumps(draft, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise AppError("project.invalid_draft", "Project draft must be valid JSON", 422) from error
    if len(encoded) > settings.project_max_draft_bytes:
        raise AppError(
            "project.draft_too_large",
            "Project draft exceeds the configured size limit",
            413,
            {"max_bytes": settings.project_max_draft_bytes},
        )


def project_response(project: Project) -> ProjectResponse:
    if not project.versions:
        raise AppError("project.version_missing", "Project has no saved version", 500)
    latest = max(project.versions, key=lambda item: item.version_number)
    links = sorted(project.asset_links, key=lambda item: (item.sort_order, item.created_at))
    return ProjectResponse(
        id=project.id,
        project_type=project.project_type,
        name=project.name,
        description=project.description,
        status=project.status,
        created_by=project.created_by,
        updated_by=project.updated_by,
        created_at=project.created_at,
        updated_at=project.updated_at,
        latest_version=ProjectVersionResponse.model_validate(latest),
        assets=[
            ProjectAssetResponse(
                id=link.id,
                role=link.role,
                sort_order=link.sort_order,
                asset=AssetResponse.model_validate(link.asset),
                created_at=link.created_at,
            )
            for link in links
            if link.asset.deleted_at is None
        ],
    )


def _project_load_options():
    return (
        selectinload(Project.versions),
        selectinload(Project.asset_links).selectinload(ProjectAsset.asset),
    )


async def get_project(
    session: AsyncSession, organization_id: str, project_id: str, *, lock: bool = False
) -> Project:
    statement = select(Project).options(*_project_load_options()).where(
        Project.id == project_id,
        Project.organization_id == organization_id,
        Project.deleted_at.is_(None),
    )
    if lock:
        statement = statement.with_for_update()
    project = await session.scalar(statement)
    if project is None:
        raise AppError("project.not_found", "Project was not found", 404)
    return project


async def list_projects(
    session: AsyncSession,
    *,
    organization_id: str,
    project_type: str | None,
    status: str | None,
    search: str | None,
    limit: int,
    offset: int,
) -> ProjectPage:
    filters = [Project.organization_id == organization_id, Project.deleted_at.is_(None)]
    if project_type:
        filters.append(Project.project_type == project_type)
    if status:
        filters.append(Project.status == status)
    if search:
        term = f"%{search.strip()}%"
        filters.append(or_(Project.name.like(term), Project.description.like(term)))
    total = int(await session.scalar(select(func.count()).select_from(Project).where(*filters)) or 0)
    projects = list((await session.scalars(
        select(Project)
        .options(*_project_load_options())
        .where(*filters)
        .order_by(Project.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )).all())
    return ProjectPage(items=[project_response(item) for item in projects], total=total, limit=limit, offset=offset)


async def create_project(
    session: AsyncSession,
    settings: Settings,
    *,
    organization_id: str,
    user_id: str,
    project_type: str,
    name: str,
    description: str | None,
    draft: dict[str, object],
) -> Project:
    validate_draft(draft, settings)
    now = datetime.now(UTC)
    project = Project(
        organization_id=organization_id,
        project_type=project_type,
        name=name.strip(),
        description=description.strip() if description else None,
        created_by=user_id,
        updated_by=user_id,
    )
    session.add(project)
    await session.flush()
    session.add(ProjectVersion(
        organization_id=organization_id,
        project_id=project.id,
        version_number=1,
        draft_json=draft,
        change_summary="Initial draft",
        created_by=user_id,
        created_at=now,
    ))
    await session.flush()
    return await get_project(session, organization_id, project.id)


async def create_project_version(
    session: AsyncSession,
    settings: Settings,
    *,
    organization_id: str,
    project_id: str,
    user_id: str,
    draft: dict[str, object],
    expected_version: int,
    change_summary: str | None,
) -> ProjectVersion:
    validate_draft(draft, settings)
    await get_project(session, organization_id, project_id, lock=True)
    current = int(await session.scalar(
        select(func.max(ProjectVersion.version_number)).where(
            ProjectVersion.organization_id == organization_id,
            ProjectVersion.project_id == project_id,
        )
    ) or 0)
    if current != expected_version:
        raise AppError(
            "project.version_conflict",
            "Project was updated by another request; reload before saving",
            409,
            {"expected_version": expected_version, "current_version": current},
        )
    version = ProjectVersion(
        organization_id=organization_id,
        project_id=project_id,
        version_number=current + 1,
        draft_json=draft,
        change_summary=change_summary.strip() if change_summary else None,
        created_by=user_id,
        created_at=datetime.now(UTC),
    )
    session.add(version)
    project = await session.get(Project, project_id)
    if project:
        project.updated_by = user_id
        project.updated_at = datetime.now(UTC)
    try:
        await session.flush()
    except IntegrityError as error:
        raise AppError("project.version_conflict", "Project version already exists", 409) from error
    return version


async def link_asset(
    session: AsyncSession,
    *,
    organization_id: str,
    project_id: str,
    asset_id: str,
    user_id: str,
    role: str,
    sort_order: int,
) -> ProjectAsset:
    await get_project(session, organization_id, project_id, lock=True)
    asset = await session.scalar(select(Asset).where(
        Asset.id == asset_id,
        Asset.organization_id == organization_id,
        Asset.deleted_at.is_(None),
    ))
    if asset is None:
        raise AppError("asset.not_found", "Asset was not found", 404)
    link = ProjectAsset(
        organization_id=organization_id,
        project_id=project_id,
        asset_id=asset_id,
        role=role,
        sort_order=sort_order,
        created_by=user_id,
        created_at=datetime.now(UTC),
    )
    session.add(link)
    try:
        await session.flush()
    except IntegrityError as error:
        raise AppError("project.asset_already_linked", "Asset is already linked with this role", 409) from error
    return link


async def unlink_asset(session: AsyncSession, *, organization_id: str, project_id: str, link_id: str) -> None:
    await get_project(session, organization_id, project_id, lock=True)
    link = await session.scalar(select(ProjectAsset).where(
        ProjectAsset.id == link_id,
        ProjectAsset.organization_id == organization_id,
        ProjectAsset.project_id == project_id,
    ))
    if link is None:
        raise AppError("project.asset_link_not_found", "Project asset link was not found", 404)
    await session.delete(link)
    await session.flush()


async def delete_project(
    session: AsyncSession, *, organization_id: str, project_id: str, user_id: str
) -> Project:
    project = await get_project(session, organization_id, project_id, lock=True)
    for link in list(project.asset_links):
        await session.delete(link)
    project.deleted_at = datetime.now(UTC)
    project.updated_by = user_id
    await session.flush()
    return project
