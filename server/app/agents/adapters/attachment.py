"""Reuse the Hermes read adapter; no copied attachment planning implementation."""
from sqlalchemy import select
from app.core.errors import AppError
from app.models.listing_workflow import ListingImageProject
from app.models.listing_workflow import ListingGenerationSession, ListingVersion
from app.models.attachment_planning import AttachmentWorkbenchPlan, AttachmentWorkbenchModulePlan
from app.services.hermes_tool_registry import HermesWorkbenchContext, tool_catalog
from app.services.hermes_agent_service import build_compact_workbench_context, project_state_signature


async def read_context(db, org, user, project_id):
    project = await db.scalar(select(ListingImageProject).where(ListingImageProject.id == project_id,
        ListingImageProject.organization_id == org, ListingImageProject.created_by == user))
    if project is None:
        raise AppError("agent.context_not_found", "附图项目不存在或无权访问。", 404)
    plan = await db.scalar(select(AttachmentWorkbenchPlan).where(AttachmentWorkbenchPlan.listing_image_project_id == project_id))
    session = await db.get(ListingGenerationSession, project.session_id)
    version = await db.get(ListingVersion, project.listing_version_id)
    if plan is None or session is None or version is None or not session.confirmed_at:
        raise AppError("agent.context_not_ready", "请先在原附图工作台初始化并确认商品；读取工具不会创建或修改策划。", 409)
    modules = list((await db.scalars(select(AttachmentWorkbenchModulePlan).where(AttachmentWorkbenchModulePlan.workbench_plan_id == plan.id))).all())
    context = HermesWorkbenchContext(project, session, version, plan, modules, user)
    return {"project_id": project_id, "name": "附图工作台", "context_kind": "attachment", "assets": [],
            "signature": project_state_signature(context), "context": await build_compact_workbench_context(db, context),
            "legacy_tools": tool_catalog()}
