"""Resume a durable pending action; short acknowledgements are not new image requests."""
from datetime import datetime,timezone
from sqlalchemy import select
from app.models.agent_control import AgentRun
from app.models.hermes_agent import HermesMessage,HermesProposal
from app.agents import execution_policy as policy
from app.core.errors import AppError


async def recent(db,conv):
    ids=list((await db.scalars(select(AgentRun.id).where(AgentRun.conversation_id==conv.id,
        AgentRun.organization_id==conv.organization_id,AgentRun.user_id==conv.user_id)
        .order_by(AgentRun.created_at.desc(),AgentRun.id).limit(30))).all())
    rows=list((await db.scalars(select(AgentRun).where(AgentRun.id.in_(ids)))).all()) if ids else []
    messages={m.id:m for m in (await db.scalars(select(HermesMessage).where(HermesMessage.id.in_([r.source_message_id for r in rows])))).all()}
    replies=list((await db.scalars(select(HermesMessage).where(HermesMessage.conversation_id==conv.id,
        HermesMessage.user_id==conv.user_id,HermesMessage.role=='user').order_by(HermesMessage.created_at.desc()).limit(100))).all())
    def timestamp(r):
        m=messages.get(r.source_message_id)
        value=(m.metadata_json or {}).get('sent_at') if m else None
        values=[value or r.created_at.isoformat()]+[(m.metadata_json or {}).get('sent_at') or m.created_at.isoformat()
            for m in replies if m.metadata_json.get('reply_to_run_id')==r.id]
        return max(values)
    return sorted(rows,key=timestamp,reverse=True)


async def resume(db,settings,redis,conv,request,permissions):
    from app.agents import runtime,auto_execution
    from app.agents.autonomous_execution import REGULAR_TOOLS
    from app.agents.adapters.batch_tryon import digest
    if not request.chat_mode or settings.agent_execution_mode!='autonomous' or not settings.agent_auto_execute_enabled:
        return None,request
    if request.start_new_task or request.prompt_source_run_id or request.production_plan_id or request.amazon_plan_id:return None,request
    rows=await recent(db,conv)
    fingerprint=digest(request.submission_payload())
    # Receipt lookup is not limited to the latest 30 runs; a late HTTP retry is still idempotent.
    stored=await db.scalar(select(AgentRun).where(AgentRun.conversation_id==conv.id,
        AgentRun.organization_id==conv.organization_id,AgentRun.user_id==conv.user_id,
        AgentRun.result_json['continuation_receipts'][request.client_request_id].as_string().is_not(None)).limit(1))
    if stored and all(r.id!=stored.id for r in rows):rows.append(stored)
    for row in rows:
        receipt=(row.result_json.get('continuation_receipts') or {}).get(request.client_request_id)
        if receipt:
            if receipt!=fingerprint:raise AppError('agent.idempotency_conflict','该请求编号已用于其他回复。',409)
            if row.status=='planning':await runtime.advance(db,settings,redis,row,permissions)
            return row,request
    if not policy.continuation(request.content):
        if not request.reply_to_run_id and not request.attachment_ids and not request.parent_output_id and rows and rows[0].status in policy.PENDING:
            import re
            if not re.search(r'新建|新的任务|另外|再帮我|另一个任务',request.content):
                return None,request.model_copy(update={'reply_to_run_id':rows[0].id,'reply_to_revision':rows[0].revision})
        return None,request
    if request.attachment_ids or request.parent_output_id:return None,request
    if request.reply_to_run_id:
        source=await runtime.owned_run(db,conv.organization_id,conv.user_id,request.reply_to_run_id,lock=True)
        if source.conversation_id!=conv.id:raise AppError('agent.reply_not_found','待执行方案不属于当前会话。',404)
    else:source=next(iter(rows),None)
    if source is None:raise AppError('agent.no_pending_action','当前没有待继续的任务，请说明新的生成或修改要求。',409)
    if request.reply_to_run_id and source.revision!=request.reply_to_revision:
        raise AppError('agent.reply_stale','待执行方案已更新，请刷新后再继续。',409)
    # Same run remains authoritative while its native Jobs are running or unknown.
    if source.status in {'planning','waiting_jobs','submitted','ready_to_submit','remote_unknown'}:
        receipts=dict(source.result_json.get('continuation_receipts') or {})
        if len(receipts)>=50:raise AppError('agent.continuation_limit','本任务回复已达上限。',409)
        receipts[request.client_request_id]=fingerprint
        source.result_json={**source.result_json,'continuation_receipts':receipts}
        now=datetime.now(timezone.utc)
        db.add(HermesMessage(conversation_id=conv.id,organization_id=conv.organization_id,user_id=conv.user_id,
            role='user',content=request.content,metadata_json={'reply_to_run_id':source.id,'sent_at':now.isoformat()},created_at=now))
        db.add(HermesMessage(conversation_id=conv.id,organization_id=conv.organization_id,user_id=conv.user_id,
            role='assistant',content='上游状态尚未确认，不会重复提交。' if source.status=='remote_unknown' else '任务已在处理中，继续等待原任务结果。',
            metadata_json={'run_id':source.id,'sent_at':now.isoformat()},created_at=now))
        await db.commit()
        return source,request
    p=source.plan_json or {}
    decision=(source.result_json.get('planner_decision') or {}).get('capability_plan') or {}
    resumable_review=source.status in {'awaiting_review','awaiting_confirmation'} and not p.get('needs_input') and all(
        a['tool'] in REGULAR_TOOLS for a in p.get('actions',[]))
    resumable_model=source.status in policy.CLARIFICATION and decision.get('steps') and (
        policy.approval_question(p.get('summary')) or p.get('needs_input')==['parent_output_id'])
    if not resumable_review and not resumable_model:
        if source.status in policy.CLARIFICATION:
            return None,request.model_copy(update={'reply_to_run_id':source.id,'reply_to_revision':source.revision})
        raise AppError('agent.no_pending_action','当前没有待继续的方案，请说明新的修改要求；不会重复生成旧任务。',409)
    receipts=dict(source.result_json.get('continuation_receipts') or {})
    if len(receipts)>=50:raise AppError('agent.continuation_limit','本方案回复已达上限，请新建任务。',409)
    receipts[request.client_request_id]=fingerprint
    message=HermesMessage(conversation_id=conv.id,organization_id=conv.organization_id,user_id=conv.user_id,
        role='user',content=request.content,metadata_json={'reply_to_run_id':source.id,'sent_at':datetime.now(timezone.utc).isoformat()},created_at=datetime.now(timezone.utc))
    db.add(message)
    state=source.result_json.get('auto_execution') or auto_execution.grant(settings,request)
    if state.get('version')!=2:state=auto_execution.grant(settings,request)
    state={**state,'review_before_generation':state.get('review_before_generation',False) if resumable_review else False}
    source.result_json={**source.result_json,'auto_execution':state,'continuation_receipts':receipts}
    source.revision+=1
    if resumable_review:
        source.result_json={**source.result_json,'reviewed_proposal_id':source.proposal_id}
        source.status='ready_to_submit'
        await runtime.event(db,source,'user_review_approved',{'proposal_id':source.proposal_id})
        await db.commit()
    else:
        proposal=await db.get(HermesProposal,source.proposal_id) if source.proposal_id else None
        if proposal and proposal.status=='pending':proposal.status='cancelled'
        source.result_json={**source.result_json,'autonomy':{**source.result_json.get('autonomy',{}),'consumed_decision':None}}
        source.status='planning'
        await runtime.event(db,source,'pending_action_resumed',{'reused_planner_job':True})
        await db.commit()
        await runtime.advance(db,settings,redis,source,permissions)
    db.add(HermesMessage(conversation_id=conv.id,organization_id=conv.organization_id,user_id=conv.user_id,
        role='assistant',content=(source.plan_json or {}).get('summary','继续原任务'),metadata_json={'run_id':source.id,
            'sent_at':datetime.now(timezone.utc).isoformat()},created_at=datetime.now(timezone.utc)))
    await db.commit()
    return source,request
