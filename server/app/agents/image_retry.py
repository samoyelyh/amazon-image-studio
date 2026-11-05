"""Single failed chat image -> original business action, no new execution engine."""
from sqlalchemy import select
from app.core.errors import AppError
from app.models.tasks import Job
from app.models.agent_control import AgentJobLink,AgentRun
from app.agents.contracts import AgentPlan,ToolAction,ChatImageAction


async def plan(db,settings,run,context):
    from app.agents import runtime,amazon
    from app.agents.samples import upstream_unknown
    from app.agents.adapters import chat
    from app.agents.amazon_contracts import GenerateAPlus
    from app.services.resource_pool_service import resolve_operation_model_code
    job=await db.scalar(select(Job).join(AgentJobLink,AgentJobLink.job_id==Job.id)
        .join(AgentRun,AgentRun.id==AgentJobLink.run_id).where(Job.id==run.selection_json['retry_image_job_id'],
            Job.organization_id==run.organization_id,Job.created_by==run.user_id,AgentRun.conversation_id==run.conversation_id,
            AgentRun.user_id==run.user_id,AgentRun.organization_id==run.organization_id).with_for_update())
    if not job:raise AppError('agent.job_not_found','任务不存在或无权重试。',404)
    if job.status!='failed':raise AppError('agent.retry_not_failed','只能重试已经明确失败的图片任务。',409)
    if await upstream_unknown(db,job):raise AppError('agent.remote_unknown','上游结果未知，请核对原请求，未重复提交。',409)
    data=job.input_json or {};meta=data.get('metadata') or {}
    if (job.result_json or {}).get('outputs'):raise AppError('agent.result_exists','原任务已有图片结果，请先查看，未重复生成。',409)
    conv=await runtime.conversation(db,run.organization_id,run.user_id,run.conversation_id)
    if meta.get('workflow')=='agent_aplus':
        m=meta['amazon_module']
        args=GenerateAPlus(plan_id=m['plan_id'],expected_revision=m['plan_revision'],module_ids=[m['module_id']],retry_failed=True)
        budget=await amazon.image_quote(db,conv,args,require_approval=not runtime.autonomous(run))
        action=ToolAction(tool='generate_aplus',arguments=args.model_dump())
    elif meta.get('workflow')=='agent_chat':
        parent=meta.get('agent_image') or {};refs=data.get('reference_asset_ids',[])
        model=await resolve_operation_model_code(db,organization_id=run.organization_id,operation_code='listing.generate',capability=job.capability)
        args=ChatImageAction(project_id=context['project_id'],prompt=data.get('effective_prompt') or data['prompt'],
            reference_asset_ids=refs,parent_output_id=parent.get('parent_output_id'),
            parent_asset_id=refs[0] if parent.get('parent_output_id') and refs else None,root_output_id=parent.get('root_output_id'),
            count=1,model_code=model,capability=job.capability)
        budget=await chat.quote(db,run.organization_id,args)
        action=ToolAction(tool='generate_chat_images',arguments=args.model_dump())
    else:raise AppError('agent.retry_workspace_required','该专业任务请使用原工作台的单图重试入口。',409)
    run.result_json={**run.result_json,'retry_of_job_id':job.id}
    return AgentPlan(summary='仅重新生成这张失败图片，其他结果保持不变。',workflow='aplus' if action.tool=='generate_aplus' else 'edit',
        image_count=1,may_charge=True,budget=budget,actions=[action])
