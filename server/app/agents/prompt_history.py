"""Prompt drafts live in AgentRun JSON; actual submitted prompts stay immutable in Job."""
from datetime import datetime,timezone
from uuid import uuid4
from app.core.errors import AppError


def remember_plan(run,plan):
    versions=list(run.result_json.get('prompt_versions') or [])
    for index,action in enumerate(plan.actions):
        if action.tool!='generate_chat_images':continue
        content=action.arguments.get('prompt')
        if not content or any(v['source']=='plan' and v['content']==content for v in versions):continue
        versions.append({'id':str(uuid4()),'version':len(versions)+1,'content':content,'source':'plan',
            'action_index':index,'replayable':True,'created_at':datetime.now(timezone.utc).isoformat()})
    run.result_json={**run.result_json,'prompt_versions':versions}


def records(run,jobs):
    result=list(run.result_json.get('prompt_versions') or [])
    # Show model instructions even if a legitimate clarification precedes materialization.
    decision=(run.result_json.get('planner_decision') or {}).get('capability_plan') or {}
    for i,step in enumerate(decision.get('steps',[])):
        if step.get('capability_id')!='business.create_images':continue
        value=(step.get('arguments') or {}).get('instruction')
        if value and not any(v['content']==value for v in result):
            result.append({'id':f'planner-{i}','version':0,'content':value,'source':'planner','action_index':i})
    for job in jobs:
        if job.capability=='text_generation':continue
        data=job.input_json or {}
        value=data.get('effective_prompt') or data.get('prompt') or (data.get('metadata') or {}).get('effective_prompt_snapshot')
        if value:result.append({'id':'job-'+job.id,'version':0,'content':value,'source':'executed' if data.get('effective_prompt') else 'submitted',
            'job_id':job.id,'job_status':job.status,'replayable':(data.get('metadata') or {}).get('workflow')=='agent_chat','created_at':job.created_at.isoformat()})
    return result


def save(run,request,jobs):
    if run.revision!=request.expected_revision:raise AppError('agent.revision_conflict','记录已更新，请刷新后保存。',409)
    source=next((r for r in records(run,jobs) if r['id']==request.source_id),None)
    if source is None:
        raise AppError('agent.prompt_not_found','提示词不属于当前任务。',404)
    versions=list(run.result_json.get('prompt_versions') or [])
    if len(versions)>=50:raise AppError('agent.prompt_version_limit','当前任务的提示词版本已达上限。',409)
    versions.append({'id':str(uuid4()),'version':len(versions)+1,'content':request.content.strip(),'source':'user',
        'parent_id':request.source_id,'replayable':source.get('replayable',False),'created_at':datetime.now(timezone.utc).isoformat()})
    if not versions[-1]['content']:raise AppError('agent.empty_prompt','提示词不能为空。',422)
    run.result_json={**run.result_json,'prompt_versions':versions}
    # A draft is not an approval and never mutates an existing Job or checkpoint.
    run.revision+=1
    return versions[-1]


async def saved_plan(db,settings,run,context):
    from sqlalchemy import select
    from app.agents import runtime
    from app.agents.contracts import AgentPlan,ToolAction,ChatImageAction
    from app.models.agent_control import AgentJobLink
    from app.models.tasks import Job
    from app.services.resource_pool_service import resolve_operation_model_code
    from app.agents.adapters import chat
    source=await runtime.owned_run(db,run.organization_id,run.user_id,run.selection_json['prompt_source_run_id'],lock=True)
    if source.conversation_id!=run.conversation_id:raise AppError('agent.prompt_not_found','提示词不属于当前会话。',404)
    versions={v['id']:v for v in source.result_json.get('prompt_versions',[])}
    revision=versions.get(run.selection_json['prompt_version_id'])
    if not revision:raise AppError('agent.prompt_not_found','提示词版本不存在。',404)
    base=revision
    for _ in range(50):
        parent=base.get('parent_id')
        if parent in versions:base=versions[parent]
        else:break
    parent=base.get('parent_id','')
    original=None
    if parent.startswith('job-'):
        job=await db.scalar(select(Job).join(AgentJobLink,AgentJobLink.job_id==Job.id).where(
            AgentJobLink.run_id==source.id,Job.id==parent[4:],Job.organization_id==run.organization_id,Job.created_by==run.user_id))
        if not job or job.capability=='text_generation':raise AppError('agent.prompt_not_found','原图片任务不存在。',404)
        if ((job.input_json or {}).get('metadata') or {}).get('workflow')!='agent_chat':
            raise AppError('agent.prompt_workflow_not_supported','该提示词属于专业生产任务，请在对应模块继续修改，不能改走普通图片任务。',409)
        data=job.input_json or {}; meta=(data.get('metadata') or {}).get('agent_image') or {}
        original=ChatImageAction(project_id=context['project_id'],prompt=revision['content'],reference_asset_ids=data.get('reference_asset_ids',[]),
            parent_output_id=meta.get('parent_output_id'),parent_asset_id=(data.get('reference_asset_ids') or [None])[0] if meta.get('parent_output_id') else None,
            root_output_id=meta.get('root_output_id'),count=1,model_code=job.model_code,capability=job.capability)
    else:
        action=next((a for a in (source.plan_json or {}).get('actions',[]) if a['tool']=='generate_chat_images'
            and a['arguments'].get('prompt')==base['content']),None)
        if action:original=ChatImageAction.model_validate({**action['arguments'],'prompt':revision['content'],'project_id':context['project_id']})
    if original is None:raise AppError('agent.prompt_inputs_incomplete','尚未形成完整图片执行方案，请先补齐必要素材。',409)
    model=await resolve_operation_model_code(db,organization_id=run.organization_id,operation_code='listing.generate',capability=original.capability)
    original=original.model_copy(update={'model_code':model})
    quote=await chat.quote(db,run.organization_id,original)
    if source.status=='awaiting_review':
        from app.models.hermes_agent import HermesProposal
        proposal=await db.get(HermesProposal,source.proposal_id)
        if proposal and proposal.status=='pending':proposal.status='cancelled'
        source.status='cancelled';source.revision+=1
        await runtime.event(db,source,'superseded_by_prompt_version',{'new_run_id':run.id,'version_id':revision['id']})
    return AgentPlan(summary=f"使用已保存的提示词 V{revision['version']}生成{original.count}张图片。",workflow='edit' if original.parent_output_id else 'fast',
        image_count=original.count,may_charge=True,budget=quote,actions=[ToolAction(tool='generate_chat_images',arguments=original.model_dump(mode='json'))])
