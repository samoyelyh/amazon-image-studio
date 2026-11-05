"""Execute scoped human requests through existing signed proposals, never a second queue."""
from datetime import datetime,timezone,timedelta
from decimal import Decimal,InvalidOperation
from sqlalchemy import select
from app.models.identity import User
from app.models.hermes_agent import HermesProposal
from app.agents.contracts import AgentPlan,ConfirmRequest
from app.core.errors import AppError

UTC=timezone.utc
REGULAR_TOOLS={
    'plan_intent','suggest_creative_directions','generate_chat_images','analyze_chat_assets',
    'generate_chat_tryon','submit_tryon_batch','analyze_tryon_references','compile_prompt_plan',
    'prepare_tryon_workspace','save_aplus_plan','revise_aplus_module','revise_amazon_modules','generate_aplus',
    'research_amazon','show_message','read_business_context','read_jobs','read_shared_queue','export_results','configure_batch_inputs','followup_batch_results',
    'review_tryon_samples','recall_user_experience','manage_user_preference','guide_batch_inputs',
}
RATE_SCRIPT="""-- agent-autonomous-rate-v2
if redis.call('EXISTS',KEYS[1]) == 1 then return 1 end
if tonumber(redis.call('GET',KEYS[2]) or '0') >= tonumber(ARGV[1]) then return 0 end
redis.call('INCR',KEYS[2]); redis.call('EXPIRE',KEYS[2],120)
redis.call('SET',KEYS[1],'1','EX',86400)
return 1
"""


async def drive(db,settings,redis,run,permissions):
    from app.agents import runtime,auto_execution
    from app.agents.tool_registry import validate_action
    if not settings.agent_auto_execute_enabled:return
    for _ in range(settings.agent_autonomous_max_steps+1):
        if run.status!='ready_to_submit':return
        await db.scalar(select(User.id).where(User.id==run.user_id).with_for_update())
        state=dict(run.result_json.get('auto_execution') or {})
        if state.get('version')!=2 or state.get('suspended'):return
        notice=run.result_json.get('execution_notice') or {}
        retry=notice.get('retry_at')
        if retry and datetime.fromisoformat(retry)>datetime.now(UTC):return
        plan=AgentPlan.model_validate(run.plan_json)
        try:
            if not settings.agent_control_writes_enabled or (plan.may_charge and not settings.agent_control_model_calls_enabled):
                raise AppError('agent.execution_disabled','当前环境未启用这项执行能力。',409)
            if run.planner_mode!=settings.agent_control_planner or (run.planner_mode=='mock' and settings.environment!='test'):
                raise AppError('agent.planner_changed','当前记录来自旧规划模式，不能自动执行。',409)
            if plan.needs_input or plan.blocked_reason:raise AppError('agent.plan_incomplete','执行条件尚不完整。',409)
            if (plan.budget or {}).get('sufficient') is False:raise AppError('agent.insufficient_budget','平台可用额度不足，未创建任务。',409)
            for action in plan.actions:
                spec,_=validate_action(action)
                if not set(spec.permissions)<=set(permissions):raise AppError('auth.permission_denied','当前账号没有执行权限。',403)
                if action.tool not in REGULAR_TOOLS:
                    run.status='awaiting_review'
                    run.result_json={**run.result_json,'review_reason':'此高风险业务操作需要单独授权。'}
                    await db.commit();return
            prior=state['proposals'].get(run.proposal_id)
            if not prior and state['used']['steps']>=min(state['limits']['steps'],settings.agent_autonomous_max_steps):
                raise AppError('agent.execution_step_limit','本次任务达到安全执行步数上限，已停止，未追加任务。',409)
            try:amount=Decimal(str((plan.budget or {}).get('estimated_cost',0)))
            except (InvalidOperation,TypeError,ValueError):raise AppError('agent.quote_invalid','无法取得有效报价，未创建任务。',409) from None
            if not amount.is_finite() or amount<0 or amount!=int(amount):raise AppError('agent.quote_invalid','无法取得有效报价，未创建任务。',409)
            credits=int(amount)
            q=auto_execution.quantities(plan)
            images,texts,operations=q or (plan.image_count,0,[])
            time=None
            if images and operations:
                try:time=await auto_execution.estimate(db,redis,settings,run.organization_id,*operations[0],images)
                except Exception:time={'source':'unavailable','sample_count':0,'text':'任务将进入现有生成队列，暂无可靠耗时估计'}
            prefix=f'agent:autonomous:{run.organization_id}:{run.user_id}'
            try:
                allowed=await redis.eval(RATE_SCRIPT,2,prefix+':proposal:'+run.proposal_id,
                    prefix+':minute:'+str(int(datetime.now(UTC).timestamp())//60),settings.agent_auto_submissions_per_minute)
            except Exception:allowed=None
            if allowed!=1:
                # Rate/Redis protection is a wait, never an approval that bypasses it.
                wait=5 if allowed is None else 60
                run.result_json={**run.result_json,'execution_notice':{'automatic':True,'image_count':images,
                    'estimated_credits':credits,'estimate':time,'reason':'执行保护暂不可用，稍后自动重试' if allowed is None else '请求较密集，等待安全提交窗口',
                    'retry_at':(datetime.now(UTC)+timedelta(seconds=wait)).isoformat()}}
                await db.commit();return
            if not prior:
                used=state['used']
                state={**state,'used':{k:used[k]+v for k,v in {'images':images,'text_jobs':texts,'credits':credits,'steps':1}.items()},
                    'proposals':{**state['proposals'],run.proposal_id:{'images':images,'credits':credits,'texts':texts}}}
                run.result_json={**run.result_json,'auto_execution':state}
                await runtime.event(db,run,'autonomous_authorized',{'proposal_id':run.proposal_id,'images':images},key='autonomous:'+run.proposal_id)
                await db.commit()
                run=await runtime.owned_run(db,run.organization_id,run.user_id,run.id,lock=True)
            run.result_json={**run.result_json,'execution_notice':{'automatic':True,'reason':None,'image_count':images,'estimated_credits':credits,'estimate':time}}
            proposal=await db.get(HermesProposal,run.proposal_id)
            await runtime.confirm(db,settings,redis,run,ConfirmRequest(expected_revision=run.revision,
                state_signature=proposal.expected_state_signature,confirmation_token=runtime.confirmation_token(settings,run,proposal)),permissions)
        except AppError as error:
            identity=(run.organization_id,run.user_id,run.id)
            await db.rollback()
            run=await runtime.owned_run(db,*identity,lock=True)
            # Unknown remote states are not failures safe to retry.
            run.status='remote_unknown' if 'remote_unknown' in error.code else 'failed'
            run.error_code=error.code
            run.result_json={**run.result_json,'execution_error':error.message,
                'auto_execution':{**run.result_json.get('auto_execution',state),'suspended':True}}
            await runtime.event(db,run,'autonomous_stopped',{'code':error.code})
            await db.commit();return
