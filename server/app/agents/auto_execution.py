"""Bounded authority from one human send; reuse the original signed confirmation.

No blanket model authorization, no new queue, no provider calls or retries here.
Grant/usage live with the existing Run. Redis only holds disposable rate counters.
"""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from math import ceil
from statistics import median
from sqlalchemy import select, func, or_
from app.agents.contracts import AgentPlan, ConfirmRequest
from app.models.tasks import Job, ProviderModel, Provider, ResourcePool, OperationResourcePool, ResourcePoolKey, ApiKey
from app.models.agent_control import AgentRun, AgentJobLink
from app.models.identity import User
from app.core.errors import AppError

UTC=timezone.utc
ACTIVE={'queued','waiting_for_resource','dispatching','running','retry_waiting'}
RATE_SCRIPT="""-- agent-auto-rate-v1
if redis.call('EXISTS',KEYS[1]) == 1 then return 1 end
if tonumber(redis.call('GET',KEYS[2]) or '0') >= tonumber(ARGV[1]) then return -1 end
if tonumber(redis.call('GET',KEYS[3]) or '0') + tonumber(ARGV[3]) > tonumber(ARGV[2]) then return -2 end
redis.call('INCR',KEYS[2]); redis.call('EXPIRE',KEYS[2],120)
redis.call('INCRBY',KEYS[3],ARGV[3]); redis.call('EXPIRE',KEYS[3],3700)
redis.call('SET',KEYS[1],'1','EX',3600)
return 1
"""


def grant(settings, request):
    if not (settings.agent_auto_execute_enabled and request.chat_mode):return None
    if settings.agent_execution_mode == 'autonomous':
        from app.agents.execution_policy import wants_review,wants_sample_review
        return {'version':2,'policy':'autonomous','review_before_generation':
            request.review_before_generation if request.review_before_generation is not None else wants_review(request.content),
            'sample_review_required':wants_sample_review(request.content),
            'limits':{'steps':settings.agent_autonomous_max_steps},
            'used':{'images':0,'credits':0,'text_jobs':0,'steps':0},'proposals':{}}
    if not request.auto_execute:return None
    return {'version':1,'expires_at':(datetime.now(UTC)+timedelta(minutes=30)).isoformat(),
        'limits':{'images':settings.agent_auto_max_images,'seconds':settings.agent_auto_max_seconds,
            'credits':settings.agent_auto_max_credits,'text_jobs':settings.agent_auto_max_text_jobs,
            'steps':settings.agent_auto_max_steps},'used':{'images':0,'credits':0,'text_jobs':0,'steps':0},'proposals':{}}


def request_digest(payload):
    from app.agents.adapters.batch_tryon import digest
    value={k:v for k,v in payload.items() if k!='client_request_id'}
    for key,default in (('request_mode','create'),('reply_to_run_id',None),('reply_to_revision',None),('review_before_generation',None),('start_new_task',False),('use_batch_inputs',False),('creative_module',None),('sample_review',None),('production_approved_only',False),('prompt_source_run_id',None),('prompt_version_id',None),('retry_image_job_id',None)):
        if value.get(key)==default:value.pop(key,None)
    return digest(value)


async def duplicate(db, settings, conv, request,creative_context=None):
    if not (settings.agent_auto_execute_enabled and request.chat_mode and (request.auto_execute or settings.agent_execution_mode=='autonomous')):return None
    recent_ids=list((await db.scalars(select(AgentRun.id).where(AgentRun.conversation_id==conv.id,
        AgentRun.organization_id==conv.organization_id,AgentRun.user_id==conv.user_id,
        AgentRun.created_at>=datetime.now(UTC)-timedelta(minutes=30)).order_by(AgentRun.created_at.desc()).limit(10))).all())
    recent=list((await db.scalars(select(AgentRun).where(AgentRun.id.in_(recent_ids)))).all()) if recent_ids else []
    fingerprint=request_digest(request.model_dump(mode='json'))
    batch_key=None
    if request.use_batch_inputs:
        from app.agents import batch_manifest
        manifest=await batch_manifest.record(db,conv)
        if manifest:batch_key=batch_manifest.material_key(batch_manifest.BatchInputManifest.model_validate(manifest.metadata_json))
    for row in recent:
        covered_import=(request.use_batch_inputs and request.client_request_id.startswith('imports:') and batch_key
            and batch_key in row.result_json.get('submitted_import_keys',[])
            and row.selection_json.get('content')==request.content)
        if request.use_batch_inputs and row.selection_json.get('_batch_input_key')!=batch_key and not covered_import:continue
        prior_context=row.selection_json.get('_creative_context') or {'module':'auto','revision':0}
        current_context=creative_context or {'module':'auto','revision':0}
        if any(prior_context.get(k)!=current_context.get(k) for k in ('module','revision')):continue
        if covered_import:return row
        created=row.created_at.replace(tzinfo=UTC) if row.created_at.tzinfo is None else row.created_at
        if (row.status=='remote_unknown' or datetime.now(UTC)-created<timedelta(seconds=30)) and (row.result_json.get('submission_fingerprint') or request_digest(row.selection_json))==fingerprint:
            return row
    return None


def quantities(plan):
    # Existing planners materialize one billable business action per proposal.
    # Do not treat a multi-action quote as a complete aggregate spending limit.
    if len(plan.actions)!=1:return None
    images=texts=0; operations=[]
    for action in plan.actions:
        args=action.arguments
        if action.tool in {'plan_intent','suggest_creative_directions'}:texts+=1
        elif action.tool=='analyze_chat_assets':texts+=len(args.get('asset_ids',[]))
        elif action.tool=='generate_chat_images':
            images+=int(args.get('count',1));operations.append(('listing.generate',args.get('model_code') or (plan.budget or {}).get('model_code')))
        elif action.tool=='generate_aplus':
            images+=len(args.get('module_ids',[]));operations.append(('aplus.generate',(plan.budget or {}).get('model_code')))
        elif action.tool in {'generate_chat_tryon','review_tryon_samples'}:
            # Rules and sample approvals are still enforced by production.image_quote
            # and by the original confirmation/submission path, not by the model.
            images+=int((plan.budget or {}).get('quantity',0));operations.append(('batch_tryon.generate',(plan.budget or {}).get('model_code')))
        elif action.tool in {'save_aplus_plan','revise_aplus_module','revise_amazon_modules','prepare_tryon_workspace','show_message','manage_user_preference','recall_user_experience','guide_batch_inputs'}:pass
        else:return None
    if plan.image_count!=images and any(a.tool in {'generate_chat_images','generate_aplus','generate_chat_tryon'} for a in plan.actions):return None
    return images,texts,operations


async def estimate(db, redis, settings, org, operation, model_code, count):
    """A range, not a countdown; original key limits/leases and observed durations."""
    now=datetime.now(UTC)
    rows=(await db.execute(select(ApiKey.id,ApiKey.max_concurrency,ApiKey.cooldown_until,ApiKey.consecutive_failures)
        .select_from(OperationResourcePool).join(ResourcePool,ResourcePool.id==OperationResourcePool.resource_pool_id)
        .join(ProviderModel,ProviderModel.id==ResourcePool.model_id).join(Provider,Provider.id==ProviderModel.provider_id)
        .join(ResourcePoolKey,ResourcePoolKey.resource_pool_id==ResourcePool.id).join(ApiKey,ApiKey.id==ResourcePoolKey.api_key_id)
        .where(OperationResourcePool.operation_code==operation,OperationResourcePool.enabled.is_(True),
            ResourcePool.enabled.is_(True),ProviderModel.enabled.is_(True),Provider.enabled.is_(True),
            ResourcePoolKey.enabled.is_(True),ApiKey.enabled.is_(True),ApiKey.status!='disabled',
            or_(OperationResourcePool.organization_id.is_(None),OperationResourcePool.organization_id==org),
            or_(ResourcePool.organization_id.is_(None),ResourcePool.organization_id==org),
            or_(ApiKey.organization_id.is_(None),ApiKey.organization_id==org),
            *([ProviderModel.code==model_code] if model_code else [])))).all()
    keys={r.id:r for r in rows};capacity=used=0
    for key in keys.values():
        until=key.cooldown_until
        if until and (until.replace(tzinfo=UTC) if until.tzinfo is None else until)>now:continue
        if await redis.get(f'resource:key:{key.id}:cooldown'):continue
        capacity+=1 if key.consecutive_failures else key.max_concurrency
        used+=int(await redis.get(f'resource:key:{key.id}:inflight') or 0)
    cap=min(capacity,settings.job_system_max_concurrency,settings.job_organization_max_concurrency,
        settings.job_user_max_concurrency,settings.celery_worker_concurrency)
    if cap<1:return {'source':'resource_wait','sample_count':0,'text':'正在等待可用资源','maximum_seconds':None}
    codes=set((await db.scalars(select(ProviderModel.code).join(ResourcePool,ResourcePool.model_id==ProviderModel.id)
        .join(ResourcePoolKey,ResourcePoolKey.resource_pool_id==ResourcePool.id).where(ResourcePoolKey.api_key_id.in_(keys)))).all())
    ahead=int(await db.scalar(select(func.count(Job.id)).where(Job.model_code.in_(codes),Job.status.in_(ACTIVE),
        or_(Job.next_dispatch_at.is_(None),Job.next_dispatch_at<=now))) or 0)
    durations=list((await db.scalars(select(Job.generation_duration_ms).where(Job.organization_id==org,
        Job.operation_code==operation,Job.status=='succeeded',Job.generation_duration_ms.between(1000,1800000),
        *([Job.model_code==model_code] if model_code else [])).order_by(Job.finished_at.desc()).limit(30))).all())
    sampled=len(durations)>=5
    per_low=max(15,median(durations)/1000*.7) if sampled else 60
    per_high=max(30,median(durations)/1000*1.6) if sampled else 180
    # A short queue that fits the currently available slots is not an extra wave.
    # Respect both shared capacity and the native per-chat-batch cap of two.
    waves=max(1,ceil(count/min(2,cap)),ceil((max(ahead,used)+count)/cap))
    low,high=ceil(per_low*waves),ceil(per_high*waves)
    label=f'预计约 {max(1,ceil(low/60))}–{max(1,ceil(high/60))} 分钟'
    if not sampled:label+='（保守预留）'
    return {'source':'recent_successes' if sampled else 'conservative_reservation','sample_count':len(durations),
        'minimum_seconds':low,'maximum_seconds':high,'text':label}


async def drive(db, settings, redis, run, permissions):
    """Called after human send / owner polling. Never grants authority to old Runs."""
    if (run.result_json.get('auto_execution') or {}).get('version') == 2:
        from app.agents.autonomous_execution import drive as autonomous_drive
        return await autonomous_drive(db,settings,redis,run,permissions)
    from app.agents import runtime
    from app.models.hermes_agent import HermesProposal
    for _ in range(settings.agent_auto_max_steps+1):
        state=run.result_json.get('auto_execution')
        if not state or state.get('suspended') or state.get('manual_proposal')==run.proposal_id or not settings.agent_auto_execute_enabled or run.status!='awaiting_confirmation':return
        await db.scalar(select(User.id).where(User.id==run.user_id).with_for_update())
        plan=AgentPlan.model_validate(run.plan_json)
        reason=None;time=None
        q=quantities(plan)
        if run.planner_mode!=settings.agent_control_planner or (run.planner_mode=='mock' and settings.environment!='test'):
            reason='这是旧预览计划，请重新发送需求'
        elif datetime.now(UTC)>datetime.fromisoformat(state['expires_at']):reason='本次自动执行授权已过期，请确认后继续'
        elif not settings.agent_control_writes_enabled or not settings.agent_control_model_calls_enabled:reason='服务端尚未启用执行'
        elif plan.blocked_reason or plan.needs_input or (plan.budget or {}).get('sufficient') is False:reason='请先补充信息或检查额度'
        elif q is None:reason='此操作需要你确认'
        images,texts,operations=q or (0,0,[])
        try:
            amount=Decimal(str((plan.budget or {}).get('estimated_cost',0)))
            if not amount.is_finite() or amount<0 or amount!=int(amount):raise InvalidOperation
            credits=int(amount)
        except (InvalidOperation,ValueError,OverflowError):reason='无法确定费用，请确认后继续';credits=0
        if plan.may_charge and not plan.budget:reason='无法确定费用，请确认后继续'
        limits={k:min(state['limits'][k],v) for k,v in {
            'images':settings.agent_auto_max_images,'seconds':settings.agent_auto_max_seconds,
            'credits':settings.agent_auto_max_credits,'text_jobs':settings.agent_auto_max_text_jobs,'steps':settings.agent_auto_max_steps}.items()}
        prior=state['proposals'].get(run.proposal_id)
        used=state['used']
        if not prior and not reason:
            if used['images']+images>limits['images']:reason=f'本次超过 {limits["images"]} 张图片，请确认后生成'
            elif used['credits']+credits>limits['credits']:reason=f'本次超过 {limits["credits"]} 平台额度，请确认后继续'
            elif used['text_jobs']+texts>limits['text_jobs'] or used['steps']+1>limits['steps']:reason='已达到本次自动处理上限，请确认下一步'
        if images and operations:
            try:
                estimates=[await estimate(db,redis,settings,run.organization_id,op,model,images) for op,model in operations]
                time=max(estimates,key=lambda e:e.get('maximum_seconds') or 10**9)
                if not reason and (time.get('maximum_seconds') is None or time['maximum_seconds']>limits['seconds']):
                    reason=f'预计等待或生成时间较长，请确认后继续'
            except Exception:
                if not reason:reason='暂时无法估计等待时间，请确认后继续'
        if not reason and not prior:
            active=int(await db.scalar(select(func.count(func.distinct(AgentRun.id))).join(AgentJobLink,AgentJobLink.run_id==AgentRun.id)
                .join(Job,Job.id==AgentJobLink.job_id).where(AgentRun.organization_id==run.organization_id,
                    AgentRun.user_id==run.user_id,AgentRun.id!=run.id,Job.status.in_(ACTIVE))) or 0)
            if active>=settings.agent_auto_max_active_runs:reason='你已有多个任务在进行，请确认是否继续排队'
        if not reason:
            now=datetime.now(UTC);prefix=f'agent:auto:{run.organization_id}:{run.user_id}'
            try:
                allowed=int(await redis.eval(RATE_SCRIPT,3,prefix+':proposal:'+run.proposal_id,
                    prefix+':minute:'+str(int(now.timestamp())//60),prefix+':hour:'+now.strftime('%Y%m%d%H'),
                    settings.agent_auto_submissions_per_minute,settings.agent_auto_credits_per_hour,credits))
                if allowed!=1:reason='自动请求过于频繁或已达到小时额度上限，请确认后继续'
            except Exception:reason='自动执行保护暂不可用，请确认后继续'
        notice={'automatic':not bool(reason),'reason':reason,'image_count':images,'estimated_credits':credits,
            'estimate':time,'limits':limits}
        run.result_json={**run.result_json,'execution_notice':notice}
        if reason:
            run.result_json={**run.result_json,'auto_execution':{**state,'manual_proposal':run.proposal_id}}
            await db.commit();return
        if not prior:
            state={**state,'used':{k:used[k]+v for k,v in {'images':images,'text_jobs':texts,'credits':credits,'steps':1}.items()},
                'proposals':{**state['proposals'],run.proposal_id:{'images':images,'credits':credits,'texts':texts}}}
            run.result_json={**run.result_json,'auto_execution':state}
            await runtime.event(db,run,'bounded_auto_authorized',{'proposal_id':run.proposal_id,'images':images,'credits':credits},key='auto:'+run.proposal_id)
            await db.commit()  # Reserve the bounded grant before a possibly interrupted submission.
            run=await runtime.owned_run(db,run.organization_id,run.user_id,run.id,lock=True)
            await db.scalar(select(User.id).where(User.id==run.user_id).with_for_update())
            active=int(await db.scalar(select(func.count(func.distinct(AgentRun.id))).join(AgentJobLink,AgentJobLink.run_id==AgentRun.id)
                .join(Job,Job.id==AgentJobLink.job_id).where(AgentRun.organization_id==run.organization_id,
                    AgentRun.user_id==run.user_id,AgentRun.id!=run.id,Job.status.in_(ACTIVE))) or 0)
            if active>=settings.agent_auto_max_active_runs:
                run.result_json={**run.result_json,'execution_notice':{**notice,'automatic':False,
                    'reason':'你已有多个任务在进行，请确认是否继续排队'},
                    'auto_execution':{**state,'manual_proposal':run.proposal_id}}
                await db.commit();return
        proposal=await db.get(HermesProposal,run.proposal_id)
        identity=(run.organization_id,run.user_id,run.id)
        try:
            await runtime.confirm(db,settings,redis,run,ConfirmRequest(expected_revision=run.revision,
                state_signature=proposal.expected_state_signature,confirmation_token=runtime.confirmation_token(settings,run,proposal)),permissions)
        except AppError as error:
            # A business/price/permission/checkpoint guard is a stop, never an
            # automatic replacement request. Persist the original safe reason.
            await db.rollback()
            run=await runtime.owned_run(db,*identity,lock=True)
            run.result_json={**run.result_json,'auto_execution':{**run.result_json.get('auto_execution',state),'suspended':True},
                'execution_notice':{**notice,'automatic':False,'reason':error.message}}
            await runtime.event(db,run,'auto_execution_stopped',{'code':error.code},key='auto-stopped:'+run.proposal_id)
            await db.commit()
            return
