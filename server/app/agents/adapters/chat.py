"""Conversation assets and fast images over the existing Project/Job/Asset services."""
from datetime import datetime, timezone
import re

from sqlalchemy import select

from app.core.errors import AppError
from app.models.content import Asset, GeneratedOutput, Project, ProjectAsset
from app.models.hermes_agent import HermesConversation, HermesMessage
from app.models.agent_control import AgentRun, AgentJobLink
from app.models.tasks import Job
from app.schemas.tasks import BatchJobItemRequest, JobBatchSubmitRequest
from app.services import project_service
from app.services.task_service import submit_batch
from app.services.billing_service import estimate_response
from app.services.resource_pool_service import resolve_operation_model_code
from app.services.proposal_confirmation_service import state_fingerprint

UTC = timezone.utc


async def asset(db, org, user, asset_id):
    # Agent conversations remain private even where another workspace publishes libraries.
    row = await db.scalar(select(Asset).where(Asset.id == asset_id, Asset.organization_id == org,
        Asset.created_by == user, Asset.deleted_at.is_(None)))
    if row is None:
        raise AppError("agent.asset_not_found", "图片不存在或不属于当前账号。", 404)
    return row


async def attachments(db, conv):
    records = list((await db.scalars(select(HermesMessage).where(HermesMessage.conversation_id == conv.id,
        HermesMessage.role == "attachment").order_by(HermesMessage.created_at, HermesMessage.id).limit(501))).all())
    if len(records) > 500:
        raise AppError("agent.context_too_large", "当前会话素材已达上限，请新建对话。", 422)
    ids = {m.metadata_json.get("asset_id") for m in records}
    rows = (await db.execute(select(Asset.id, Asset.filename, Asset.sha256, Asset.category, Asset.updated_at)
        .where(Asset.id.in_(ids), Asset.organization_id == conv.organization_id, Asset.created_by == conv.user_id,
               Asset.deleted_at.is_(None)))).all() if ids else []
    by_id = {a.id: a for a in rows}
    return [{"id": m.id, "asset_id": a.id, "filename": a.filename, "name": a.filename,
        "role": (m.metadata_json.get('inferred_role') or m.metadata_json.get('role','reference')) if m.metadata_json.get('role','reference')=='reference' else m.metadata_json['role'],
        "inferred_role":m.metadata_json.get('inferred_role'),"role_reason":m.metadata_json.get('role_reason'),
        'import_info':m.metadata_json.get('import_info'),'garment_key':m.metadata_json.get('garment_key',''),
        "submitted": bool(m.metadata_json.get("submitted")),
        "sha256": a.sha256, "content_url": f"/api/v1/assets/{a.id}/content"}
        for m in records if (a := by_id.get(m.metadata_json.get("asset_id")))]


async def attach(db, conv, payload):
    item = await asset(db, conv.organization_id, conv.user_id, payload.asset_id)
    metadata={}
    role=payload.role
    if payload.import_info:
        from app.agents.material_import import assignment
        inferred,group,origin=assignment(payload.import_info)
        role=payload.role if payload.role!='reference' else inferred
        metadata={'import_info':payload.import_info.model_dump(mode='json'),'garment_key':group,'role_origin':origin}
    current = await attachments(db, conv)
    prior = next((a for a in current if a["asset_id"] == item.id and not a["submitted"]), None)
    if prior:
        message = await db.get(HermesMessage, prior["id"])
        message.metadata_json = {**{k:v for k,v in message.metadata_json.items() if k not in ('inferred_role','role_reason','role_analysis_job_id')}, "role": role,**metadata}
    else:
        if len(current) >= 500:
            raise AppError("agent.context_too_large", "当前会话素材已达上限。", 422)
        message = HermesMessage(conversation_id=conv.id, organization_id=conv.organization_id, user_id=conv.user_id,
            role="attachment", content=item.filename, metadata_json={"asset_id": item.id, "role": role, "submitted": False,**metadata},
            created_at=datetime.now(UTC))
        db.add(message)
    await db.flush()
    return next(a for a in await attachments(db, conv) if a["id"] == message.id)


async def detach(db, conv, attachment_id):
    item = await db.scalar(select(HermesMessage).where(HermesMessage.id == attachment_id,
        HermesMessage.conversation_id == conv.id, HermesMessage.role == "attachment"))
    if item is None:
        raise AppError("agent.asset_not_found", "附件不存在。", 404)
    if item.metadata_json.get("submitted"):
        raise AppError("agent.attachment_submitted", "已提交消息的图片不能移除；可在新消息中使用其他图片。", 409)
    await db.delete(item)
    await db.flush()


async def outputs(db, conv, run_ids=None):
    runs = list((await db.scalars(select(AgentRun).where(AgentRun.conversation_id == conv.id)
        .order_by(AgentRun.created_at, AgentRun.id))).all())
    slots = {s["job_id"]: s["number"] for r in runs for s in r.result_json.get("gallery_slots", [])}
    ids = [r.id for r in runs if run_ids is None or r.id in run_ids]
    rows = (await db.execute(select(GeneratedOutput, Asset, Job, AgentJobLink.run_id)
        .join(Asset, Asset.id == GeneratedOutput.asset_id).join(Job, Job.id == GeneratedOutput.job_id)
        .join(AgentJobLink, AgentJobLink.job_id == Job.id).where(AgentJobLink.run_id.in_(ids),
            GeneratedOutput.organization_id == conv.organization_id, GeneratedOutput.created_by == conv.user_id,
            Job.created_by == conv.user_id, Job.organization_id == conv.organization_id,
            Asset.created_by == conv.user_id, Asset.deleted_at.is_(None), GeneratedOutput.discarded_at.is_(None))
        .order_by(Job.created_at, Job.id, GeneratedOutput.sequence_number, GeneratedOutput.id))).all() if ids else []
    from app.models.tasks import BatchTryOnVersion
    job_ids=[job.id for _,_,job,_ in rows]
    versions={v.task_id:v for v in (await db.scalars(select(BatchTryOnVersion).where(BatchTryOnVersion.task_id.in_(job_ids),BatchTryOnVersion.organization_id==conv.organization_id))).all()} if job_ids else {}
    result = []
    for output, image, job, run_id in rows:
        meta = (job.input_json.get("metadata") or {}).get("agent_image", {})
        batch_meta=job.input_json.get('metadata') or {}
        review=versions.get(job.id)
        result.append({"id": output.id, "asset_id": image.id, "job_id": job.id, "run_id": run_id,
            'review_item_id':review.item_id if review else None,'review_version_id':review.id if review else None,
            'review_status':review.review_status if review else None,
            'batch_tryon':{k:batch_meta.get(k) for k in ('combination_id','template_asset_id','template_name','garment_id','garment_asset_id','garment_filename','effective_garment_reference_ids','agent_production_plan_id','export_filename')} if batch_meta.get('workflow')=='agent_chat_tryon' else None,
            'amazon_module':(job.input_json.get('metadata') or {}).get('amazon_module'),
            "number": slots.get(job.id), "sequence_number": output.sequence_number,
            "filename": image.filename, "width": image.width, "height": image.height, "size": image.size, "mime_type": image.mime_type,
            "content_url": f"/api/v1/assets/{image.id}/content", "download_url": f"/api/v1/assets/{image.id}/download",
            "parent_output_id": meta.get("parent_output_id"), "root_output_id": meta.get("root_output_id") or output.id,
            'source_asset_id':meta.get('source_asset_id'),'source_filename':meta.get('source_filename'),'source_index':meta.get('source_index'),
            "version": meta.get("version", 1)})
    return sorted(result, key=lambda o: (o["number"] or 10**9, o["sequence_number"], o["id"]))


async def context(db, conv):
    if conv.context_project_id:
        project = await db.scalar(select(Project).where(Project.id == conv.context_project_id,
            Project.organization_id == conv.organization_id, Project.created_by == conv.user_id, Project.deleted_at.is_(None))
            .with_for_update().execution_options(populate_existing=True))
        if project is None:
            raise AppError("agent.context_not_found", "会话关联项目已删除或不可访问。", 404)
    images = await attachments(db, conv)
    gallery = await outputs(db, conv)
    messages = list((await db.execute(select(HermesMessage.role, HermesMessage.content).where(
        HermesMessage.conversation_id == conv.id, HermesMessage.role.in_(["user", "assistant"]))
        .order_by(HermesMessage.created_at.desc(), HermesMessage.id.desc()).limit(8))).all())
    snapshot = {"project_id": conv.context_project_id, "name": conv.title, "context_kind": "chat",
        "conversation_id": conv.id, "assets": [{**a, "id": a["asset_id"], "attachment_id": a["id"]} for a in images],
        "outputs": gallery, "history": [{"role": m.role, "content": m.content[:2000]} for m in reversed(messages)]}
    # Message/progress changes must not invalidate an already confirmed immutable plan.
    signature = state_fingerprint({"assets": [{k: a[k] for k in ("asset_id", "role", "sha256")} for a in images],
        "project_id": conv.context_project_id})
    from app.agents.production import list_plans
    from app.agents import amazon, amazon_research
    from app.agents import batch_manifest
    manifest_row=await batch_manifest.record(db,conv)
    manifest=batch_manifest.snapshot(manifest_row,batch_manifest.BatchInputManifest.model_validate(manifest_row.metadata_json)) if manifest_row else None
    return {**snapshot, "signature": signature, "production_plans": await list_plans(db,conv),
        'batch_input_manifest':manifest,'amazon_plans':await amazon.list_plans(db,conv),'amazon_research':await amazon_research.receipts(db,conv)}


async def ensure_project(db, settings, conv, *, kind="listing"):
    # MySQL RR consistent reads can still see the pre-wait snapshot even after
    # another caller acquired/released an ORM instance. Use a current locking
    # read at the allocation site, retaining that instance through the update.
    conv = await db.scalar(select(HermesConversation).where(HermesConversation.id==conv.id,
        HermesConversation.organization_id==conv.organization_id, HermesConversation.user_id==conv.user_id)
        .with_for_update().execution_options(populate_existing=True))
    if conv.context_project_id:
        project = await db.scalar(select(Project).where(Project.id == conv.context_project_id,
            Project.organization_id == conv.organization_id, Project.created_by == conv.user_id, Project.deleted_at.is_(None))
            .with_for_update().execution_options(populate_existing=True))
        if project is None or (project.project_type != kind and not (kind == "listing" and project.project_type == "batch_tryon")):
            raise AppError("agent.project_kind_conflict", "当前会话已关联其他类型项目，请新建对话。", 409)
        return project
    project = await project_service.create_project(db, settings, organization_id=conv.organization_id,
        user_id=conv.user_id, project_type=kind, name=conv.title[:160], description="AI 对话工作台", draft={})
    conv.context_project_id = project.id
    await db.flush()
    return project


def image_confirmation_context(context, plan):
    """Bind approval to these images, not unrelated conversation uploads/jobs.

    The plan already binds prompt, model, count and explicit parent. An automatically
    allocated backing project is not an input change. Owner and project access are
    still checked by context()/generate() at execution time.
    """
    references = {aid for action in plan['actions'] if action['tool']=='generate_chat_images'
        for aid in action['arguments'].get('reference_asset_ids', [])}
    parents = {action['arguments'].get('parent_output_id') for action in plan['actions']
        if action['tool']=='generate_chat_images'} - {None}
    assets = {(a['asset_id'],a['role'],a['sha256']):{k:a[k] for k in ('asset_id','role','sha256')}
        for a in context['assets'] if a['asset_id'] in references}
    return state_fingerprint({
        'conversation_id':context['conversation_id'],
        'references':sorted(references),
        'assets':[assets[key] for key in sorted(assets)],
        'parents':[{k:o[k] for k in ('id','asset_id','root_output_id','version')}
            for o in context['outputs'] if o['id'] in parents],
    })


def analysis_confirmation_context(context, plan):
    """Bind an understanding Job to its exact inputs, not later appended imports.

    A referenced image's identity, role, grouping, enabled state and bytes remain
    protected. Unrelated uploads and harmless analysis/progress updates are not
    permission to change this plan, and do not invalidate its immutable inputs.
    """
    references = {aid for action in plan['actions'] if action['tool']=='analyze_chat_assets'
                  for aid in action['arguments'].get('asset_ids', [])}
    entries = {e['asset_id']: e for e in (context.get('batch_input_manifest') or {}).get('entries', [])}
    return state_fingerprint({
        'conversation_id': context['conversation_id'], 'references': sorted(references),
        'assets': sorted(({'asset_id': a['asset_id'], 'role': a['role'], 'sha256': a['sha256'],
            'assignment': {k: entries[a['asset_id']].get(k) for k in ('role','garment_key','manual','enabled')}
                          if a['asset_id'] in entries else None}
            for a in context['assets'] if a['asset_id'] in references), key=lambda a:a['asset_id']),
    })


async def quote(db, org, action):
    return (await estimate_response(db, organization_id=org, operation_code="listing.generate", quantity=action.count,
        factors={"model": action.model_code, "resource_pool": "platform"})).model_dump(mode="json")


def independent_edit_prompt(prompt,index,total):
    # The planner describes the batch; each provider call sees only one source.
    # Normalize operational image counts, never garment numbers/print contents.
    prompt=re.sub(r'(?:[0-9]+|[一二三四五六七八九十两]+)张(?=(?:上传)?(?:原图|图片|图像))','1张',prompt)
    boundary=('本次是单张原图的独立图片编辑，只提供1张原图，只输出1张完整独立结果。'
        '下文的批量或分别处理描述不是当前请求的输出数量，禁止拼图、复制主体或生成其他原图的结果。'
        '仅编辑这张原图的指定部分，保留原有主体数量；原图没有人物时不得新增人物。\n')
    return boundary+prompt+'\n最终交付：仅返回当前原图编辑后的1张图片，不拼图，不输出多张。'


async def generate(db, settings, conv, action, key):
    # Verify a concrete parent binding again; do not trust arbitrary IDs in tool JSON.
    parent = None
    if action.parent_output_id:
        parent = next((o for o in await outputs(db, conv) if o["id"] == action.parent_output_id), None)
        if parent is None or action.parent_asset_id != parent["asset_id"] or action.root_output_id != parent["root_output_id"]:
            raise AppError("agent.output_not_found", "待编辑图片不属于当前对话。", 404)
        if not action.reference_asset_ids or action.reference_asset_ids[0] != parent["asset_id"]:
            raise AppError("agent.edit_source_mismatch", "编辑底图必须是指定结果，不能自动替换。", 409)
    independent=action.capability=='image_edit' and len(action.reference_asset_ids)>1
    if independent and action.count!=len(action.reference_asset_ids):
        raise AppError('agent.edit_source_mismatch','独立编辑必须为每张原图提交一个任务。',409)
    reference_assets={}
    for aid in action.reference_asset_ids:
        reference_assets[aid]=await asset(db, conv.organization_id, conv.user_id, aid)
    budget = await quote(db, conv.organization_id, action)
    if not budget["sufficient"]:
        raise AppError("agent.insufficient_budget", "当前可用额度不足，未提交图片任务。", 409)
    project = await ensure_project(db, settings, conv)
    for i, aid in enumerate(action.reference_asset_ids):
        existing = await db.scalar(select(ProjectAsset.id).where(ProjectAsset.project_id == project.id,
            ProjectAsset.asset_id == aid, ProjectAsset.role == "product_reference"))
        if not existing:
            await project_service.link_asset(db, organization_id=conv.organization_id, project_id=project.id,
                asset_id=aid, role="product_reference", sort_order=i, user_id=conv.user_id,
                display_name=None, is_default=False)
    # Same provider/worker/billing, one result per original Job. No custom dispatcher.
    items=[]
    for i in range(action.count):
        refs=[action.reference_asset_ids[i]] if independent else action.reference_asset_ids
        source=reference_assets[refs[0]] if len(refs)==1 else None
        preserve_size=independent or bool(parent and parent.get('source_index') is not None)
        size=f'{source.width}x{source.height}' if preserve_size and source and source.width and source.height else '1024x1024'
        image_meta={'conversation_id':conv.id,'parent_output_id':action.parent_output_id,
            'root_output_id':action.root_output_id,'version':parent['version']+1 if parent else 1,
            'source_asset_id':(parent.get('source_asset_id') or parent['asset_id']) if parent else source.id if source else None,
            'source_filename':(parent.get('source_filename') or parent['filename']) if parent else source.filename if source else None,
            'source_index':parent.get('source_index') if parent else i+1 if independent else 1 if source else None}
        items.append(BatchJobItemRequest(client_item_id=f'chat-{i+1:03}',
            prompt=independent_edit_prompt(action.prompt,i,action.count) if independent else action.prompt,
            reference_asset_ids=refs,size=size,metadata={'workflow':'agent_chat','dsh_native':conv.controller_type=='dsh','agent_image':image_meta}))
    payload = JobBatchSubmitRequest(name=conv.title[:160], workspace_type="listing", operation_code="listing.generate",
        capability=action.capability, model_code=action.model_code, idempotency_key=key, project_id=project.id,
        concurrency=action.count if independent else min(action.count, 2),items=items)
    batch, jobs, _ = await submit_batch(db, settings.model_copy(update={"job_max_attempts": 1}),
        organization_id=conv.organization_id, user_id=conv.user_id, payload=payload)
    return {"batch_id": batch.id, "project_id": project.id, "job_ids": [j.id for j in jobs]}


async def prepare_tryon(db, settings, conv, action):
    project = await ensure_project(db, settings, conv, kind="batch_tryon")
    for role, ids in (("model_template", action.template_asset_ids), ("garment", action.garment_asset_ids)):
        for index, aid in enumerate(ids):
            await asset(db, conv.organization_id, conv.user_id, aid)
            if not await db.scalar(select(ProjectAsset.id).where(ProjectAsset.project_id == project.id,
                    ProjectAsset.asset_id == aid, ProjectAsset.role == role)):
                await project_service.link_asset(db, organization_id=conv.organization_id, project_id=project.id,
                    asset_id=aid, role=role, sort_order=index, user_id=conv.user_id, display_name=None, is_default=index == 0)
    return {"project_id": project.id, "workspace_url": f"/workspaces/batch-tryon?project_id={project.id}",
        "combination_count": len(action.template_asset_ids)*len(action.garment_asset_ids),
        "message": "素材已关联原工作台；还需在原样图流程完成分析、样图验证，未提交正式生产。"}
