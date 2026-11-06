"""One owner-scoped Tool for natural-language and card sample review/regeneration."""
from datetime import datetime,timezone
import re
from typing import Literal
from pydantic import Field,model_validator
from sqlalchemy import select
from app.agents.contracts import StrictModel
from app.core.errors import AppError
from app.models.tasks import Job,BatchTryOnVersion,JobAttempt


async def upstream_unknown(db,job):
    meta=(job.input_json or {}).get('metadata') or {}
    if (meta.get('dsh_native') or meta.get('workflow')=='dsh_native_session') and job.status=='failed' and job.error_code in {'job.worker_lost','job.timeout'}:
        # A lost process can have sent a paid request. Receipt-only recovery is
        # separate from creating/retrying another generation Job.
        return True
    if any(w in str(job.error_code).lower() for w in ('timeout','524','network','remote_unknown')):return True
    attempt=await db.scalar(select(JobAttempt).where(JobAttempt.job_id==job.id,JobAttempt.organization_id==job.organization_id)
        .order_by(JobAttempt.attempt_number.desc()).limit(1))
    return bool(attempt and (attempt.http_status in (408,504,524) or any(w in str(attempt.error_code).lower() for w in ('timeout','remote_unknown','network'))))


class SampleDecision(StrictModel):
    sample_number:int=Field(ge=1,le=10)
    output_id:str|None=None
    decision:Literal['approve','revise','redo']
    notes:str=Field(default='',max_length=2000)


class ReviewSamples(StrictModel):
    plan_id:str
    expected_revision:int=Field(ge=1)
    expected_review_revision:int|None=Field(default=None,ge=0)
    decisions:list[SampleDecision]=Field(min_length=1,max_length=10)

    @model_validator(mode='after')
    def distinct(self):
        if len({x.sample_number for x in self.decisions})!=len(self.decisions):raise ValueError('Sample decisions must not conflict')
        return self


def authorized_approval(text,number):
    clauses=re.split(r'[，,。；;\n]',text)
    def numbers(clause):
        return [int(x) for x in re.findall(r'\d+',clause)]+['一二三四五六七八九十'.index(x)+1 for x in re.findall(r'[一二三四五六七八九十]',clause)]
    excluded={n for clause in clauses if re.search(r'除了|除.*外|不通过|未通过|没通过|重做|修改|太暗|错误|不合格|不满意',clause)
        and (re.match(r'\s*(?:把|第|样图\s*)?[0-9一二三四五六七八九十]',clause) or re.search(r'第[0-9一二三四五六七八九十]|除',clause)) for n in numbers(clause)}
    if number in excluded:return False
    for clause in clauses:
        if re.search(r'不.{0,5}通过|未通过|没通过|不合格|不满意',clause):continue
        if re.search(r'全部(?:样图)?通过|都通过|所有(?:的|样图)*通过',clause):return True
        if re.search(r'通过|合格|满意',clause) and number in numbers(clause):return True
    return False


async def resolve(db,conv,args):
    from app.agents import production
    from app.agents.adapters import chat
    row,rules=await production.plan_record(db,conv,args.plan_id,True)
    if rules.revision!=args.expected_revision:raise AppError('agent.revision_conflict','替换规则已更新，请读取最新样图。',409)
    if args.expected_review_revision is not None and rules.review_revision!=args.expected_review_revision:
        raise AppError('agent.review_conflict','样图审核状态已更新，请刷新后再操作。',409)
    gallery=await chat.outputs(db,conv)
    selected=[];tids=list(rules.template_rules)
    for decision in args.decisions:
        if decision.sample_number>len(tids):raise AppError('agent.sample_not_found','样图序号不存在。',404)
        tid=tids[decision.sample_number-1];jid=rules.samples.get(tid)
        output=next((o for o in gallery if o['job_id']==jid),None)
        job=await db.get(Job,jid)
        version=await db.scalar(select(BatchTryOnVersion).where(BatchTryOnVersion.task_id==jid,BatchTryOnVersion.organization_id==conv.organization_id))
        failed_retry=job and job.status=='failed' and decision.decision=='redo' and version
        if failed_retry and args.expected_review_revision is None:
            raise AppError('agent.review_conflict','重试失败样图需要当前审核版本，请读取最新样图状态。',409)
        if failed_retry and await upstream_unknown(db,job):
            raise AppError('agent.remote_unknown','上游状态未知，未自动重发；请先核对原请求。',409)
        if failed_retry:output={'id':None,'root_output_id':None,'version':version.version_number}
        if not failed_retry and not decision.output_id:
            raise AppError('agent.sample_stale','请引用当前样图的Output ID，未审核未定位的图片。',409)
        if not output or decision.output_id and decision.output_id!=output['id']:
            raise AppError('agent.sample_stale','样图已更新或不属于当前方案，未采用旧结果。',409)
        if not job or job.created_by!=conv.user_id or job.organization_id!=conv.organization_id or not version or job.status!='succeeded' and not failed_retry:
            raise AppError('agent.sample_not_ready','样图尚未成功，不能审核或修改。',409)
        selected.append((decision,tid,output,job,version))
    return row,rules,selected


async def quote(db,conv,args):
    from app.services.billing_service import estimate_response
    _,_,selected=await resolve(db,conv,args)
    redo=[s for s in selected if s[0].decision!='approve']
    if not redo:return {'estimated_cost':'0','sufficient':True,'quantity':0}
    models={s[3].model_code for s in redo}
    if len(models)!=1:raise AppError('agent.sample_model_mismatch','样图模型不同，请分别修改。',409)
    budget=(await estimate_response(db,organization_id=conv.organization_id,operation_code='batch_tryon.generate',quantity=len(redo),
        factors={'model':next(iter(models)),'quality':'high','resolution':'2048x2048','resource_pool':'platform'})).model_dump(mode='json')
    return {**budget,'quantity':len(redo),'model_code':next(iter(models))}


async def execute(db,settings,conv,args,key,*,human_request,card_request=None):
    from app.agents import production,experience
    from app.schemas.batch_tryon_review import BatchTryOnRegenerateRequest
    from app.services.batch_tryon_review_service import regenerate_version
    row,rules,selected=await resolve(db,conv,args)
    card=card_request is not None and ReviewSamples.model_validate(card_request).model_dump()==args.model_dump()
    for decision,tid,output,job,version in selected:
        if decision.decision=='approve' and not card and not authorized_approval(human_request,decision.sample_number):
            raise AppError('agent.review_authorization','未收到该样图的明确通过指令，Agent不能自行审核通过。',403)
        if decision.decision!='approve' and not card and not (str(decision.sample_number) in human_request or re.search(r'全部|这些|有问题|重做|修改',human_request)):
            raise AppError('agent.review_scope','修改范围不明确，未追加图片任务。',409)
    if any(s[0].decision!='approve' for s in selected) and not settings.agent_control_model_calls_enabled:
        raise AppError('agent.model_calls_disabled','当前未启用模型执行，未重做样图。',409)
    ids=[];changes=[]
    for decision,tid,output,job,version in selected:
        state=rules.sample_reviews.get(tid,{})
        history=list(state.get('history',[]))
        if decision.decision=='approve':
            # Existing service owns Review/Version state; sample image is never a production template.
            await production.approve_sample(db,conv,row.id,output['id'],rules.revision)
            rules.sample_approvals[tid]=output['id']
            rule=state.get('reusable_rule','')
            rules.verified_template_rules[tid]={'output_id':output['id'],'feedback':rule,'rule_signature':production.rules_signature(rules)}
            notes=state.get('notes','')
            facts=' '.join(f for r in rules.garment_rules.values() for f in r.visual_facts)
            case_id=await experience.record_case(db,conv,plan_id=row.id,template_id=tid,product_type=experience.scope(facts+' '+rules.common_prompt),
                scenario=rules.template_rules[tid].template_type,before_output_id=state.get('before_output_id'),after_output_id=output['id'],notes=notes,rule=rule,
                opt_out=rules.memory_opt_out or experience.task_only(human_request))
            changes.append({'sample_number':decision.sample_number,'output_id':output['id'],'status':'approved','case_id':case_id})
            status='approved';next_job=job.id
        else:
            notes=decision.notes or '按当前服装参考重新生成，保持商品事实。'
            _,_,new_job,_=await regenerate_version(db,settings,organization_id=conv.organization_id,item_id=version.item_id,user_id=conv.user_id,
                payload=BatchTryOnRegenerateRequest(source_version_id=version.id,retry_mode='with_review_notes',review_notes=notes,idempotency_key=key+':'+tid))
            meta=new_job.input_json.get('metadata') or {}
            if output['id']:
                new_job.input_json={**new_job.input_json,'metadata':{**meta,'agent_image':{'conversation_id':conv.id,
                    'parent_output_id':output['id'],'root_output_id':output['root_output_id'],'version':output['version']+1}}}
            rules.samples[tid]=new_job.id;rules.sample_approvals.pop(tid,None);rules.verified_template_rules.pop(tid,None)
            ids.append(new_job.id);status='regenerating';next_job=new_job.id;case_id=None
            state={**state,'notes':notes,'before_output_id':output['id'],'reusable_rule':experience.correction_rule(notes)}
            changes.append({'sample_number':decision.sample_number,'output_id':output['id'],'job_id':new_job.id,'status':status})
        history.append({'decision':decision.decision,'output_id':output['id'],'notes':decision.notes,'at':datetime.now(timezone.utc).isoformat()})
        rules.sample_reviews[tid]={**state,'status':status,'job_id':next_job,'output_id':output['id'],'history':history[-30:]}
    rules.review_revision+=1
    row.metadata_json=rules.model_dump(mode='json');await db.flush()
    return {'job_ids':ids,'production_plan_id':row.id,'review_revision':rules.review_revision,'sample_changes':changes,
        'cards':[{'type':'sample_review_receipt','changes':changes}],'workspace_url':f'/workspaces/batch-tryon?project_id={rules.project_id}'}
