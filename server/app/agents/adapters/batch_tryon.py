"""A narrow facade over the production B path. No dispatch, pool or billing fork."""
from dataclasses import asdict

from sqlalchemy import select

from app.core.errors import AppError
from app.models.content import Asset, Project, ProjectAsset
from app.models.tasks import Job, JobBatch, BatchTryOnReviewItem, BatchTryOnVersion
from app.agents.contracts import MessageCreate
from app.schemas.batch_tryon_workflow import BatchTryOnWorkflowCreateRequest
from app.services.batch_tryon_access_service import require_batch_asset_access
from app.services import batch_tryon_workflow_service as workflows
from app.services.batch_tryon_prompt_service import build_template_prompt_composed_prompt
from app.services.proposal_confirmation_service import state_fingerprint


def digest(value):
    return state_fingerprint(value)


async def owned_project(db, org, user, project_id):
    row = await db.scalar(select(Project).where(
        Project.id == project_id, Project.organization_id == org,
        Project.created_by == user, Project.deleted_at.is_(None),
    ))
    if row is None:
        raise AppError("agent.context_not_found", "项目不存在或无权访问。", 404)
    return row


async def read_context(db, org, user, project_id):
    project = await owned_project(db, org, user, project_id)
    if project.project_type != "batch_tryon":
        raise AppError("agent.context_invalid", "第一阶段总控仅接入批量套图项目；其他工作台保持原入口。", 422)
    # Do not duplicate potentially megabyte-sized crop/erase metadata into the
    # graph, plan or browser. The immutable reference Asset + hash is sufficient.
    rows = (await db.execute(select(
        Asset.id.label("id"), Asset.filename.label("filename"), Asset.sha256.label("sha256"),
        Asset.width.label("width"), Asset.height.label("height"), Asset.source_asset_id.label("source_asset_id"),
        Asset.created_by.label("owner"), Asset.updated_at.label("updated_at"),
        ProjectAsset.role.label("role"), ProjectAsset.display_name.label("name"),
    ).join(ProjectAsset, ProjectAsset.asset_id == Asset.id).where(
        ProjectAsset.project_id == project.id, ProjectAsset.organization_id == org,
        Asset.organization_id == org, Asset.deleted_at.is_(None),
        ProjectAsset.role.in_({"model_template", "garment", "font_reference",
            "garment_reference.front", "garment_reference.back", "garment_reference.detail"}),
    ).order_by(ProjectAsset.sort_order, ProjectAsset.id).limit(501))).mappings().all()
    if len(rows) > 500:
        raise AppError("agent.context_too_large", "当前项目参考素材较多，请先在原工作台选择或拆分批次；总控不会静默截断素材。", 422)
    assets = []
    for row in rows:
        # Explicit shared-library publication remains governed by the old asset service.
        if row["owner"] != user:
            await require_batch_asset_access(db, organization_id=org, user_id=user, asset_ids=[row["id"]])
        assets.append({"id": row["id"], "filename": row["filename"], "name": row["name"] or row["filename"],
                       "role": row["role"], "sha256": row["sha256"], "width": row["width"], "height": row["height"],
                       "source_asset_id": row["source_asset_id"], "updated_at": row["updated_at"].isoformat(),
                       "content_url": f"/api/v1/assets/{row['id']}/content"})
    snapshot = {"project_id": project.id, "name": project.name, "project_type": project.project_type,
                "updated_at": project.updated_at.isoformat(), "assets": assets}
    return {**snapshot, "signature": digest(snapshot)}


def build_workflow(context, selection, *, action_key, analysis=False):
    selection = MessageCreate.model_validate(selection)
    by_id = {a["id"]: a for a in context["assets"]}
    templates = list(dict.fromkeys(selection.template_asset_ids))
    garments = list(dict.fromkeys(selection.garment_asset_ids))
    if not templates or not garments:
        raise AppError("agent.selection_required", "请先选择模板图和服装原图。", 422)
    for ids, role in ((templates, "model_template"), (garments, "garment")):
        if any(i not in by_id or by_id[i]["role"] != role for i in ids):
            raise AppError("agent.invalid_selection", "选择的素材不属于当前项目或素材角色不符。", 404)
    if not selection.prompt.strip():
        raise AppError("agent.prompt_required", "请填写已确认的提示词；总控不会擅自选择或拼接预设。", 422)
    if selection.prompt_kind != ("analysis" if analysis else "final"):
        raise AppError("agent.prompt_kind_mismatch", "请明确区分最终换衣提示词和 Luna 分析指令，再提交对应操作。", 422)
    if any(a["role"] == "font_reference" for a in context["assets"]):
        raise AppError("agent.font_context_required", "此项目包含图C字体参考。第一阶段尚未导入工作台的组合字体绑定，请使用原工作台提交，避免遗漏图C。", 409)
    garment_rows = []
    for index, aid in enumerate(garments):
        derived = {a["role"].split(".", 1)[-1]: a["id"] for a in context["assets"]
                   if a["source_asset_id"] == aid and a["role"].startswith("garment_reference.")}
        garment_rows.append({"garment_id": aid, "asset_id": aid, "filename": by_id[aid]["filename"], "order": index,
                             **{f"{view}_reference_asset_id": derived.get(view) for view in ("front", "back", "detail")}})
    payload = BatchTryOnWorkflowCreateRequest(
        project_id=context["project_id"], name=f"AI 总控 · {context['name']}"[:160],
        idempotency_key=action_key, prompt_mode="ai_detailed" if analysis else "direct",
        submission_kind="validation" if analysis else "production",
        templates=[{"template_id": aid, "asset_id": aid, "name": by_id[aid]["name"], "order": i,
                    "template_type": selection.template_type, "prompt_source": "custom",
                    "analysis_prompt": selection.prompt, "prompt_strategy": "luna_per_image" if analysis else "preset",
                    "garment_view": selection.garment_view} for i, aid in enumerate(templates)],
        garments=garment_rows,
    )
    workflows._validate_explicit_garment_references(payload)
    return payload


async def verify_workflow(db, org, user, payload):
    ids = [t.asset_id for t in payload.templates]
    ids.extend(v for g in payload.garments for v in (g.asset_id, g.font_reference_asset_id,
               g.front_reference_asset_id, g.back_reference_asset_id, g.detail_reference_asset_id) if v)
    ids.extend(c.font_reference_asset_id for c in payload.combinations or [] if c.font_reference_asset_id)
    await require_batch_asset_access(db, organization_id=org, user_id=user, asset_ids=ids)
    await workflows._validate_inputs(db, organization_id=org, user_id=user, payload=payload)


async def submit_workflow(db, settings, org, user, payload, action_key, *, analysis_only=False):
    # New Agent submissions never automatically reissue an unknown paid request.
    # This does not change retry policy of existing/manual B jobs.
    settings = settings.model_copy(update={"job_max_attempts": 1})
    payload = payload.model_copy(update={"idempotency_key": action_key})
    if analysis_only:
        payload = payload.model_copy(update={"prompt_mode": "ai_detailed", "submission_kind": "validation"})
    elif payload.prompt_mode != "direct":
        raise AppError("agent.confirmation_required", "第一阶段生图提交仅接受已确认的直接提示词，分析请单独确认。", 409)
    await verify_workflow(db, org, user, payload)
    root, analysis_jobs, _ = await workflows.create_batch_tryon_workflow(
        db, settings, organization_id=org, user_id=user, payload=payload)
    if analysis_only:
        return {"workflow_id": root.id, "job_ids": [j.id for j in analysis_jobs], "batch_id": None}
    batch, jobs, _ = await workflows.submit_confirmed_batch_tryon_workflow(
        db, settings, organization_id=org, user_id=user, workflow_job_id=root.id,
        idempotency_key=f"{action_key}:images")
    # Existing durable Job rows + dispatcher publish after transaction commit.
    return {"workflow_id": root.id, "batch_id": batch.id, "job_ids": [j.id for j in jobs]}


async def read_jobs(db, org, user, ids):
    rows = list((await db.scalars(select(Job).where(Job.id.in_(set(ids)), Job.organization_id == org,
                                                  Job.created_by == user))).all())
    if len(rows) != len(set(ids)):
        raise AppError("agent.job_not_found", "任务不存在或无权访问。", 404)
    from app.models.tasks import JobAttempt
    failed=[j.id for j in rows if j.status=='failed']
    attempts=(await db.scalars(select(JobAttempt).where(JobAttempt.job_id.in_(failed),JobAttempt.organization_id==org)
        .order_by(JobAttempt.attempt_number.desc()))).all() if failed else []
    latest={}
    for attempt in attempts:latest.setdefault(attempt.job_id,attempt)
    result=[]
    for j in rows:
        a=latest.get(j.id)
        unknown=j.status=='failed' and (getattr(a,'http_status',None) in (408,504,524)
            or any(w in str(j.error_code)+' '+str(getattr(a,'error_code','')) for w in ('timeout','network','remote_unknown')))
        meta=(j.input_json or {}).get('metadata') or {}
        module=meta.get('amazon_module') or {}
        label=(module.get('module_snapshot') or {}).get('title') or meta.get('garment_filename') or (meta.get('agent_image') or {}).get('source_filename')
        # Only owner-scoped display metadata. Job.progress is a local processing
        # stage, NOT a Provider's true percentage and is never promoted as one.
        result.append({'id':j.id,'status':j.status,'progress':j.progress,'batch_id':j.batch_id,'capability':j.capability,
            'error_code':j.error_code,'upstream_unknown':unknown,'label':str(label or '图片')[:120],
            'image_kind':'aplus' if j.operation_code=='aplus.generate' else 'listing' if meta.get('workflow')=='agent_aplus' else 'image',
            'can_retry':bool(j.status=='failed' and not unknown and not (j.result_json or {}).get('outputs') and meta.get('workflow') in {'agent_aplus','agent_chat'})})
    return result


def compile_prompt(payload):
    return {"prompts": [{"template_id": t.template_id, "garment_id": g.garment_id,
                         **asdict(build_template_prompt_composed_prompt(
                             template_type=t.template_type, reusable_final_prompt=t.analysis_prompt,
                             garment_filename=g.filename, template_name=t.name,
                             direct_output=True, has_font_reference=bool(g.font_reference_asset_id),
                             garment_reference_count=len(workflows._job_reference_snapshot(template=t, garment=g,
                                 font_reference_asset_id=g.font_reference_asset_id)[1]["effective_garment_reference_asset_ids"]),
                         ))} for t in payload.templates for g in payload.garments]}


async def approve(db, org, user, item_id, version_id):
    from app.services.batch_tryon_review_service import approve_version
    item = await db.scalar(select(BatchTryOnReviewItem).join(JobBatch, JobBatch.id == BatchTryOnReviewItem.batch_id).where(
        BatchTryOnReviewItem.id == item_id, BatchTryOnReviewItem.organization_id == org, JobBatch.created_by == user))
    if item is None:
        raise AppError("agent.item_not_found", "审核对象不存在或无权访问。", 404)
    await approve_version(db, organization_id=org, item_id=item_id, version_id=version_id, user_id=user)
    return {"item_id": item_id, "version_id": version_id, "review_status": "approved"}
