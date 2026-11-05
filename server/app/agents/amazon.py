"""Amazon chat briefs over existing messages, projects and A+ jobs. No extra engine."""
from datetime import datetime, timezone
import json
import re
from pathlib import Path
from sqlalchemy import select
from app.core.errors import AppError
from app.agents.amazon_contracts import APlusPlan, GenerateAPlus
from app.agents.capabilities.registry import digest
from app.agents.adapters import chat
from app.models.hermes_agent import HermesMessage
from app.models.content import Project
from app.schemas.tasks import JobBatchSubmitRequest, BatchJobItemRequest
from app.services import project_service
from app.services.billing_service import estimate_response
from app.services.resource_pool_service import resolve_operation_model_code
from app.services.task_service import submit_batch


def rules():
    return json.loads(Path(__file__).with_name('amazon_rules.json').read_text(encoding='utf-8'))


def visual_rules():
    return json.loads(Path(__file__).with_name('company_visual_rules.json').read_text(encoding='utf-8'))


def module_spec(plan, module):
    if plan.deliverable == 'listing':
        spec = dict(visual_rules()['listing_spec'])
        spec.update(width=module.requested_width or spec['width'], height=module.requested_height or spec['height'])
        return spec
    spec=rules()['modules'].get(module.spec_id)
    if spec and plan.design_version=='professional-aplus-v2' and spec.get('mobile_width') and not spec.get('slots'):
        return {**spec,'slots':[{'id':'desktop','width':spec['width'],'height':spec['height'],'field':'desktopImage'},
            {'id':'mobile','width':spec['mobile_width'],'height':spec['mobile_height'],'field':'mobileImage'}]}
    return spec


def direct_generation_requested(text):
    from app.agents.execution_policy import wants_review
    if wants_review(text or '') or re.search(r'(?:不要|先不|暂不|别|不想).{0,5}(?:生成|生产)|先.{0,5}(?:出|给).{0,3}方案',text or ''):return False
    return bool(re.search(r'直接(?:整套|全部|并发)?生成|(?:不用|无需|不需要)(?:再|任何|额外)?确认(?!费用|额度|成本|模型)|不用审核|全部做|直接生产', text or ''))


def requested_revision_ids(text, plan):
    from app.agents.intent_router import number
    ordinals=re.findall(r'第\s*([0-9一二三四五六七八九十两]+)\s*(?:张|个|幅)',text or '')
    ids=[]
    for value in ordinals:
        index=number(value)-1
        if not 0<=index<len(plan.modules):
            raise AppError('agent.module_missing','指定图片序号超出当前方案范围。',422)
        ids.append(plan.modules[index].id)
    return set(ids)


def findings(plan):
    cfg = rules()
    errors = []
    evidence = {e.id:e for e in plan.insight.evidence}
    if plan.rules_version not in [cfg['version'],*cfg.get('compatible_versions',[])]: errors.append('规格版本已变化，请重新核对。')
    if plan.deliverable == 'aplus' and len(plan.modules) > cfg['max_modules'][plan.aplus_type]: errors.append('模块数量超过当前A+类型规则。')
    for m in plan.modules:
        spec = module_spec(plan, m)
        if not spec or spec['type'] != (plan.aplus_type if plan.deliverable == 'aplus' else 'listing'): errors.append(f'{m.id}: 模块规格未审核或不匹配。')
        if plan.deliverable == 'listing' and not m.design_direction:
            errors.append(f'{m.id}: 请指定公司视觉设计方向。')
        for field in ('headline','body'):
            limit=(spec or {}).get(field+'_max')
            if limit and len(getattr(m,field))>limit:errors.append(f'{m.id}: {field}超过官方模块{limit}字符限制。')
        line_limit=(spec or {}).get('body_lines_max')
        if line_limit and len(m.body.splitlines())>line_limit:
            errors.append(f'{m.id}: 正文超过官方模块{line_limit}行限制。')
        if any(e not in evidence or evidence[e].scope != 'own_product' or evidence[e].status != 'fact' for e in m.evidence_ids):
            errors.append(f'{m.id}: 正式卖点必须引用我方商品事实，不能引用竞品或假设。')
        copy = '\n'.join([m.headline, m.body, m.main_point])
        if any(re.search(p, copy) for p in cfg['forbidden_copy_patterns']): errors.append(f'{m.id}: 文案含禁止或需要移除的促销/承诺/比较。')
        for slot in m.image_slots:
            if any(re.search(pattern,slot.headline+'\n'+slot.body) for pattern in cfg['forbidden_copy_patterns']):errors.append(f'{m.id}/{slot.id}: 槽位文案含禁止内容。')
    if plan.design_version=='professional-aplus-v2':
        from app.agents.aplus_design import quality
        errors.extend(quality(plan,complete=False)['errors'])
    return errors


def module_signature(plan, module):
    data=module.model_dump(mode='json')
    for key in ('design_direction','requested_width','requested_height'):
        if data[key] is None:data.pop(key)
    if not module.design_principles and not module.art_direction and not module.image_slots:
        for key in ('design_principles','art_direction','image_slots'):data.pop(key,None)
    value={'module':data,'identity':plan.product_identity_lock,
        'style':plan.campaign_style_lock,'rules':plan.rules_version,'marketplace':plan.marketplace,
        'evidence':[e.model_dump(mode='json') for e in plan.insight.evidence if e.id in module.evidence_ids]}
    if plan.deliverable!='aplus':value['deliverable']=plan.deliverable
    return digest(value)


async def record(db, conv, plan_id, lock=False):
    q=select(HermesMessage).where(HermesMessage.id==plan_id,HermesMessage.conversation_id==conv.id,
        HermesMessage.organization_id==conv.organization_id,HermesMessage.user_id==conv.user_id,HermesMessage.role=='amazon_plan')
    if lock:q=q.with_for_update().execution_options(populate_existing=True)
    row=await db.scalar(q)
    if row is None:raise AppError('agent.amazon_plan_missing','A+方案不存在或无权访问。',404)
    return row, APlusPlan.model_validate(row.metadata_json['plan'])


def response(row):
    p=APlusPlan.model_validate(row.metadata_json['plan'])
    return {'id':row.id,**row.metadata_json,'findings':findings(p),'manual_checks':rules()['manual_checks'],
        'module_specs':{m.id:module_spec(p,m) for m in p.modules}}


async def list_plans(db, conv):
    rows=(await db.scalars(select(HermesMessage).where(HermesMessage.conversation_id==conv.id,
        HermesMessage.organization_id==conv.organization_id,HermesMessage.user_id==conv.user_id,
        HermesMessage.role=='amazon_plan').order_by(HermesMessage.created_at.desc()).limit(20))).all()
    from app.models.tasks import Job
    result=[]
    for row in rows:
        ids=[jid for s in row.metadata_json.get('submissions',[]) for jid in s.get('job_ids',[])]
        jobs=(await db.scalars(select(Job).where(Job.id.in_(ids[-300:]),Job.organization_id==conv.organization_id,
            Job.created_by==conv.user_id))).all() if ids else []
        result.append({**response(row),'module_jobs':[{'job_id':j.id,'status':j.status,'error_code':j.error_code,
            'module_id':(j.input_json.get('metadata') or {}).get('amazon_module',{}).get('module_id'),
            'slot_id':(j.input_json.get('metadata') or {}).get('amazon_module',{}).get('slot_id','main')} for j in jobs]})
    return result


async def check_assets(db, conv, plan):
    known={a['asset_id'] for a in await chat.attachments(db,conv)} | {o['asset_id'] for o in await chat.outputs(db,conv)}
    for aid in {aid for m in plan.modules for aid in [*m.reference_asset_ids,*[a for s in m.image_slots for a in (s.reference_asset_ids or [])]]}:
        if aid not in known:raise AppError('agent.context_mismatch','A+只能引用当前会话已授权素材。',403)
        await chat.asset(db,conv.organization_id,conv.user_id,aid)


async def save(db, conv, plan, key):
    await check_assets(db,conv,plan)
    rows=await list_plans(db,conv)
    prior=next((r for r in rows if r.get('request_key')==key),None)
    if prior:return {'amazon_plan_id':prior['id']}
    row=HermesMessage(conversation_id=conv.id,organization_id=conv.organization_id,user_id=conv.user_id,
        role='amazon_plan',content='Amazon图片方案',metadata_json={'schema_version':1,'revision':1,
        'plan':plan.model_dump(mode='json'),'approvals':{},'submissions':[],'project_id':None,'request_key':key},
        created_at=datetime.now(timezone.utc))
    db.add(row);await db.flush()
    return {'amazon_plan_id':row.id,'findings':findings(plan),'message':'草稿已保存，尚未确认或生成。'}


async def revise(db, conv, args):
    from app.agents.amazon_contracts import ModuleRevisions
    return await revise_many(db, conv, ModuleRevisions(plan_id=args.plan_id,
        expected_revision=args.expected_revision, modules=[args.module]))


async def revise_many(db, conv, args):
    row,p=await record(db,conv,args.plan_id,True)
    data=dict(row.metadata_json)
    if data['revision']!=args.expected_revision:raise AppError('agent.revision_conflict','方案已更新，请刷新后修改。',409)
    changed={m.id:m for m in args.modules}
    if set(changed)-{m.id for m in p.modules}:raise AppError('agent.module_missing','指定模块不存在。',404)
    p.modules=[changed.get(m.id,m) for m in p.modules]
    await check_assets(db,conv,p)
    approvals={k:v for k,v in data['approvals'].items() if k not in changed}
    row.metadata_json={**data,'revision':data['revision']+1,'plan':p.model_dump(mode='json'),'approvals':approvals}
    await db.flush();return response(row)


async def approve(db, conv, plan_id, args):
    row,p=await record(db,conv,plan_id,True);data=dict(row.metadata_json)
    if data['revision']!=args.expected_revision:raise AppError('agent.revision_conflict','方案已变化。',409)
    if not args.commercial_rights_confirmed:raise AppError('agent.rights_unconfirmed','请确认素材商业使用权及标识授权。',422)
    if findings(p):raise AppError('agent.aplus_validation','请先解决方案中的证据或规格问题。',422)
    selected=[m for m in p.modules if m.id in args.module_ids]
    if len(selected)!=len(set(args.module_ids)):raise AppError('agent.module_missing','模块不存在。',404)
    required={e for m in selected for e in m.evidence_ids}
    if required-set(args.verified_evidence_ids):raise AppError('agent.evidence_unconfirmed','请逐项确认本商品事实，不得用竞品性能代替。',422)
    approvals=dict(data['approvals'])
    for m in selected:approvals[m.id]={'signature':module_signature(p,m),'by':conv.user_id,
        'at':datetime.now(timezone.utc).isoformat(),'evidence_ids':m.evidence_ids,'rights_confirmed':True}
    row.metadata_json={**data,'approvals':approvals};await db.flush();return response(row)


async def image_quote(db, conv, args, *, require_approval=True):
    row,p=await record(db,conv,args.plan_id)
    if row.metadata_json['revision']!=args.expected_revision:raise AppError('agent.revision_conflict','方案版本已更新。',409)
    selected=[m for m in p.modules if m.id in args.module_ids]
    if len(selected)!=len(set(args.module_ids)):raise AppError('agent.module_missing','模块不存在。',404)
    if findings(p):raise AppError('agent.aplus_validation','方案存在未解决的校验问题。',422)
    for m in selected:
        if require_approval and row.metadata_json['approvals'].get(m.id,{}).get('signature')!=module_signature(p,m):
            raise AppError('agent.module_unconfirmed','模块尚未由运营确认，不能提交生图。',409)
    await check_assets(db,conv,p)
    operation='listing.generate' if p.deliverable=='listing' else 'aplus.generate'
    model=await resolve_operation_model_code(db,organization_id=conv.organization_id,operation_code=operation,
        capability='image_edit',additional_capabilities={'multi_image_reference'})
    pending,_=await _slot_work(db,p,row.metadata_json,args)
    budget=(await estimate_response(db,organization_id=conv.organization_id,operation_code=operation,
        quantity=max(1,len(pending)),factors={'model':model,'resource_pool':'platform'})).model_dump(mode='json')
    return {**budget,'model_code':model,'quantity':len(pending)}


async def authorize_review(db, conv, args, *, source):
    """Called only by the server's signed user review/direct-request boundary, never a model Tool."""
    row,p=await record(db,conv,args.plan_id,True)
    if row.metadata_json['revision']!=args.expected_revision:
        raise AppError('agent.revision_conflict','方案已更新，请查看新方案。',409)
    if findings(p):raise AppError('agent.aplus_validation','方案仍存在事实或规格问题。',422)
    approvals=dict(row.metadata_json['approvals'])
    for m in p.modules:
        if m.id in args.module_ids:
            approvals[m.id]={'signature':module_signature(p,m),'by':conv.user_id,
                'at':datetime.now(timezone.utc).isoformat(),'source':source,
                'evidence_ids':m.evidence_ids,'rights_confirmed':False}
    row.metadata_json={**row.metadata_json,'approvals':approvals}
    await db.flush()


async def _slot_work(db,plan,data,args):
    """Resolve actual image slots against original submissions; no writes/dispatch."""
    from app.agents.aplus_design import slots
    from app.models.tasks import Job
    from app.agents.samples import upstream_unknown
    latest={}
    for submission in data.get('submissions',[]):
        mids=submission.get('module_ids',[]);jids=submission.get('job_ids',[])
        sids=submission.get('slot_ids') or ['main']*len(jids)
        for mid,jid,sid in zip(mids,jids,sids):
            sigs=submission.get('module_signatures',{})
            latest[(mid,sid)]=(jid,sigs.get(mid+'::'+sid,sigs.get(mid)))
    pending=[];reused={}
    for module in plan.modules:
        if module.id not in args.module_ids:continue
        signature=module_signature(plan,module)
        for slot in slots(plan,module):
            pair=(module.id,slot['id']);prior=latest.get(pair)
            job=await db.get(Job,prior[0]) if prior else None
            same=prior and prior[1]==signature
            if same and job and not (job.status=='failed' and args.retry_failed):
                reused[pair]=job;continue
            if job:
                if job.status not in {'succeeded','failed','cancelled'}:
                    raise AppError('agent.module_running','对应槽位仍在生成，请等待原任务完成。',409)
                if job.status=='failed' and await upstream_unknown(db,job):
                    raise AppError('agent.remote_unknown','前次上游结果未知，不能通过重试或修改Prompt重复提交。',409)
            pending.append((module,slot))
    return pending,reused


async def generate(db, settings, conv, args, key):
    row,p=await record(db,conv,args.plan_id,True)
    budget=await image_quote(db,conv,args)
    if not budget['sufficient']:raise AppError('agent.insufficient_budget','额度不足。',409)
    data=dict(row.metadata_json)
    prior=next((s for s in data['submissions'] if s['request_key']==key),None)
    if prior:return {**prior,'amazon_plan_id':row.id,'project_id':data['project_id']}
    pending,reused=await _slot_work(db,p,data,args)
    if not pending and reused:
        jobs=list(reused.values())
        return {'amazon_plan_id':row.id,'project_id':data['project_id'],'batch_id':jobs[0].batch_id,
            'job_ids':[j.id for j in jobs],'module_ids':[pair[0] for pair in reused],
            'slot_ids':[pair[1] for pair in reused],'reused':True}
    if not pending:raise AppError('agent.module_missing','没有可生成的模块图片槽位。',422)
    if data['project_id']:
        project=await project_service.get_project(db,conv.organization_id,data['project_id'],owner_user_id=conv.user_id)
    else:
        project=await project_service.create_project(db,settings,organization_id=conv.organization_id,user_id=conv.user_id,
            project_type='listing' if p.deliverable=='listing' else 'aplus',name=f'Amazon · {conv.title}'[:160],
            description='AI总控运营方案',draft={'amazon_plan_id':row.id,'plan':p.model_dump(mode='json')})
    gallery=await chat.outputs(db,conv)
    from app.agents import professional_prompts,experience
    remembered=await experience.recall(db,conv,experience.MemoryQuery(product_type=experience.scope(p.product_identity_lock),
        scenario='listing_images' if p.deliverable=='listing' else 'amazon_aplus'))
    items=[]
    for m,slot in pending:
        old=[o for o in gallery if (o.get('amazon_module') or {}).get('plan_id')==row.id
            and o['amazon_module'].get('module_id')==m.id and o['amazon_module'].get('slot_id','main')==slot['id']]
        parent=max(old,key=lambda o:o['version']) if old else None
        spec=slot['spec'];direction=slot['direction']
        prompt=professional_prompts.aplus(p,m,editing=bool(parent),slot=slot)
        preferences=experience.prompt_rules(remembered,m.composition+' '+m.image_prompt)
        if preferences:prompt+='\nPRIVATE STYLE PREFERENCES (subordinate to this brief and product truth): '+'; '.join(v['instruction'] for v in preferences)
        refs=list(dict.fromkeys(([parent['asset_id']] if parent else [])+(direction.reference_asset_ids or m.reference_asset_ids)))
        legacy=not m.image_slots and not (module_spec(p,m) or {}).get('slots')
        item_id=m.id if legacy else m.id+'::'+slot['id']
        items.append(BatchJobItemRequest(client_item_id=item_id,prompt=prompt,reference_asset_ids=refs,
            size=f"{spec['width']}x{spec['height']}",requested_width=spec['width'],requested_height=spec['height'],quality='high',metadata={
                'workflow':'agent_aplus','effective_prompt_snapshot':prompt,'prompt_recipe_version':professional_prompts.VERSION,
                'personal_preference_versions':[{'id':v['id'],'revision':v['revision']} for v in preferences],
                'amazon_module':{'plan_id':row.id,'module_id':m.id,'slot_id':slot['id'],'slot_snapshot':direction.model_dump(mode='json'),
                    'plan_revision':data['revision'],'module_snapshot':m.model_dump(mode='json'),'rules_version':p.rules_version,'spec_snapshot':spec,
                    'design_trace':{'skills':data.get('skill_trace',[]),'principles':m.design_principles,
                        'art_direction':m.art_direction.model_dump() if m.art_direction else None}},
                'agent_image':{'conversation_id':conv.id,'parent_output_id':parent['id'] if parent else None,
                    'root_output_id':parent['root_output_id'] if parent else None,'version':parent['version']+1 if parent else 1}}))
    batch,jobs,_=await submit_batch(db,settings.model_copy(update={'job_max_attempts':1}),organization_id=conv.organization_id,
        user_id=conv.user_id,payload=JobBatchSubmitRequest(name='Amazon运营图片',project_id=project.id,
        workspace_type='listing' if p.deliverable=='listing' else 'aplus',
        operation_code='listing.generate' if p.deliverable=='listing' else 'aplus.generate',capability='image_edit',
        model_code=budget['model_code'],idempotency_key=key,concurrency=min(12,len(items)),items=items))
    result={'batch_id':batch.id,'job_ids':[j.id for j in jobs],'module_ids':[m.id for m,s in pending],
        'slot_ids':[s['id'] for m,s in pending],'request_key':key,
        'module_signatures':{m.id+'::'+s['id']:module_signature(p,m) for m,s in pending}}
    row.metadata_json={**data,'project_id':project.id,'submissions':[*data['submissions'],result]}
    await db.flush();return {**result,'amazon_plan_id':row.id,'project_id':project.id}
