from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.session import get_db_session
from app.models.content import ProjectVersion
from app.schemas.content import (
    ProjectAssetCreateRequest,
    ProjectAssetUpdateRequest,
    ProjectCreateRequest,
    ProjectPage,
    ProjectResponse,
    ProjectStatusValue,
    ProjectTypeValue,
    ProjectUpdateRequest,
    ProjectVersionCreateRequest,
    ProjectVersionResponse,
)
from app.security.principal import Principal, require_permissions
from app.services.audit_service import add_audit_log
from app.services.project_service import (
    create_project,
    create_project_version,
    delete_project,
    get_project,
    link_asset,
    list_projects,
    project_response,
    unlink_asset,
    update_asset_link,
)


router = APIRouter(prefix="/projects", tags=["projects"])


def organization_id(principal: Principal) -> str:
    if principal.organization is None:
        raise AppError("organization.required", "Select an organization first", 409)
    return principal.organization.id


@router.get("", response_model=ProjectPage)
async def get_projects(
    project_type: ProjectTypeValue | None = None,
    project_status: ProjectStatusValue | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None, max_length=255),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("projects.read")),
) -> ProjectPage:
    return await list_projects(
        session, organization_id=organization_id(principal), project_type=project_type,
        status=project_status, search=search, limit=limit, offset=offset,
    )


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def add_project(
    payload: ProjectCreateRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("projects.write")),
) -> ProjectResponse:
    org_id = organization_id(principal)
    project = await create_project(
        session, settings, organization_id=org_id, user_id=principal.user.id,
        project_type=payload.project_type, name=payload.name, description=payload.description, draft=payload.draft,
    )
    add_audit_log(
        session, request=request, actor_user_id=principal.user.id, organization_id=org_id,
        action="project.create", resource_type="project", resource_id=project.id,
        metadata={"project_type": payload.project_type},
    )
    await session.commit()
    return project_response(await get_project(session, org_id, project.id))


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project_detail(
    project_id: str,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("projects.read")),
) -> ProjectResponse:
    return project_response(await get_project(session, organization_id(principal), project_id))


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    payload: ProjectUpdateRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("projects.write")),
) -> ProjectResponse:
    org_id = organization_id(principal)
    project = await get_project(session, org_id, project_id, lock=True)
    values = payload.model_dump(exclude_unset=True)
    if "name" in values:
        project.name = values["name"].strip()
    if "description" in values:
        project.description = values["description"].strip() if values["description"] else None
    if "status" in values:
        project.status = values["status"]
    project.updated_by = principal.user.id
    add_audit_log(
        session, request=request, actor_user_id=principal.user.id, organization_id=org_id,
        action="project.update", resource_type="project", resource_id=project.id,
        metadata={"fields": sorted(values)},
    )
    await session.commit()
    return project_response(await get_project(session, org_id, project.id))


@router.get("/{project_id}/versions", response_model=list[ProjectVersionResponse])
async def get_project_versions(
    project_id: str,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("projects.read")),
) -> list[ProjectVersionResponse]:
    org_id = organization_id(principal)
    await get_project(session, org_id, project_id)
    versions = list((await session.scalars(select(ProjectVersion).where(
        ProjectVersion.organization_id == org_id, ProjectVersion.project_id == project_id
    ).order_by(ProjectVersion.version_number.desc()))).all())
    return [ProjectVersionResponse.model_validate(item) for item in versions]


@router.post("/{project_id}/versions", response_model=ProjectVersionResponse, status_code=status.HTTP_201_CREATED)
async def add_project_version(
    project_id: str,
    payload: ProjectVersionCreateRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permissions("projects.write")),
) -> ProjectVersionResponse:
    org_id = organization_id(principal)
    version = await create_project_version(
        session, settings, organization_id=org_id, project_id=project_id, user_id=principal.user.id,
        draft=payload.draft, expected_version=payload.expected_version, change_summary=payload.change_summary,
    )
    add_audit_log(
        session, request=request, actor_user_id=principal.user.id, organization_id=org_id,
        action="project.version.create", resource_type="project", resource_id=project_id,
        metadata={"version_number": version.version_number},
    )
    await session.commit()
    await session.refresh(version)
    return ProjectVersionResponse.model_validate(version)


@router.post("/{project_id}/assets", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def add_project_asset(
    project_id: str,
    payload: ProjectAssetCreateRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("projects.write")),
) -> ProjectResponse:
    org_id = organization_id(principal)
    link = await link_asset(
        session, organization_id=org_id, project_id=project_id, asset_id=payload.asset_id,
        user_id=principal.user.id, role=payload.role, sort_order=payload.sort_order,
        display_name=payload.display_name, is_default=payload.is_default,
    )
    add_audit_log(
        session, request=request, actor_user_id=principal.user.id, organization_id=org_id,
        action="project.asset.link", resource_type="project", resource_id=project_id,
        metadata={"asset_id": payload.asset_id, "link_id": link.id, "role": payload.role},
    )
    await session.commit()
    return project_response(await get_project(session, org_id, project_id))


@router.patch("/{project_id}/assets/{link_id}", response_model=ProjectResponse)
async def patch_project_asset(
    project_id: str,
    link_id: str,
    payload: ProjectAssetUpdateRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("projects.write")),
) -> ProjectResponse:
    org_id = organization_id(principal)
    await update_asset_link(
        session,
        organization_id=org_id,
        project_id=project_id,
        link_id=link_id,
        display_name=payload.display_name,
        is_default=payload.is_default,
        sort_order=payload.sort_order,
    )
    add_audit_log(
        session, request=request, actor_user_id=principal.user.id, organization_id=org_id,
        action="project.asset.update", resource_type="project", resource_id=project_id,
        metadata={"link_id": link_id},
    )
    await session.commit()
    return project_response(await get_project(session, org_id, project_id))


@router.delete("/{project_id}/assets/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_project_asset(
    project_id: str,
    link_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("projects.write")),
) -> None:
    org_id = organization_id(principal)
    await unlink_asset(session, organization_id=org_id, project_id=project_id, link_id=link_id)
    add_audit_log(
        session, request=request, actor_user_id=principal.user.id, organization_id=org_id,
        action="project.asset.unlink", resource_type="project", resource_id=project_id,
        metadata={"link_id": link_id},
    )
    await session.commit()


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_project(
    project_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("projects.delete")),
) -> None:
    org_id = organization_id(principal)
    await delete_project(session, organization_id=org_id, project_id=project_id, user_id=principal.user.id)
    add_audit_log(
        session, request=request, actor_user_id=principal.user.id, organization_id=org_id,
        action="project.delete", resource_type="project", resource_id=project_id,
    )
    await session.commit()
