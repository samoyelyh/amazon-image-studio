"""Targeted retries/adjustments reuse native Review/Version regeneration, not a new engine."""
from typing import Literal
from pydantic import Field
from sqlalchemy import select
from app.agents.contracts import StrictModel
from app.core.errors import AppError
from app.models.tasks import Job,BatchTryOnReviewItem,BatchTryOnVersion
from app.services.billing_service import estimate_response


class BatchFollowup(StrictModel):
    plan_id:str
    expected_revision:int=Field(ge=1)
    action:Literal['retry_failed','adjust']
    template_number:int|None=Field(default=None,ge=1,le=10)
    instruction:str=Field(default='',max_length=10000)


async def sources(db,conv,args):
    from app.agents.production import plan_record
    row,rules=await plan_record(db,conv,args.plan_id)
    if rules.revision!=args.expected_revision:raise AppError('agent.revision_conflict','套图规则已更新。',409)
    if not rules.production_batch_id:raise AppError('agent.batch_missing','该方案尚未提交正式批次。',409)
    tids=list(rules.template_rules)
    if args.template_number and args.template_number>len(tids):raise AppError('agent.template_missing','指定模板序号不存在。',422)
    target=tids[args.template_number-1] if args.template_number else None
    batch_ids=[b['batch_id'] for b in rules.production_batches] or [rules.production_batch_id]
    rows=(await db.execute(select(BatchTryOnReviewItem,BatchTryOnVersion,Job)
        .join(BatchTryOnVersion,BatchTryOnVersion.id==BatchTryOnReviewItem.current_version_id)
        .join(Job,Job.id==BatchTryOnVersion.task_id).where(BatchTryOnReviewItem.batch_id.in_(batch_ids),
            BatchTryOnReviewItem.organization_id==conv.organization_id,Job.created_by==conv.user_id,Job.organization_id==conv.organization_id))).all()
    selected=[]
    for item,version,job in rows:
        meta=job.input_json.get('metadata') or {}
        if meta.get('agent_production_plan_id')!=row.id or (target and meta.get('template_asset_id')!=target):continue
        if args.action=='retry_failed':
            if job.status!='failed':continue
            from app.agents.samples import upstream_unknown
            if await upstream_unknown(db,job):
                raise AppError('agent.remote_unknown','存在上游状态未知的失败任务，请核对上游后单独处理，未补发。',409)
        elif job.status!='succeeded':continue
        selected.append((item,version,job))
    if args.action=='adjust' and not args.instruction.strip():raise AppError('agent.instruction_required','请说明本次调整内容。',422)
    if not selected:raise AppError('agent.no_target_results','没有符合本次范围的可处理结果，未重复提交。',409)
    return rules,selected


async def quote(db,conv,args):
    rules,rows=await sources(db,conv,args)
    models={job.model_code for _,_,job in rows}
    if len(models)!=1:raise AppError('agent.mixed_models','本次结果使用不同模型，请分组处理。',409)
    result=(await estimate_response(db,organization_id=conv.organization_id,operation_code='batch_tryon.generate',quantity=len(rows),
        factors={'model':next(iter(models)),'quality':'high','resolution':'2048x2048','resource_pool':'platform'})).model_dump(mode='json')
    return {**result,'quantity':len(rows),'model_code':next(iter(models))}


async def execute(db,settings,conv,args,key):
    from app.services.batch_tryon_review_service import regenerate_version
    from app.schemas.batch_tryon_review import BatchTryOnRegenerateRequest
    from app.agents.adapters.chat import outputs
    rules,rows=await sources(db,conv,args)
    prior={o['job_id']:o for o in await outputs(db,conv)}
    jobs=[]
    for item,version,source in rows:
        _,new_version,job,_=await regenerate_version(db,settings,organization_id=conv.organization_id,item_id=item.id,user_id=conv.user_id,
            payload=BatchTryOnRegenerateRequest(source_version_id=version.id,retry_mode='with_review_notes' if args.action=='adjust' else 'direct',
                review_notes=args.instruction or None,idempotency_key=key+':'+item.id))
        output=prior.get(source.id)
        if output:
            meta=job.input_json.get('metadata') or {}
            job.input_json={**job.input_json,'metadata':{**meta,'agent_image':{'conversation_id':conv.id,
                'parent_output_id':output['id'],'root_output_id':output['root_output_id'],'version':output['version']+1}}}
        jobs.append(job.id)
    return {'job_ids':jobs,'production_plan_id':args.plan_id,'batch_id':rules.production_batch_id,
        'target_template_number':args.template_number,'action':args.action,'handled_count':len(jobs),
        'workspace_url':f'/workspaces/batch-tryon?project_id={rules.project_id}'}
