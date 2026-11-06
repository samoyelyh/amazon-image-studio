from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.session import get_db_session
from app.infrastructure.redis import get_redis_client
from app.models.content import Project, Asset, ProjectAsset
from app.models.hermes_agent import HermesConversation, HermesMessage
from app.models.agent_control import AgentRun
from app.security.principal import Principal, require_permissions
from app.agents import runtime
from app.agents import dsh_platform
from app.agents import production
from app.agents import creative_modules
from app.agents import amazon, amazon_research
from app.agents.amazon_contracts import ModuleRevision, ModuleApproval
from app.agents.contracts import ConversationCreate, MessageCreate, ConfirmRequest, RunResponse, AttachmentCreate, StrictModel
from app.agents.contracts import PromptRevisionRequest
from app.agents.adapters import batch_tryon, attachment, chat
from app.agents.tool_registry import catalog
from app.services.storage_service import StorageService, get_storage_service

router = APIRouter(prefix="/agent", tags=["agent-control"])


async def _agent_db(db: AsyncSession = Depends(get_db_session)):
    # Only Agent HTTP transactions use current committed reads. The principal
    # shares this dependency, so configure before its first query. Existing
    # conversation/Run locks, revision checks and idempotency still serialize
    # writes; other workspaces and Worker transactions keep their isolation.
    if db.get_bind().dialect.name == 'mysql' and not db.in_transaction():
        db.sync_session.bind = db.get_bind().execution_options(isolation_level='READ COMMITTED')
    return db


def _org(principal):
    if principal.organization is None:
        raise AppError("organization.required", "请先选择组织。", 409)
    return principal.organization.id


def _settings(settings: Settings = Depends(get_settings)):
    runtime.enabled(settings)
    return settings


@router.get("/status")
async def status(settings: Settings = Depends(get_settings), db: AsyncSession = Depends(_agent_db),
                 principal: Principal = Depends(require_permissions("jobs.read"))):
    active=await dsh_platform.controller(db)
    models = {}
    if settings.agent_control_enabled and principal.organization:
        from app.services.resource_pool_service import resolve_operation_model_code
        for name, operation, capability in (("text", "listing.plan", "text_generation"),
                ("image", "listing.generate", "image_generation"), ("edit", "listing.generate", "image_edit")):
            try:
                code = await resolve_operation_model_code(db, organization_id=_org(principal), operation_code=operation, capability=capability,
                    preferred_model_code=('kimi-for-coding' if active=='dsh' else settings.agent_control_text_model) if name=='text' else None)
                models[name] = {"configured": True, "model_code": code}
            except AppError as error:
                models[name] = {"configured": False, "reason": error.code}
    return {"controller":active,"enabled": settings.agent_control_enabled, "writes_enabled": settings.agent_control_writes_enabled,
            "model_calls_enabled": settings.agent_control_model_calls_enabled, "planner_mode": settings.agent_control_planner,
            "checkpoint_configured": active=='dsh' or bool(settings.agent_checkpoint_url), "models": models,
            "dynamic_capabilities_enabled": settings.agent_dynamic_capabilities_enabled,
            "creative_assistance_enabled": settings.agent_control_enabled,
            "auto_execution": {"enabled": settings.agent_auto_execute_enabled,
                'mode':settings.agent_execution_mode,
                "max_images": settings.agent_auto_max_images, "max_seconds": settings.agent_auto_max_seconds,
                "max_credits": settings.agent_auto_max_credits,
                "max_active_runs": settings.agent_auto_max_active_runs,
                "submissions_per_minute": settings.agent_auto_submissions_per_minute},
            "tools": catalog() if settings.agent_control_enabled else []}


@router.get("/capabilities")
async def capability_catalog(settings: Settings = Depends(_settings),
    principal: Principal = Depends(require_permissions("jobs.read"))):
    from app.agents.capabilities.contracts import ExecutionContext
    from app.agents.capabilities.registry import CapabilityRegistry
    ctx = ExecutionContext(_org(principal), principal.user.id, "catalog", "catalog", principal.permissions)
    registry = CapabilityRegistry(settings, ctx)
    return {"catalog_version": registry.snapshot(), "dynamic_enabled": settings.agent_dynamic_capabilities_enabled,
        "skills": registry.skill_catalog, "tools": [c.summary() for c in registry.capabilities.values()],
        "mcp_servers": [{"id": s.id, "version": s.version, "state": "approved_not_connected",
            "timeout_seconds": s.timeout_seconds, "max_calls_per_run": s.max_calls_per_run,
            "tools": len(s.tools)} for s in registry.mcp.values()],
        "approval_mode": "server_owned_manifest", "execution_state": "see_run_tool_events"}


@router.get("/capabilities/skills/{skill_id}")
async def read_skill(skill_id: str, resource: str | None = Query(default=None, max_length=200),
    settings: Settings = Depends(_settings), principal: Principal = Depends(require_permissions("jobs.read"))):
    from app.agents.capabilities.contracts import ExecutionContext
    from app.agents.capabilities.registry import CapabilityRegistry
    registry = CapabilityRegistry(settings, ExecutionContext(_org(principal), principal.user.id, "catalog", "catalog", principal.permissions))
    skill = registry.load_skill(skill_id)
    if resource:
        owner = registry._builtins if skill_id in registry._builtins._entries else registry.skills
        return {"skill_id": skill_id, "version": skill["version"], "resource": resource,
                "content": owner.resource(skill_id, resource), "trust": "skill_reference_data"}
    return skill


@router.get("/library")
async def library(search: str = Query(default="", max_length=100), db: AsyncSession = Depends(_agent_db),
    settings: Settings = Depends(_settings), principal: Principal = Depends(require_permissions("assets.read"))):
    rows = (await db.execute(select(Asset.id, Asset.filename, Asset.category).where(
        Asset.organization_id == _org(principal), Asset.created_by == principal.user.id, Asset.deleted_at.is_(None),
        Asset.filename.contains(search)).order_by(Asset.created_at.desc(), Asset.id).limit(40))).all()
    return [{"id": a.id, "filename": a.filename, "category": a.category,
             "content_url": f"/api/v1/assets/{a.id}/content"} for a in rows]


@router.get("/contexts")
async def contexts(db: AsyncSession = Depends(_agent_db), settings: Settings = Depends(_settings),
                   principal: Principal = Depends(require_permissions("jobs.read", "projects.read"))):
    rows = (await db.scalars(select(Project).where(Project.organization_id == _org(principal),
        Project.created_by == principal.user.id, Project.deleted_at.is_(None), Project.project_type.in_(["batch_tryon", "listing"]))
        .order_by(Project.updated_at.desc()).limit(100))).all()
    return [{"id": p.id, "name": p.name, "project_type": p.project_type} for p in rows]


@router.get("/contexts/{project_id}")
async def context(project_id: str, db: AsyncSession = Depends(_agent_db), settings: Settings = Depends(_settings),
                  principal: Principal = Depends(require_permissions("jobs.read", "projects.read", "assets.read"))):
    return await batch_tryon.read_context(db, _org(principal), principal.user.id, project_id)


@router.post("/conversations", status_code=201)
async def create_conversation(payload: ConversationCreate, db: AsyncSession = Depends(_agent_db),
    settings: Settings = Depends(_settings), principal: Principal = Depends(require_permissions("jobs.read", "projects.read", "assets.read"))):
    org, user = _org(principal), principal.user.id
    chat_mode = payload.context_kind == "chat" or payload.project_id is None
    if chat_mode:
        if payload.project_id:
            await batch_tryon.owned_project(db, org, user, payload.project_id)
    elif payload.context_kind == "attachment":
        await attachment.read_context(db, org, user, payload.project_id)
    else:
        project = await batch_tryon.owned_project(db, org, user, payload.project_id)
        if project.project_type != "batch_tryon":
            raise AppError("agent.context_invalid", "当前阶段请选择批量套图项目。", 422)
    row = HermesConversation(organization_id=org, user_id=user, controller_type=await dsh_platform.controller(db), title=payload.title,
        mode="chat" if chat_mode else "suggest",
        context_project_id=payload.project_id if chat_mode or payload.context_kind == "batch_tryon" else None,
        listing_image_project_id=payload.project_id if not chat_mode and payload.context_kind == "attachment" else None)
    db.add(row)
    await db.flush()
    if chat_mode and payload.creative_module is not None:await creative_modules.change(db,row,payload.creative_module)
    if chat_mode and payload.project_id:
        links = (await db.execute(select(ProjectAsset.asset_id, ProjectAsset.role).join(Asset, Asset.id == ProjectAsset.asset_id).where(
            ProjectAsset.project_id == payload.project_id, Asset.created_by == user, Asset.organization_id == org,
            Asset.deleted_at.is_(None), ProjectAsset.role.in_(["model_template", "garment", "product_reference", "font_reference","garment_reference.front","garment_reference.back","garment_reference.detail"])).limit(501))).all()
        if len(links) > 500:
            raise AppError("agent.context_too_large", "该项目素材较多，请直接从素材库选择本次图片。", 422)
        for link in links:
            await chat.attach(db, row, AttachmentCreate(asset_id=link.asset_id,
                role={"model_template": "template", "garment": "garment", "font_reference": "font","garment_reference.front":"front","garment_reference.back":"back","garment_reference.detail":"detail"}.get(link.role, "reference")))
        from app.agents import batch_manifest
        await batch_manifest.sync(db,row)
    await db.commit()
    return {"id": row.id, "title": row.title, "context_kind": "chat" if chat_mode else payload.context_kind, "project_id": payload.project_id,
            "controller_type": row.controller_type, "read_only": payload.context_kind == "attachment",'creative_context':await creative_modules.read(db,row)}


@router.get("/conversations")
async def conversations(db: AsyncSession = Depends(_agent_db), settings: Settings = Depends(_settings),
    principal: Principal = Depends(require_permissions("jobs.read"))):
    rows = (await db.scalars(select(HermesConversation).where(HermesConversation.organization_id == _org(principal),
        HermesConversation.user_id == principal.user.id, HermesConversation.controller_type.in_(['langgraph','dsh']),HermesConversation.mode!='memory')
        .order_by(HermesConversation.updated_at.desc()).limit(50))).all()
    return [{"id": r.id, "title": r.title, "project_id": r.context_project_id or r.listing_image_project_id,
             "context_kind": "chat" if r.mode == "chat" else "batch_tryon" if r.context_project_id else "attachment"} for r in rows]


@router.get("/conversations/{conversation_id}")
async def read_conversation(conversation_id: str, db: AsyncSession = Depends(_agent_db),
    settings: Settings = Depends(_settings), principal: Principal = Depends(require_permissions("jobs.read"))):
    conv = await runtime.conversation(db, _org(principal), principal.user.id, conversation_id)
    if conv.context_project_id:
        await batch_tryon.owned_project(db, _org(principal), principal.user.id, conv.context_project_id)
    messages = (await db.scalars(select(HermesMessage).where(HermesMessage.conversation_id == conv.id,
        HermesMessage.role.in_(["user", "assistant"]))
        .order_by(HermesMessage.created_at.desc(), HermesMessage.id.desc()).limit(100))).all()
    run_ids=list((await db.scalars(select(AgentRun.id).where(AgentRun.conversation_id == conv.id)
        .order_by(AgentRun.created_at.desc()).limit(20))).all())
    runs=list((await db.scalars(select(AgentRun).where(AgentRun.id.in_(run_ids)))).all()) if run_ids else []
    # Existing MySQL timestamp columns may have second precision. Preserve
    # actual message order without a schema migration or UUID tie-breaking.
    def message_time(message):
        value = message.metadata_json.get('sent_at')
        parsed = datetime.fromisoformat(value) if value else message.created_at
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    messages = sorted(messages, key=lambda m:(message_time(m),m.id))
    source_times = {m.id:message_time(m) for m in messages}
    reply_times={}
    for m in messages:
        source=(m.metadata_json or {}).get('reply_to_run_id') if m.role=='user' else None
        if source:reply_times[source]=max(reply_times.get(source,message_time(m)),message_time(m))
    runs = sorted(runs,key=lambda r:source_times.get(r.source_message_id,
        r.created_at.replace(tzinfo=timezone.utc)) if r.id not in reply_times else reply_times[r.id],reverse=True)
    from app.agents import batch_manifest
    manifest_row=await batch_manifest.record(db,conv) if conv.mode=='chat' else None
    for r in runs:
        if r.graph_version.startswith('dsh-'):await dsh_platform.sync(db,r,principal)
    return {"id": conv.id, "title": conv.title, "project_id": conv.context_project_id or conv.listing_image_project_id,
        'creative_context':await creative_modules.read(db,conv),
        'batch_input_manifest':batch_manifest.snapshot(manifest_row,batch_manifest.BatchInputManifest.model_validate(manifest_row.metadata_json)) if manifest_row else None,
        "context_kind": "chat" if conv.mode == "chat" else "batch_tryon" if conv.context_project_id else "attachment",
        "attachments": await chat.attachments(db, conv) if conv.mode == "chat" else [],
        "production_plans": await production.list_plans(db,conv) if conv.mode=='chat' else [],
        "amazon_plans": await amazon.list_plans(db,conv) if conv.mode=='chat' else [],
        "amazon_research": await amazon_research.receipts(db,conv) if conv.mode=='chat' else [],
        "messages": [{"id": m.id, "role": m.role, "content": m.content, "metadata": m.metadata_json} for m in messages],
        "runs": [await runtime.response(db, settings, r) for r in runs]}


@router.put('/conversations/{conversation_id}/creative-context')
async def update_creative_context(conversation_id:str,payload:creative_modules.ModuleChange,db:AsyncSession=Depends(_agent_db),
    settings:Settings=Depends(_settings),principal:Principal=Depends(require_permissions('jobs.read'))):
    if not settings.agent_control_writes_enabled:raise AppError('agent.writes_disabled','当前未启用总控写入。',409)
    conv=await runtime.conversation(db,_org(principal),principal.user.id,conversation_id,lock=True)
    result=await creative_modules.change(db,conv,payload.module,payload.expected_revision)
    await db.commit();return result


@router.post("/conversations/{conversation_id}/attachments", status_code=201)
async def add_attachment(conversation_id: str, payload: AttachmentCreate, db: AsyncSession = Depends(_agent_db),
    settings: Settings = Depends(_settings), principal: Principal = Depends(require_permissions("assets.read"))):
    conv = await runtime.conversation(db, _org(principal), principal.user.id, conversation_id, lock=True)
    if conv.mode != "chat":
        raise AppError("agent.mode_mismatch", "请新建对话后上传素材。", 409)
    from app.agents.adapters.chat import attach
    result = await attach(db, conv, payload)
    from app.agents import batch_manifest
    await batch_manifest.sync(db,conv,role_updates={payload.asset_id:result['role']})
    await db.commit()
    return result


@router.put('/conversations/{conversation_id}/amazon-plans/{plan_id}/module')
async def revise_amazon_module(conversation_id:str,plan_id:str,payload:ModuleRevision,db:AsyncSession=Depends(_agent_db),
    settings:Settings=Depends(_settings),principal:Principal=Depends(require_permissions('projects.write','assets.read'))):
    if not settings.agent_control_writes_enabled:raise AppError('agent.writes_disabled','总控写操作未启用。',403)
    if payload.plan_id!=plan_id:raise AppError('agent.context_mismatch','方案ID不匹配。',422)
    conv=await runtime.conversation(db,_org(principal),principal.user.id,conversation_id,lock=True)
    result=await amazon.revise(db,conv,payload);await db.commit();return result


@router.post('/conversations/{conversation_id}/amazon-plans/{plan_id}/confirm')
async def approve_amazon_modules(conversation_id:str,plan_id:str,payload:ModuleApproval,db:AsyncSession=Depends(_agent_db),
    settings:Settings=Depends(_settings),principal:Principal=Depends(require_permissions('projects.write','assets.read'))):
    if not settings.agent_control_writes_enabled:raise AppError('agent.writes_disabled','总控写操作未启用。',403)
    conv=await runtime.conversation(db,_org(principal),principal.user.id,conversation_id,lock=True)
    result=await amazon.approve(db,conv,plan_id,payload);await db.commit();return result


@router.get('/conversations/{conversation_id}/amazon-plans/{plan_id}/export')
async def export_amazon_brief(conversation_id:str,plan_id:str,db:AsyncSession=Depends(_agent_db),
    settings:Settings=Depends(_settings),principal:Principal=Depends(require_permissions('jobs.read','assets.read'))):
    from fastapi.responses import Response
    import json
    conv=await runtime.conversation(db,_org(principal),principal.user.id,conversation_id)
    from app.agents.amazon_export import manifest
    body=await manifest(db,conv,plan_id)
    return Response(json.dumps(body,ensure_ascii=False,indent=2),media_type='application/json',
        headers={'Content-Disposition':f'attachment; filename="aplus-{plan_id}.json"'})


@router.get('/conversations/{conversation_id}/amazon-plans/{plan_id}/archive')
async def export_amazon_archive(conversation_id:str,plan_id:str,db:AsyncSession=Depends(_agent_db),
    storage:StorageService=Depends(get_storage_service),settings:Settings=Depends(_settings),
    principal:Principal=Depends(require_permissions('jobs.read','assets.read'))):
    from fastapi.responses import StreamingResponse
    from starlette.background import BackgroundTask
    from app.agents.amazon_export import archive
    conv=await runtime.conversation(db,_org(principal),principal.user.id,conversation_id)
    stream=await archive(db,storage,conv,plan_id)
    def chunks():
        try:
            while chunk:=stream.read(65536):yield chunk
        finally:stream.close()
    return StreamingResponse(chunks(),media_type='application/zip',background=BackgroundTask(stream.close),
        headers={'Content-Disposition':f'attachment; filename="aplus-{plan_id}.zip"'})

@router.get('/conversations/{conversation_id}/amazon-plans/{plan_id}/source/{module_id}/{slot_id}')
async def amazon_source_crop(conversation_id:str,plan_id:str,module_id:str,slot_id:str,db:AsyncSession=Depends(_agent_db),
    storage:StorageService=Depends(get_storage_service),principal:Principal=Depends(require_permissions('jobs.read','assets.read'))):
    from fastapi.responses import Response
    from app.agents.amazon_source import render
    conv=await runtime.conversation(db,_org(principal),principal.user.id,conversation_id)
    content,_=await render(db,storage,conv,plan_id,module_id,slot_id)
    return Response(content,media_type='image/png',headers={'Cache-Control':'private, no-store'})


@router.delete("/conversations/{conversation_id}/attachments/{attachment_id}", status_code=204)
async def remove_attachment(conversation_id: str, attachment_id: str, db: AsyncSession = Depends(_agent_db),
    settings: Settings = Depends(_settings), principal: Principal = Depends(require_permissions("assets.read"))):
    conv = await runtime.conversation(db, _org(principal), principal.user.id, conversation_id, lock=True)
    from app.agents.adapters.chat import detach
    await detach(db, conv, attachment_id)
    from app.agents import batch_manifest
    await batch_manifest.sync(db,conv)
    await db.commit()


@router.post("/conversations/{conversation_id}/messages", response_model=RunResponse)
async def message(conversation_id: str, payload: MessageCreate, db: AsyncSession = Depends(_agent_db),
    redis=Depends(get_redis_client), settings: Settings = Depends(_settings),
    principal: Principal = Depends(require_permissions("jobs.read", "projects.read", "assets.read"))):
    conv = await runtime.conversation(db, _org(principal), principal.user.id, conversation_id, lock=True)
    active=await dsh_platform.controller(db)
    if payload.reply_to_run_id:
        bound=await runtime.owned_run(db,_org(principal),principal.user.id,payload.reply_to_run_id)
        if bound.conversation_id!=conv.id:raise AppError('agent.run_missing','原任务不属于本对话。',404)
        active='dsh' if bound.graph_version.startswith('dsh-') else 'langgraph'
    if active=='dsh':
        run=await dsh_platform.send(db,settings,conv,payload,principal)
        return await runtime.response(db,settings,run)
    conv.controller_type='langgraph'
    run = await runtime.create_run(db, settings, redis, conv, payload, principal.permissions)
    from app.agents.auto_execution import drive
    await drive(db,settings,redis,run,principal.permissions)
    return await runtime.response(db, settings, run)


@router.put('/conversations/{conversation_id}/production-plans/{plan_id}')
async def update_production_rules(conversation_id:str,plan_id:str,payload:production.UpdateRules,
    db:AsyncSession=Depends(_agent_db),settings:Settings=Depends(_settings),principal:Principal=Depends(require_permissions('projects.write'))):
    from app.agents import production
    conv=await runtime.conversation(db,_org(principal),principal.user.id,conversation_id,lock=True)
    result=await production.update(db,conv,plan_id,payload);await db.commit();return result


from app.agents.batch_manifest import ManifestUpdate


@router.get('/conversations/{conversation_id}/batch-inputs')
async def read_batch_inputs(conversation_id:str, db:AsyncSession=Depends(_agent_db),settings:Settings=Depends(_settings),
    principal:Principal=Depends(require_permissions('assets.read'))):
    from app.agents import batch_manifest
    conv=await runtime.conversation(db,_org(principal),principal.user.id,conversation_id)
    row=await batch_manifest.record(db,conv)
    return batch_manifest.snapshot(row,batch_manifest.BatchInputManifest.model_validate(row.metadata_json)) if row else None


@router.get('/conversations/{conversation_id}/production-plans/{plan_id}/archive')
async def export_chat_batch(conversation_id:str,plan_id:str,request:Request,template_asset_id:str|None=None,garment_id:str|None=None,
    allow_partial:bool=False,db:AsyncSession=Depends(_agent_db),storage:StorageService=Depends(get_storage_service),
    settings:Settings=Depends(_settings),principal:Principal=Depends(require_permissions('jobs.read','assets.read'))):
    from app.models.tasks import BatchTryOnReviewItem,Job
    from app.services.batch_tryon_export_service import _load_export_versions,_build_template_archive
    from app.api.batch_tryon_review import template_archive_response
    conv=await runtime.conversation(db,_org(principal),principal.user.id,conversation_id)
    _,rules=await production.plan_record(db,conv,plan_id)
    if not rules.production_batch_id:raise AppError('agent.batch_missing','尚未创建正式批次。',409)
    batch_ids=[b['batch_id'] for b in rules.production_batches] or [rules.production_batch_id]
    query=select(BatchTryOnReviewItem).where(BatchTryOnReviewItem.batch_id.in_(batch_ids),
        BatchTryOnReviewItem.organization_id==conv.organization_id,BatchTryOnReviewItem.created_by==conv.user_id)
    if template_asset_id:
        if template_asset_id not in rules.template_rules:raise AppError('agent.template_missing','模板不属于本方案。',404)
        query=query.where(BatchTryOnReviewItem.model_asset_id==template_asset_id)
    items=list((await db.scalars(query)).all())
    if garment_id:
        if garment_id not in rules.garment_rules:raise AppError('agent.garment_missing','服装不属于本方案。',404)
        asset_id=next(g['primary_asset_id'] for g in rules.input_manifest['garments'] if g['id']==garment_id) if rules.input_manifest else garment_id
        items=[i for i in items if i.garment_asset_id==asset_id]
    versions,assets=await _load_export_versions(db,organization_id=conv.organization_id,items=items)
    stream,name,count,skipped=await _build_template_archive(db,storage,items=items,versions_by_item=versions,assets=assets,
        template_id=template_asset_id,scope='all_succeeded',whole_batch=not template_asset_id,allow_partial=allow_partial,
        request_id=getattr(request.state,'request_id',None))
    await db.commit()
    return template_archive_response(stream,filename=name,success_count=count,skipped_count=skipped,
        template_id=template_asset_id or '',scope='all_succeeded')


@router.put('/conversations/{conversation_id}/batch-inputs')
async def update_batch_inputs(conversation_id:str,payload:ManifestUpdate,db:AsyncSession=Depends(_agent_db),settings:Settings=Depends(_settings),
    principal:Principal=Depends(require_permissions('assets.read','projects.write'))):
    if not settings.agent_control_writes_enabled:raise AppError('agent.writes_disabled','总控写操作未启用。',403)
    from app.agents import batch_manifest
    conv=await runtime.conversation(db,_org(principal),principal.user.id,conversation_id,lock=True)
    result=await batch_manifest.update(db,conv,payload)
    await db.commit()
    return result


@router.post('/conversations/{conversation_id}/production-plans/{plan_id}/confirm')
async def confirm_production_rules(conversation_id:str,plan_id:str,payload:production.ConfirmRules,
    db:AsyncSession=Depends(_agent_db),settings:Settings=Depends(_settings),principal:Principal=Depends(require_permissions('jobs.submit'))):
    from app.agents import production
    conv=await runtime.conversation(db,_org(principal),principal.user.id,conversation_id,lock=True)
    result=await production.update(db,conv,plan_id,payload,confirm=True);await db.commit();return result


class SampleApproval(StrictModel):
    output_id:str
    expected_revision:int


@router.post('/conversations/{conversation_id}/production-plans/{plan_id}/approve-sample')
async def approve_production_sample(conversation_id:str,plan_id:str,payload:SampleApproval,
    db:AsyncSession=Depends(_agent_db),settings:Settings=Depends(_settings),principal:Principal=Depends(require_permissions('batch_tryon.review'))):
    from app.agents import production
    conv=await runtime.conversation(db,_org(principal),principal.user.id,conversation_id,lock=True)
    from app.agents import samples
    _,rules=await production.plan_record(db,conv,plan_id,True)
    output=next((o for o in await chat.outputs(db,conv) if o['id']==payload.output_id),None)
    tid=next((tid for tid,jid in rules.samples.items() if output and output['job_id']==jid),None)
    if tid is None:raise AppError('agent.sample_not_found','该图片不是当前样图。',404)
    args=samples.ReviewSamples(plan_id=plan_id,expected_revision=payload.expected_revision,expected_review_revision=rules.review_revision,
        decisions=[samples.SampleDecision(sample_number=list(rules.template_rules).index(tid)+1,decision='approve',output_id=payload.output_id)])
    await samples.execute(db,settings,conv,args,'legacy-sample-approval:'+payload.output_id,human_request='样图通过',card_request=args.model_dump())
    row,rules=await production.plan_record(db,conv,plan_id)
    result=production.response(row,rules)
    await db.commit();return result


@router.get("/runs/{run_id}", response_model=RunResponse)
async def read_run(run_id: str, db: AsyncSession = Depends(_agent_db), redis=Depends(get_redis_client),
    settings: Settings = Depends(_settings), principal: Principal = Depends(require_permissions("jobs.read"))):
    run = await runtime.owned_run(db, _org(principal), principal.user.id, run_id, lock=True)
    if run.graph_version.startswith('dsh-'):
        await dsh_platform.sync(db,run,principal)
        return await runtime.response(db,settings,run)
    await runtime.reconcile(db, settings, redis, run, principal.permissions)
    from app.agents.auto_execution import drive
    await drive(db,settings,redis,run,principal.permissions)
    return await runtime.response(db, settings, run)


@router.get("/runs/{run_id}/events")
async def events(run_id: str, db: AsyncSession = Depends(_agent_db), settings: Settings = Depends(_settings),
                 principal: Principal = Depends(require_permissions("jobs.read"))):
    run = await runtime.owned_run(db, _org(principal), principal.user.id, run_id)
    return (await runtime.response(db, settings, run)).events


@router.post('/runs/{run_id}/prompts',response_model=RunResponse)
async def save_prompt(run_id:str,payload:PromptRevisionRequest,db:AsyncSession=Depends(_agent_db),
    settings:Settings=Depends(_settings),principal:Principal=Depends(require_permissions('jobs.submit','assets.read'))):
    from app.agents import prompt_history
    from app.models.agent_control import AgentJobLink
    from app.models.tasks import Job
    if not settings.agent_control_writes_enabled:raise AppError('agent.writes_disabled','当前环境未启用编辑。',409)
    run=await runtime.owned_run(db,_org(principal),principal.user.id,run_id,lock=True)
    jobs=list((await db.scalars(select(Job).join(AgentJobLink,AgentJobLink.job_id==Job.id).where(
        AgentJobLink.run_id==run.id,Job.organization_id==run.organization_id,Job.created_by==run.user_id))).all())
    value=prompt_history.save(run,payload,jobs)
    await runtime.event(db,run,'prompt_version_saved',{'version_id':value['id'],'version':value['version']})
    await db.commit()
    return await runtime.response(db,settings,run)


@router.post("/runs/{run_id}/confirm", response_model=RunResponse)
async def confirm(run_id: str, payload: ConfirmRequest, db: AsyncSession = Depends(_agent_db),
    redis=Depends(get_redis_client), settings: Settings = Depends(_settings),
    principal: Principal = Depends(require_permissions("jobs.read", "projects.read", "assets.read"))):
    run = await runtime.owned_run(db, _org(principal), principal.user.id, run_id, lock=True)
    # An explicit confirmation authorizes this proposal only, not an enlarged
    # automatic continuation after a threshold/risk boundary was reached.
    if run.status=='awaiting_confirmation' and run.result_json.get('auto_execution'):
        run.result_json={**run.result_json,'auto_execution':{**run.result_json['auto_execution'],'suspended':True}}
    await runtime.confirm(db, settings, redis, run, payload, principal.permissions)
    return await runtime.response(db, settings, run)


@router.post("/runs/{run_id}/resume", response_model=RunResponse)
async def resume(run_id: str, db: AsyncSession = Depends(_agent_db), redis=Depends(get_redis_client),
    settings: Settings = Depends(_settings), principal: Principal = Depends(require_permissions("jobs.read"))):
    run = await runtime.owned_run(db, _org(principal), principal.user.id, run_id, lock=True)
    if run.graph_version.startswith('dsh-'):
        await dsh_platform.resume(db,run,principal)
        return await runtime.response(db,settings,run)
    # Resume only observes already-existing jobs. Pending paid actions use /confirm.
    await runtime.reconcile(db, settings, redis, run, principal.permissions)
    from app.agents.auto_execution import drive
    await drive(db,settings,redis,run,principal.permissions)
    return await runtime.response(db, settings, run)


@router.post("/runs/{run_id}/stop", response_model=RunResponse)
async def stop(run_id: str, db: AsyncSession = Depends(_agent_db), settings: Settings = Depends(_settings),
               principal: Principal = Depends(require_permissions("jobs.read"))):
    run = await runtime.owned_run(db, _org(principal), principal.user.id, run_id, lock=True)
    if run.graph_version.startswith('dsh-'):
        await dsh_platform.stop(db,run,principal)
        return await runtime.response(db,settings,run)
    await runtime.cancel(db, run)
    return await runtime.response(db, settings, run)


class ControllerChange(StrictModel):
    controller:str

@router.put('/controller')
async def change_controller(payload:ControllerChange,db:AsyncSession=Depends(_agent_db),principal:Principal=Depends(require_permissions('platform.admin'))):
    return await dsh_platform.set_controller(db,payload.controller,principal.user.id)
