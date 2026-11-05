"""Durable control plane. DB commits precede checkpointed side-effect completion."""
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
import hashlib
import hmac

from sqlalchemy import select

from app.core.errors import AppError
from app.models.agent_control import AgentRun, AgentEvent, AgentJobLink
from app.models.hermes_agent import HermesConversation, HermesMessage, HermesProposal, HermesToolAudit
from app.models.tasks import Job
from app.agents.contracts import AgentPlan, IntentDecision, RunResponse, ChatImageAction
from app.agents.adapters import batch_tryon as batch
from app.agents.planner import mock_intent, parse_intent_result
from app.agents.graphs.batch_tryon import build_plan
from app.agents.graphs.supervisor import build_graph
from app.agents.tool_registry import execute, validate_action
from app.services.hermes_agent_service import audit_safe_snapshot
from app.services.proposal_confirmation_service import proposal_state_matches, require_proposal_owner
from app.agents.execution_policy import autonomous

UTC = timezone.utc
TERMINAL = {"completed", "failed", "cancelled", "stale", "remote_unknown", "needs_input", "blocked"}


def enabled(settings):
    if not settings.agent_control_enabled:
        raise AppError("agent.disabled", "AI 总控尚未启用，原专业工作台可继续使用。", 503)


@asynccontextmanager
async def checkpoint_store(settings, *, setup=False):
    if not settings.agent_checkpoint_url:
        raise AppError("agent.checkpoint_required", "尚未配置持久化 Checkpointer；不会降级为内存存储。", 503)
    url = settings.agent_checkpoint_url.get_secret_value()
    if url.startswith("sqlite:///"):
        if settings.environment == "production":
            raise AppError("agent.checkpoint_unsupported", "SQLite Checkpointer 仅用于隔离开发和测试。", 503)
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        async with AsyncSqliteSaver.from_conn_string(url[len("sqlite:///"):]) as saver:
            await saver.setup()
            yield saver
    elif url.startswith(("mysql://", "mysql+asyncmy://")):
        from langgraph.checkpoint.mysql.asyncmy import AsyncMySaver
        async with AsyncMySaver.from_conn_string(url.replace("mysql+asyncmy://", "mysql://", 1)) as saver:
            # Never run framework DDL as a side effect of an API request.
            if setup:
                await saver.setup()
            yield saver
    else:
        raise AppError("agent.checkpoint_unsupported", "当前阶段只支持经验证的 MySQL 或隔离 SQLite 配置。", 503)


async def conversation(db, org, user, conversation_id, *, lock=False):
    statement = select(HermesConversation).where(HermesConversation.id == conversation_id,
        HermesConversation.organization_id == org, HermesConversation.user_id == user,
        HermesConversation.controller_type == "langgraph")
    row = await db.scalar(statement.with_for_update().execution_options(populate_existing=True) if lock else statement)
    if row is None:
        raise AppError("agent.conversation_not_found", "会话不存在或无权访问。", 404)
    return row


async def owned_run(db, org, user, run_id, *, lock=False):
    row = await db.scalar(select(AgentRun).where(AgentRun.id == run_id, AgentRun.organization_id == org,
        AgentRun.user_id == user))
    if row is None:
        raise AppError("agent.run_not_found", "执行记录不存在或无权访问。", 404)
    # Consistent lock order across message/confirm/cancel paths.
    await conversation(db, org, user, row.conversation_id, lock=lock)
    if lock:
        row = await db.scalar(select(AgentRun).where(AgentRun.id == row.id).with_for_update().execution_options(populate_existing=True))
    return row


async def event(db, run, event_type, payload=None, *, key=None):
    key = key or f"{run.revision}:{event_type}"
    if not await db.scalar(select(AgentEvent.id).where(AgentEvent.run_id == run.id, AgentEvent.event_key == key)):
        db.add(AgentEvent(run_id=run.id, event_key=key, event_type=event_type,
                          payload=audit_safe_snapshot(payload or {}), created_at=datetime.now(UTC)))


def confirmation_token(settings, run, proposal):
    content = f"{run.id}:{proposal.id}:{run.user_id}:{run.organization_id}:{proposal.expected_state_signature}"
    return hmac.new(settings.jwt_secret.get_secret_value().encode(), content.encode(), hashlib.sha256).hexdigest()


async def _context(db, run):
    conv = await conversation(db, run.organization_id, run.user_id, run.conversation_id)
    context=await conversation_context(db, conv)
    context={**context,'pending_action':(run.result_json.get('reply_context') or {}).get('pending_action_snapshot')}
    if run.selection_json.get('start_new_task') and not run.selection_json.get('parent_output_id') and not run.selection_json.get('use_batch_inputs'):
        selected=set(run.selection_json.get('attachment_ids',[]))
        context={**context,'outputs':[],'history':[],'assets':[a for a in context['assets'] if a['attachment_id'] in selected]}
    return context


async def conversation_context(db, conv):
    if conv.mode == "chat":
        from app.agents.adapters.chat import context
        return await context(db, conv)
    if conv.context_project_id:
        return await batch.read_context(db, conv.organization_id, conv.user_id, conv.context_project_id)
    from app.agents.adapters.attachment import read_context
    return await read_context(db, conv.organization_id, conv.user_id, conv.listing_image_project_id)


async def _execute_committed(db, settings, redis, run, plan, permissions, authorized):
    if not authorized:
        raise AppError("agent.confirmation_required", "缺少服务端确认凭据。", 409)
    # LangGraph resumes after a durable checkpoint; reload the conversation under
    # its existing lock before allocating its backing project or gallery numbers.
    # A second confirmation must not reuse an ORM snapshot from before the wait.
    await conversation(db, run.organization_id, run.user_id, run.conversation_id, lock=True)
    proposal = await db.get(HermesProposal, run.proposal_id)
    if proposal.status == "applied":
        return dict(proposal.result_json)
    if batch.digest(plan) != batch.digest(run.plan_json):
        raise AppError("agent.plan_integrity", "执行计划与已确认快照不一致，未提交任务。", 409)
    if proposal.status != "pending" or run.status not in {"awaiting_confirmation", "submitting",'ready_to_submit','awaiting_review'}:
        raise AppError("agent.proposal_not_pending", "计划已处理，不能重复执行。", 409)
    typed = AgentPlan.model_validate(plan)
    if any(validate_action(action)[0].model_cost for action in typed.actions) or any(a.tool=='review_tryon_samples' for a in typed.actions) and typed.image_count>0:
        # Native submission performs missing-idempotency-key SELECT FOR UPDATE before
        # quota reservation. In MySQL RR, simultaneous inserts can deadlock on the
        # same index gap. Acquire the existing billing row first (only this short
        # Agent submission transaction), never serialize Provider execution.
        from app.models.quota import QuotaAccount
        await db.scalar(select(QuotaAccount).where(QuotaAccount.organization_id==run.organization_id)
            .with_for_update().execution_options(populate_existing=True))
    results, ids = [], []
    for index, action in enumerate(typed.actions):
        spec, args = validate_action(action)
        if action.tool=='generate_aplus' and autonomous(run):
            from app.agents import amazon
            conv=await conversation(db,run.organization_id,run.user_id,run.conversation_id)
            reviewed=run.result_json.get('reviewed_proposal_id')==run.proposal_id
            human=(await db.get(HermesMessage,run.source_message_id)).content
            row,p=await amazon.record(db,conv,args.plan_id)
            approved=all(row.metadata_json['approvals'].get(m.id,{}).get('signature')==amazon.module_signature(p,m)
                for m in p.modules if m.id in args.module_ids)
            if not approved:
                revision_requested=set(run.result_json.get('amazon_revision_requested',[]))==set(args.module_ids)
                if not reviewed and not revision_requested and not amazon.direct_generation_requested(human) and not run.result_json.get('suite_auto_generation'):
                    raise AppError('agent.module_unconfirmed','请先确认当前图片方案。',409)
                await amazon.authorize_review(db,conv,args,source='user_plan_review' if reviewed else 'user_module_revision' if revision_requested else 'user_direct_request')
        context = await _context(db, run)
        # Even a forged checkpoint cannot change the conversation's write target.
        pid = getattr(args, "project_id", None) or getattr(getattr(args, "workflow", None), "project_id", None)
        if pid and pid != context["project_id"]:
            raise AppError("agent.context_mismatch", "工具项目与当前会话不一致。", 409)
        result = await execute(db, settings, redis, org=run.organization_id, user=run.user_id,
            permissions=permissions, action=action, action_key=f"agent:{run.id}:{proposal.id}:{index}", confirmed=True, conversation_id=run.conversation_id,
            autonomous_production=autonomous(run),sample_review_required=(run.result_json.get('auto_execution') or {}).get('sample_review_required',False),
            human_request=(await db.get(HermesMessage,run.source_message_id)).content,card_review=run.selection_json.get('sample_review'),run_id=run.id)
        results.append({"tool": action.tool, "result": result})
        if action.tool=='save_aplus_plan' and result.get('amazon_plan_id'):
            from app.agents import amazon
            conv=await conversation(db,run.organization_id,run.user_id,run.conversation_id)
            row,p=await amazon.record(db,conv,result['amazon_plan_id'],True)
            if p.design_version=='professional-aplus-v2':
                trace=(typed.capability_context or {}).get('skills') or []
                row.metadata_json={**row.metadata_json,'skill_trace':trace,'quality_review':run.result_json.get('aplus_design_review')}
                await event(db,run,'aplus_design_applied',{'plan_id':row.id,'skills':trace,'modules':run.result_json.get('aplus_design_review',{}).get('modules',[])})
        for jid in result.get("job_ids", []):
            if action.tool=='generate_aplus' and result.get('reused'):
                # Keep original chat gallery slots and Run ownership. A repeated
                # acknowledgement is a receipt, not another generated result.
                continue
            ids.append(jid)
            if not await db.scalar(select(AgentJobLink.id).where(AgentJobLink.run_id == run.id, AgentJobLink.job_id == jid)):
                db.add(AgentJobLink(run_id=run.id, job_id=jid, role="planner" if action.tool == "plan_intent" else
                    "suggestions" if action.tool == 'suggest_creative_directions' else "business"))
        db.add(HermesToolAudit(conversation_id=run.conversation_id, proposal_id=proposal.id,
            organization_id=run.organization_id, user_id=run.user_id, listing_image_project_id=None,
            tool_name=action.tool, arguments_json=audit_safe_snapshot(action.arguments),
            result_json=audit_safe_snapshot(result), status="succeeded", created_at=datetime.now(UTC)))
    # UI-only upload receipts belong to this Run even if a later planner Job is
    # submitted. Do not retain obsolete planner actions or alter Job ownership.
    upload_receipts = [a for a in run.result_json.get("actions", []) if a.get("tool") == "guide_batch_inputs"]
    result = {"actions": [*upload_receipts, *results], "job_ids": list(dict.fromkeys(ids)),
              **({"autonomy": run.result_json["autonomy"]} if "autonomy" in run.result_json else {})}
    for key in ('auto_execution','execution_notice','reply_context','submission_fingerprint','prompt_versions','continuation_receipts','reviewed_proposal_id','amazon_revision_requested','suite_auto_generation','light_routing','retry_of_job_id','aplus_clarification','brief_question_answered','aplus_design_review'):
        if key in run.result_json:result[key]=run.result_json[key]
    if 'confirmation_scope' in run.result_json:result['confirmation_scope']=run.result_json['confirmation_scope']
    submitted_inputs=list(run.result_json.get('submitted_import_keys',[]))
    for receipt in results:
        data=receipt['result']
        if receipt['tool']=='analyze_chat_assets' and data.get('import_input_key'):
            current={e['asset_id'] for e in (context.get('batch_input_manifest') or {}).get('entries',[]) if e.get('enabled',True)}
            if current and current<=set(data.get('understanding_asset_ids',[])):
                submitted_inputs.append(data['import_input_key'])
    if submitted_inputs:result['submitted_import_keys']=list(dict.fromkeys(submitted_inputs))
    conv = await conversation(db, run.organization_id, run.user_id, run.conversation_id)
    if conv.mode == "chat":
        prior_runs = list((await db.scalars(select(AgentRun).where(AgentRun.conversation_id == conv.id)
            .with_for_update().execution_options(populate_existing=True))).all())
        last_number = max((s["number"] for r in prior_runs for s in r.result_json.get("gallery_slots", [])), default=0)
        images = list((await db.scalars(select(Job).where(Job.id.in_(ids), Job.capability != "text_generation")
            .order_by(Job.created_at, Job.client_item_id, Job.id))).all())
        result["gallery_slots"] = list(run.result_json.get("gallery_slots", [])) + [
            {"job_id": j.id, "number": last_number+i+1} for i, j in enumerate(images)]
    for item in results:
        if item["result"].get("batch_id"):
            result["batch_id"] = item["result"]["batch_id"]
    run.result_json = result
    run.status = "waiting_jobs" if ids else "completed"
    if ids and autonomous(run):await event(db,run,'submitted',{'job_ids':ids,'status':'submitted'})
    run.revision += 1
    proposal.status = "applied"
    proposal.result_json = result
    proposal.applied_at = datetime.now(UTC)
    await event(db, run, "tools_committed", {"tools": [a.tool for a in typed.actions], "job_count": len(ids)})
    if typed.capability_context:
        await event(db, run, "capability_business_submitted", {"capability_id": typed.capability_context.get("pending_capability"),
            "job_ids": ids, "tools": [a.tool for a in typed.actions], "status": run.status})
    await db.commit()  # Critical: durable business side effects before LangGraph records success.
    return result


async def advance(db, settings, redis, run, permissions, *, resume=False):
    run = await db.scalar(select(AgentRun).where(AgentRun.id == run.id).with_for_update().execution_options(populate_existing=True))
    if not resume and run.status != "planning":
        return
    if run.graph_version not in {"phase1-v1", "capabilities-v1"}:
        raise AppError("agent.graph_version_mismatch", "该执行记录需要对应版本的总控，不会用新流程重放收费动作。", 409)
    inflight = run.result_json.get("autonomy", {})
    if inflight.get("inflight"):
        started = datetime.fromisoformat(inflight["inflight_at"])
        if datetime.now(UTC)-started > timedelta(seconds=45):
            run.status, run.error_code = "failed", "agent.tool_interrupted"
            await event(db, run, "capability_interrupted", {"note": "不自动重发未知状态的外部查询"})
            await db.commit()
        return
    context = await _context(db, run)
    async def identify():
        if run.graph_version == "capabilities-v1":
            return {"intent": "generate", "summary": "从获准能力目录规划，不使用固定意图工作流路由"}
        if run.result_json.get("planner_decision"):
            return IntentDecision.model_validate(run.result_json["planner_decision"]).model_dump()
        if run.planner_mode == "existing_text":
            return {"intent": "model_plan", "summary": "请求真实文本规划"}
        if run.selection_json.get("chat_mode"):
            from app.agents.intent_router import IntentRouter
            intent = IntentRouter.simulate(run.selection_json["content"], bool(run.selection_json.get("parent_output_id"))).model_dump()
        else:
            intent = mock_intent(run.selection_json["content"]).model_dump()
        await event(db, run, "intent_identified", {"intent": intent["intent"]})
        return intent

    linked_ids = list((await db.scalars(select(AgentJobLink.job_id).join(AgentRun, AgentRun.id == AgentJobLink.run_id)
        .where(AgentRun.conversation_id == run.conversation_id))).all())
    async def plan(intent):
        from app.agents.aplus_briefing import question as brief_question
        clarification=brief_question(run,context)
        if clarification:
            await event(db,run,'brief_clarification',run.result_json['aplus_clarification'])
            return clarification.model_dump(mode='json')
        if run.selection_json.get('retry_image_job_id'):
            from app.agents.image_retry import plan as retry_plan
            return (await retry_plan(db,settings,run,context)).model_dump(mode='json')
        if run.selection_json.get('prompt_source_run_id'):
            from app.agents.prompt_history import saved_plan
            return (await saved_plan(db,settings,run,context)).model_dump(mode='json')
        if run.selection_json.get('request_mode') == 'suggest':
            from app.agents.creative_assistance import build_plan as build_suggestions
            return (await build_suggestions(db, settings, run, context)).model_dump(mode='json')
        if run.graph_version == "capabilities-v1":
            from app.agents.capabilities.orchestrator import build_dynamic_plan
            return (await build_dynamic_plan(db, settings, redis, run, permissions, context)).model_dump(mode="json")
        if run.selection_json.get("chat_mode"):
            from app.agents.intent_router import build_chat_plan
            value = await build_chat_plan(db, settings, run.organization_id, run.user_id, context, run.selection_json, intent)
            return value.model_dump(mode="json")
        return build_plan(intent, context, run.selection_json, run.id, linked_ids).model_dump(mode="json")

    async def execute_plan(value):
        return await _execute_committed(db, settings, redis, run, value, permissions, resume)

    from langgraph.types import Command
    from langsmith import tracing_context
    async with checkpoint_store(settings) as saver:
        graph = build_graph(checkpointer=saver, identify=identify, plan=plan, execute=execute_plan)
        config = {"configurable": {"thread_id": run.id}, "recursion_limit": 12}
        with tracing_context(enabled=False):
            if resume:
                state = await graph.aget_state(config)
                if not state.tasks:
                    if run.status in TERMINAL or (await db.get(HermesProposal, run.proposal_id)).status == "applied":
                        return
                    raise AppError("agent.checkpoint_mismatch", "确认检查点不存在；请重新规划，不会补发请求。", 409)
                interrupted = any(getattr(task, "interrupts", ()) for task in state.tasks)
                result = await graph.ainvoke(Command(resume={"approved": True}) if interrupted else None, config)
            else:
                result = await graph.ainvoke({"run_id": run.id, "request_hash": run.request_hash,
                    "decision": {}, "result": {}}, config)
    if not resume:
        if run.status == "cancelled":
            return
        typed = AgentPlan.model_validate(result["plan"])
        serialized = typed.model_dump(mode="json")
        context_signature = context['signature']
        scope = None
        if run.selection_json.get('chat_mode') and any(a.tool=='generate_chat_images' for a in typed.actions) and all(
            a.tool in {'generate_chat_images','show_message'} for a in typed.actions):
            from app.agents.adapters.chat import image_confirmation_context
            scope = 'chat-images-v1'
            context_signature = image_confirmation_context(context, serialized)
        elif run.selection_json.get('chat_mode') and any(a.tool=='analyze_chat_assets' for a in typed.actions) and all(
            a.tool in {'analyze_chat_assets','show_message'} for a in typed.actions):
            from app.agents.adapters.chat import analysis_confirmation_context
            scope = 'chat-analysis-v1'
            # The quote may have synchronized the manifest; bind its settled
            # assignments, then protect exactly these images at commit time.
            context_signature = analysis_confirmation_context(await _context(db,run), serialized)
        run.result_json = {**run.result_json, 'confirmation_scope':scope}
        signature = batch.digest({"context": context_signature, "plan": serialized})
        proposal = HermesProposal(conversation_id=run.conversation_id, source_message_id=run.source_message_id,
            organization_id=run.organization_id, user_id=run.user_id, listing_image_project_id=None,
            summary=typed.summary, actions_json=[a.model_dump(mode="json") for a in typed.actions],
            expected_state_signature=signature, status="pending", created_at=datetime.now(UTC), updated_at=datetime.now(UTC))
        db.add(proposal)
        await db.flush()
        run.proposal_id, run.plan_json, run.status = proposal.id, typed.model_dump(mode="json"), "ready_to_submit" if autonomous(run) else "awaiting_confirmation"
        from app.agents.prompt_history import remember_plan
        remember_plan(run,typed)
        if autonomous(run) and (run.result_json.get('auto_execution') or {}).get('review_before_generation') and any(
            a.tool in {'generate_chat_images','generate_chat_tryon','generate_aplus','submit_tryon_batch'} for a in typed.actions):
            run.status='awaiting_review'
            run.result_json={**run.result_json,'review_reason':'你要求先审核方案，审核通过后再生成。'}
        if autonomous(run) and any(a.tool=='generate_aplus' for a in typed.actions):
            from app.agents import amazon
            human=(await db.get(HermesMessage,run.source_message_id)).content
            args=next(a.arguments for a in typed.actions if a.tool=='generate_aplus')
            conv=await conversation(db,run.organization_id,run.user_id,run.conversation_id)
            row,p=await amazon.record(db,conv,args['plan_id'])
            approved=all(row.metadata_json['approvals'].get(m.id,{}).get('signature')==amazon.module_signature(p,m)
                for m in p.modules if m.id in args['module_ids'])
            revision_requested=set(run.result_json.get('amazon_revision_requested',[]))==set(args['module_ids'])
            if not approved and not revision_requested and not amazon.direct_generation_requested(human) and not run.result_json.get('suite_auto_generation'):
                run.status='awaiting_review'
                run.result_json={**run.result_json,'review_reason':'图片方案已就绪，说“可以”或点击生成即可。'}
        if typed.capability_context and typed.capability_context.get("readonly_complete"):
            # Only the server capability loop can complete approved zero-cost reads without confirmation.
            if any(a.tool != "show_message" for a in typed.actions) or typed.may_charge:
                raise AppError("agent.auto_execution_denied", "不可自动确认写入或收费动作。", 403)
            run.status, proposal.status = "completed", "applied"
            # The final message is delivered below, not an unexecuted image tool.
            # Keep its receipt so the UI does not show "waiting" on a finished read.
            run.result_json = {**run.result_json, "actions": [
                *[a for a in run.result_json.get("actions", []) if a.get("tool") != "show_message"],
                *[{"tool": a.tool, "result": {"message": a.arguments["message"], "readonly_complete": True}}
                  for a in typed.actions]]}
            proposal.result_json = {"readonly_complete": True}
        if typed.blocked_reason or typed.needs_input:
            run.status = ("failed" if autonomous(run) else "blocked") if typed.blocked_reason else ("awaiting_clarification" if autonomous(run) else "needs_input")
            if autonomous(run) and 'sample_review' in typed.needs_input:run.status='awaiting_review'
            if typed.blocked_reason and autonomous(run):run.error_code=typed.blocked_reason
            proposal.status = "cancelled"
        await event(db, run, "plan_ready", {"summary": typed.summary, "may_charge": typed.may_charge})
        if autonomous(run):await event(db,run,run.status,{'proposal_id':proposal.id})
        db.add(HermesMessage(conversation_id=run.conversation_id, organization_id=run.organization_id,
            user_id=run.user_id, role="assistant", content=typed.summary,
            metadata_json={"run_id": run.id, "planner_mode": run.planner_mode, "sent_at":datetime.now(UTC).isoformat()}, created_at=datetime.now(UTC)))
        await db.commit()


async def create_run(db, settings, redis, conv, request, permissions):
    fingerprint = batch.digest(request.submission_payload())
    previous = await db.scalar(select(AgentRun).where(AgentRun.conversation_id == conv.id,
        AgentRun.client_request_id == request.client_request_id))
    if previous:
        if previous.request_hash != fingerprint:
            raise AppError("agent.idempotency_conflict", "该请求编号已经用于其他内容。", 409)
        if previous.status == "planning":
            await advance(db, settings, redis, previous, permissions)
        return previous
    if request.retry_image_job_id:
        # Conversation is locked by the owning API. Different browser request
        # IDs must not create two charged retries of one failed Job.
        repeated=await db.scalar(select(AgentRun).where(AgentRun.conversation_id==conv.id,
            AgentRun.organization_id==conv.organization_id,AgentRun.user_id==conv.user_id,
            AgentRun.selection_json['retry_image_job_id'].as_string()==request.retry_image_job_id))
        if repeated:return repeated
    if request.chat_mode and request.use_batch_inputs and request.client_request_id.startswith('imports:'):
        # Same conversation is locked by the API. Coalesce automatic import
        # continuations, not user chat or independent image Jobs. A later poll
        # will submit the latest manifest after this preparation has settled.
        preparing = (await db.scalars(select(AgentRun).where(
            AgentRun.conversation_id==conv.id, AgentRun.organization_id==conv.organization_id,
            AgentRun.user_id==conv.user_id,
            AgentRun.status.in_(['planning','ready_to_submit','submitted','waiting_jobs'])))).all()
        if any((r.selection_json.get('use_batch_inputs') or r.selection_json.get('creative_module')=='batch_tryon') and
               (r.status=='planning' or any(a['tool'] in {'plan_intent','analyze_chat_assets'}
                                            for a in (r.plan_json or {}).get('actions',[]))) for r in preparing):
            raise AppError('agent.import_preparation_pending','当前素材仍在准备中，新增素材已保存，完成后将继续处理。',409)
    from app.agents import auto_execution
    from app.agents import creative_modules
    mode=await creative_modules.read(db,conv) if request.chat_mode else None
    prospective_mode=mode
    if mode and request.creative_module is not None and mode['module']!=request.creative_module:
        prospective_mode=creative_modules.describe(request.creative_module,mode['revision']+1)
    repeated=await auto_execution.duplicate(db,settings,conv,request,creative_context=prospective_mode)
    if repeated:return repeated
    original_request = request
    from app.agents.pending_actions import resume as resume_pending
    resumed,request=await resume_pending(db,settings,redis,conv,request,permissions)
    if resumed:return resumed
    from app.agents.creative_assistance import resolve_reply
    request, reply_context = await resolve_reply(db, conv, request)
    if reply_context and settings.agent_aplus_professional_enabled and request.creative_module in {None,'auto'}:
        import re
        source=await owned_run(db,conv.organization_id,conv.user_id,reply_context['source_run_id'])
        if (source.result_json.get('aplus_clarification') or {}).get('kind')=='deliverable':
            if re.search(r'A\s*\+',original_request.content,re.I):request=request.model_copy(update={'creative_module':'amazon_aplus'})
            elif re.search(r'Listing|附图|主副图',original_request.content,re.I):request=request.model_copy(update={'creative_module':'listing_images'})
    if conv.controller_type != "langgraph":
        raise AppError("agent.wrong_controller", "该会话不属于 LangGraph。", 409)
    context = await conversation_context(db, conv)
    if request.chat_mode and settings.agent_execution_mode=='autonomous' and not request.start_new_task and not request.attachment_ids and not request.parent_output_id:
        from app.agents.execution_policy import explicit_previous_output
        import re
        edit_intent=explicit_previous_output(request.content) or re.search(r'(?:背景|光线|服装|衣服).{0,4}(?:换成|改成|改为)|(?:更换|修改|调整|替换).{0,4}(?:背景|光线|衣服|服装)',request.content)
        if edit_intent:
            if context.get('outputs'):
                from app.agents.intent_router import number
                ordinal=re.search(r'第([0-9一二三四五六七八九十两]+)张',request.content)
                candidates=[o for o in context['outputs'] if o['number']==number(ordinal[1])] if ordinal else context['outputs'][-1:]
                if len(candidates)==1:request=request.model_copy(update={'parent_output_id':candidates[0]['id']})
            elif not request.reply_to_run_id:
                from app.agents.pending_actions import recent
                prior=next((r for r in await recent(db,conv) if r.selection_json.get('attachment_ids')),None)
                if prior:request=request.model_copy(update={'attachment_ids':prior.selection_json['attachment_ids']})
    selected = set(request.template_asset_ids + request.garment_asset_ids)
    if selected - {a["id"] for a in context["assets"]}:
        raise AppError("agent.invalid_selection", "选择的素材不属于当前项目。", 404)
    if request.chat_mode != (conv.mode == "chat"):
        raise AppError("agent.mode_mismatch", "会话模式不匹配，请刷新后重试。", 409)
    attachment_snapshot = []
    if request.chat_mode:
        selected_attachments = {a["attachment_id"]: a for a in context["assets"]}
        if set(request.attachment_ids) - set(selected_attachments):
            raise AppError("agent.asset_not_found", "附件不属于当前会话。", 404)
        attachment_snapshot = [selected_attachments[i] for i in request.attachment_ids]
        if request.parent_output_id and request.parent_output_id not in {o["id"] for o in context["outputs"]}:
            raise AppError("agent.output_not_found", "结果不属于当前会话。", 404)
    message = HermesMessage(conversation_id=conv.id, organization_id=conv.organization_id, user_id=conv.user_id,
        role="user", content=request.content, metadata_json={"attachments": attachment_snapshot,
            "parent_output_id": request.parent_output_id, "sent_at":datetime.now(UTC).isoformat(),
            **({'reply_to_run_id':request.reply_to_run_id,'request_mode':original_request.request_mode}
                if request.reply_to_run_id else {})}, created_at=datetime.now(UTC))
    message.content = original_request.content
    db.add(message)
    if request.chat_mode and conv.title == "新的图片创作":
        conv.title = request.content.strip().splitlines()[0][:60]
    await db.flush()
    for item in attachment_snapshot:
        linked = await db.get(HermesMessage, item["attachment_id"])
        linked.metadata_json = {**linked.metadata_json, "submitted": True}
    run = AgentRun(conversation_id=conv.id, organization_id=conv.organization_id, user_id=conv.user_id,
        source_message_id=message.id, client_request_id=request.client_request_id, request_hash=fingerprint,
        planner_mode=settings.agent_control_planner, selection_json=request.model_dump(mode="json"),
        graph_version="capabilities-v1" if request.chat_mode and settings.agent_dynamic_capabilities_enabled and request.request_mode != 'suggest' and not request.prompt_source_run_id and not request.retry_image_job_id else "phase1-v1")
    if request.chat_mode:
        from app.agents import creative_modules
        mode=await creative_modules.change(db,conv,request.creative_module) if request.creative_module is not None else await creative_modules.read(db,conv)
        if mode['revision'] or request.creative_module is not None:run.selection_json={**run.selection_json,'_creative_context':mode}
        if request.use_batch_inputs and context.get('batch_input_manifest'):
            from app.agents.batch_manifest import material_key
            run.selection_json={**run.selection_json,'_batch_input_key':material_key(context['batch_input_manifest'])}
        if settings.agent_control_decision_enabled and run.graph_version=='capabilities-v1':
            from app.agents.light_router import snapshot
            run.selection_json={**run.selection_json,'_model_policy':await snapshot(settings,redis,run.organization_id)}
    consent_request=original_request
    if reply_context and original_request.review_before_generation is None:
        prior=await owned_run(db,conv.organization_id,conv.user_id,reply_context['source_run_id'])
        if prior.status=='awaiting_review':consent_request=original_request.model_copy(update={'review_before_generation':True})
    consent=auto_execution.grant(settings,consent_request)
    if consent:
        run.result_json={'auto_execution':consent}
        if consent.get('version')==2:run.selection_json={**run.selection_json,'_execution_mode':'autonomous'}
    run.result_json={**(run.result_json or {}),'suite_auto_generation':bool(request.chat_mode and settings.agent_execution_mode=='autonomous'),
        'submission_fingerprint':auto_execution.request_digest(original_request.model_dump(mode='json')),
        **({'reply_context':reply_context} if reply_context else {})}
    if request.chat_mode and settings.agent_aplus_professional_enabled and run.graph_version=='capabilities-v1':
        run.selection_json={**run.selection_json,'_aplus_professional':True}
        if reply_context:
            source=await owned_run(db,conv.organization_id,conv.user_id,reply_context['source_run_id'])
            prior=source.result_json.get('aplus_clarification') or source.result_json.get('brief_question_answered')
            if prior:
                run.result_json={**run.result_json,'brief_question_answered':prior}
                run.selection_json={**run.selection_json,'_brief_user_reply':original_request.content}
    db.add(run)
    await db.flush()
    await event(db, run, "created", {"planner_mode": run.planner_mode})
    await db.commit()
    identity = (run.organization_id, run.user_id, run.id)
    try:
        await advance(db, settings, redis, run, permissions)
    except AppError as error:
        run.status, run.error_code = "failed", error.code
        await event(db, run, "planning_failed", {"code": error.code})
        await db.commit()
        raise
    except Exception:
        await db.rollback()
        current = await owned_run(db, *identity, lock=True)
        current.status, current.error_code = "failed", "agent.planning_unavailable"
        await event(db, current, "planning_failed", {"code": current.error_code})
        await db.commit()
        raise AppError("agent.planning_unavailable", "规划或检查点暂时不可用；未发送图片请求。请检查配置后重新规划。", 503) from None
    return run


async def confirm(db, settings, redis, run, request, permissions):
    proposal = await db.scalar(select(HermesProposal).where(HermesProposal.id == run.proposal_id)
        .with_for_update().execution_options(populate_existing=True))
    if not proposal or not hmac.compare_digest(request.confirmation_token, confirmation_token(settings, run, proposal)):
        raise AppError("agent.invalid_confirmation", "确认凭据无效。", 403)
    require_proposal_owner(proposal, run.organization_id, run.user_id)
    if request.state_signature != proposal.expected_state_signature:
        raise AppError("agent.invalid_confirmation", "确认的计划签名不一致。", 409)
    if proposal.status == "applied":
        return  # Same confirmation is replay-safe, even after browser/backend restart.
    if run.planner_mode != settings.agent_control_planner:
        raise AppError('agent.planner_changed','当前计划来自旧规划模式，请重新发送需求；不会执行旧的Mock计划。',409)
    if run.status not in {"awaiting_confirmation",'ready_to_submit','awaiting_review'} or proposal.status != "pending" or request.expected_revision != run.revision:
        raise AppError("agent.revision_conflict", "计划状态已改变，请刷新。", 409)
    created = proposal.created_at.replace(tzinfo=UTC) if proposal.created_at.tzinfo is None else proposal.created_at
    if datetime.now(UTC) - created > timedelta(hours=1):
        raise AppError("agent.confirmation_expired", "确认已过期，请重新规划。", 409)
    context = await _context(db, run)
    context_signature = context['signature']
    if run.result_json.get('confirmation_scope')=='chat-images-v1':
        from app.agents.adapters.chat import image_confirmation_context
        context_signature = image_confirmation_context(context, run.plan_json)
    elif run.result_json.get('confirmation_scope')=='chat-analysis-v1':
        from app.agents.adapters.chat import analysis_confirmation_context
        context_signature = analysis_confirmation_context(context, run.plan_json)
    signature = batch.digest({"context": context_signature, "plan": run.plan_json})
    if run.graph_version == "capabilities-v1":
        from app.agents.capabilities.orchestrator import verify_confirmation
        verify_confirmation(settings, run, permissions)
    if not proposal_state_matches(proposal, signature):
        proposal.status, run.status = "stale", "stale"
        await event(db, run, "stale")
        await db.commit()
        raise AppError("agent.plan_stale", "素材或项目已改变，请重新规划，不会使用旧计划提交。", 409)
    if run.selection_json.get("chat_mode") and run.plan_json.get("budget"):
        from app.agents.adapters import chat
        from app.services.billing_service import estimate_response
        for action in AgentPlan.model_validate(run.plan_json).actions:
            if action.tool == "generate_chat_images":
                current_budget = await chat.quote(db, run.organization_id, ChatImageAction.model_validate(action.arguments))
            elif action.tool == 'generate_aplus':
                from app.agents import amazon
                from app.agents.amazon_contracts import GenerateAPlus
                conv=await conversation(db,run.organization_id,run.user_id,run.conversation_id)
                current_budget=await amazon.image_quote(db,conv,GenerateAPlus.model_validate(action.arguments),require_approval=not autonomous(run))
            elif action.tool in {"plan_intent", 'suggest_creative_directions'}:
                from app.services.resource_pool_service import resolve_operation_model_code
                current_model=await resolve_operation_model_code(db,organization_id=run.organization_id,
                    operation_code='listing.plan',capability='text_generation',
                    additional_capabilities={'vision_input'} if action.arguments.get('reference_asset_ids') else set(),
                    preferred_model_code=(action.arguments.get('model_code') if run.selection_json.get('_model_policy') and action.tool=='plan_intent' else settings.agent_control_text_model))
                if current_model != run.plan_json['budget'].get('model_code'):
                    raise AppError('agent.text_model_changed','推理模型已调整，请重新发送需求并确认当前费用。',409)
                current_budget = (await estimate_response(db, organization_id=run.organization_id, operation_code="listing.plan",
                    quantity=1, factors={"model": run.plan_json["budget"].get("model_code", ""), "resource_pool": "platform"})).model_dump(mode="json")
            elif action.tool=='review_tryon_samples':
                from app.agents import samples
                conv=await conversation(db,run.organization_id,run.user_id,run.conversation_id)
                current_budget=await samples.quote(db,conv,samples.ReviewSamples.model_validate(action.arguments))
            elif action.tool=='followup_batch_results':
                from app.agents import batch_followup
                conv=await conversation(db,run.organization_id,run.user_id,run.conversation_id)
                current_budget=await batch_followup.quote(db,conv,batch_followup.BatchFollowup.model_validate(action.arguments))
            elif action.tool in {'analyze_chat_assets','generate_chat_tryon'}:
                from app.agents import production
                conv=await conversation(db,run.organization_id,run.user_id,run.conversation_id)
                current_budget=await (production.analyze_quote(db,conv,production.AnalyzeAssets.model_validate(action.arguments),settings)
                    if action.tool=='analyze_chat_assets' else production.image_quote(db,conv,production.PlanAction.model_validate(action.arguments),
                        autonomous=autonomous(run),sample_review_required=(run.result_json.get('auto_execution') or {}).get('sample_review_required',False)))
            else:
                continue
            if not current_budget["sufficient"]:
                raise AppError("agent.insufficient_budget", "当前可用额度不足，未发送模型请求。", 409)
            if current_budget["estimated_cost"] != run.plan_json["budget"]["estimated_cost"] and not autonomous(run):
                raise AppError("agent.price_changed", "费用规则已变化，请重新生成计划并确认。", 409)
    identity = (run.organization_id, run.user_id, run.id)
    if run.status=='awaiting_review' and any(a['tool']=='generate_aplus' for a in run.plan_json.get('actions',[])):
        run.result_json={**run.result_json,'reviewed_proposal_id':run.proposal_id}
    try:
        await advance(db, settings, redis, run, permissions, resume=True)
        if run.status == 'completed' and run.graph_version == 'capabilities-v1':
            from app.agents.capabilities.orchestrator import continue_after_jobs
            await continue_after_jobs(db, settings, redis, run, permissions)
    except AppError as error:
        await db.rollback()
        current = await owned_run(db, *identity, lock=True)
        await event(db, current, "tool_blocked", {"code": error.code}, key=f"blocked:{error.code}:{current.revision}")
        await db.commit()
        raise
    except Exception as error:
        # The business commit may already have succeeded while a checkpoint write failed.
        # The durable proposal is authoritative; never submit a replacement Job here.
        await db.rollback()
        current = await owned_run(db, *identity, lock=True)
        durable = await db.get(HermesProposal, current.proposal_id)
        await event(db, current, "checkpoint_recovery_needed", {"business_committed": durable.status == "applied"})
        await db.commit()
        if durable.status == "applied":
            return
        if getattr(getattr(error,'orig',None),'args',(None,))[0] in {1205,1213}:
            raise AppError('agent.submission_conflict','任务提交遇到数据库并发冲突，未追加请求；请使用同一确认重试，不要新建批次。',409) from None
        raise AppError("agent.checkpoint_unavailable", "检查点暂时不可用，请刷新查看任务状态；不会自动补发模型请求。", 503) from None


async def cancel(db, run):
    if run.status in TERMINAL:
        return
    proposal = await db.get(HermesProposal, run.proposal_id) if run.proposal_id else None
    if proposal and proposal.status == "pending":
        proposal.status = "cancelled"
    # Deliberately does not cancel already submitted Jobs.
    run.status, run.revision = "cancelled", run.revision + 1
    await event(db, run, "cancelled", {"business_jobs_cancelled": False})
    await db.commit()


async def reconcile(db, settings, redis, run, permissions):
    if run.status == 'completed' and run.graph_version == 'capabilities-v1':
        from app.agents.capabilities.orchestrator import continue_after_jobs
        if await continue_after_jobs(db, settings, redis, run, permissions):
            return
    if run.status == "planning":
        await advance(db, settings, redis, run, permissions)
        return
    if run.status != "waiting_jobs":
        return
    links = (await db.scalars(select(AgentJobLink).where(AgentJobLink.run_id == run.id))).all()
    if not links:
        run.status, run.error_code = "failed", "agent.jobs_removed"
    else:
        jobs = await batch.read_jobs(db, run.organization_id, run.user_id, [l.job_id for l in links])
        cached=False
        for action in run.result_json.get('actions',[]):
            if action['tool']=='analyze_chat_assets':
                from app.agents.production import cache_completed_analyses
                conv=await conversation(db,run.organization_id,run.user_id,run.conversation_id)
                cached=await cache_completed_analyses(db,conv,action['result']) or cached
        if any(j["status"] not in {"succeeded", "failed", "cancelled"} for j in jobs):
            if cached:await db.commit()
            return
        if all(j["status"] == "succeeded" for j in jobs):
            if any(l.role == 'suggestions' for l in links):
                # A suggestion run cannot enter the planner/replanner or submit
                # an image, even if the text model returns tool-shaped content.
                from app.agents.creative_assistance import parse
                try:
                    job = await db.get(Job, next(l.job_id for l in links if l.role == 'suggestions'))
                    run.result_json={**run.result_json,'creative_suggestions':parse(job)}
                    run.status='completed'
                except (ValueError, TypeError):
                    run.status,run.error_code='failed','agent.invalid_suggestions'
                await event(db,run,'suggestions_finished',{'status':run.status})
                await db.commit()
                return
            if any(l.role == "planner" for l in links):
                planner_link = next(l for l in links if l.role == "planner")
                job = await db.get(Job, planner_link.job_id)
                try:
                    from app.agents.planner import parse_intent_result_with_diagnostics
                    decision,normalization = parse_intent_result_with_diagnostics(job)
                except (ValueError, TypeError, RecursionError) as error:
                    run.status, run.error_code = "failed", "agent.invalid_planner_result"
                    from app.agents.planner_result import rejection
                    run.result_json={**run.result_json,'execution_error':'AI 策划结果格式不完整或不符合执行规则，无法安全执行。已保留原始返回，未重新提交生图。'}
                    await event(db,run,'planner_result_rejected',{'job_id':job.id,**rejection(error)})
                else:
                    if normalization:
                        await event(db,run,'planner_result_normalized',{'job_id':job.id,**normalization})
                    if decision.capability_plan and decision.capability_plan.get('asset_roles'):
                        inferred=decision.capability_plan['asset_roles']
                        from app.agents.production import apply_role_predictions
                        try:await apply_role_predictions(db,await conversation(db,run.organization_id,run.user_id,run.conversation_id),inferred,job.id)
                        except AppError as error:
                            run.status,run.error_code='failed',error.code
                            await event(db,run,'asset_role_rejected',{'code':error.code});await db.commit();return
                        await event(db,run,'asset_roles_inferred',{'job_id':job.id,'roles':inferred})
                    planner_link.role = "planner_consumed"
                    run.result_json = {**run.result_json, "planner_decision": decision.model_dump(), "planner_decision_job_id": job.id}
                    run.revision += 1
                    run.status = "planning"
                    try:
                        await advance(db, settings, redis, run, permissions)
                    except AppError as error:
                        run.status, run.error_code = "failed", error.code
                        await event(db, run, "planning_failed", {"code": error.code})
                        await db.commit()
                    return
            else:
                run.status = "completed"
                conv = await conversation(db, run.organization_id, run.user_id, run.conversation_id)
                for action in run.result_json.get('actions',[]):
                    if action['tool']=='analyze_chat_assets' and not action['result'].get('production_plan_id'):
                        from app.agents.production import collect_understanding
                        try:
                            analysis_plan=await collect_understanding(db,conv,action['result'])
                            result=dict(run.result_json);updated=[]
                            for stored in result['actions']:
                                updated.append({**stored,'result':{**stored['result'],'production_plan_id':analysis_plan['id']}} if stored['tool']=='analyze_chat_assets' else stored)
                            run.result_json={**result,'actions':updated}
                            await event(db,run,'asset_roles_understood',{'production_plan_id':analysis_plan['id'],'combination_count':analysis_plan['combination_count']})
                        except AppError as error:
                            run.status,run.error_code='failed',error.code
                if conv.mode == "chat" and any(j["status"] == "succeeded" for j in jobs):
                    from app.agents.adapters.chat import outputs
                    observed = {o["job_id"] for o in await outputs(db, conv, [run.id])}
                    image_ids = set((await db.scalars(select(Job.id).where(Job.id.in_([j["id"] for j in jobs]),
                        Job.capability != "text_generation"))).all())
                    if image_ids - observed:
                        run.status, run.error_code = "failed", "agent.outputs_missing"
                if run.status == "completed" and run.graph_version == "capabilities-v1":
                    from app.agents.capabilities.orchestrator import continue_after_jobs
                    if await continue_after_jobs(db, settings, redis, run, permissions):
                        return
        else:
            unknown = any(any(s in str(j["error_code"]).lower() for s in ("timeout", "network", "524", "gateway",'remote_unknown')) for j in jobs)
            if not unknown:
                from app.agents.samples import upstream_unknown
                for observed in jobs:
                    if observed['status']=='failed':
                        record=await db.get(Job,observed['id'])
                        if record and await upstream_unknown(db,record):unknown=True;break
            run.status = "remote_unknown" if unknown else "failed"
            run.error_code = "agent.remote_unknown" if unknown else "agent.business_job_failed"
            if unknown and all(j['capability']=='text_generation' for j in jobs):
                if any(((record.input_json or {}).get('metadata') or {}).get('role')=='decision'
                    for record in (await db.scalars(select(Job).where(Job.id.in_([j['id'] for j in jobs])))).all()):
                    from app.agents.light_router import fallback
                    await fallback(db,redis,run,'agent.decision_remote_unknown')
                run.result_json = {**run.result_json, 'execution_error':
                    '素材分析或需求规划的上游请求超时，返回状态未知；本轮尚未提交图片生成，不会自动重复请求。'}
    run.revision += 1
    await event(db, run, "jobs_observed", {"status": run.status})
    await db.commit()


async def response(db, settings, run):
    from app.agents.prompt_history import records as prompt_records
    proposal = await db.get(HermesProposal, run.proposal_id) if run.proposal_id else None
    events = (await db.scalars(select(AgentEvent).where(AgentEvent.run_id == run.id)
        .order_by(AgentEvent.created_at, AgentEvent.id).limit(200))).all()
    links = list((await db.scalars(select(AgentJobLink.job_id).where(AgentJobLink.run_id == run.id))).all())
    jobs = await batch.read_jobs(db, run.organization_id, run.user_id, links) if links else []
    from app.agents.adapters.chat import outputs
    conv = await conversation(db, run.organization_id, run.user_id, run.conversation_id)
    gallery = await outputs(db, conv, [run.id]) if conv.mode == "chat" else []
    records=list((await db.scalars(select(Job).where(Job.id.in_(links)))).all()) if links else []
    def mocked(job):
        data=job.result_json or {}
        return bool((data.get('metadata') or {}).get('mock_provider')) or str(data.get('provider_request_id','')).startswith(('mock-','no-live-call'))
    text_records=[j for j in records if j.capability=='text_generation' and j.status=='succeeded']
    image_records=[j for j in records if j.capability!='text_generation' and (j.result_json or {}).get('outputs')]
    verification={'model_inference':'mock' if any(mocked(j) for j in text_records) else 'provider_response_recorded' if text_records else 'not_verified',
        'skill_selection_source':'mock_rules' if run.planner_mode=='mock' else 'mock_model_response' if any(mocked(j) for j in text_records) else 'model_response_recorded' if text_records else 'pending',
        'mcp_success_count':sum(e.event_type=='capability_call_finished' and str(e.payload.get('capability_id','')).startswith('mcp.') and e.payload.get('status')=='succeeded' for e in events),
        'job_count':len(records),'provider_image_response_count':len(image_records),'mock_image_response_count':sum(mocked(j) for j in image_records),
        'stored_output_count':len(gallery),'chat_display':'requires_browser_verification'}
    return RunResponse(id=run.id, conversation_id=run.conversation_id, status=run.status, revision=run.revision,
        planner_mode=run.planner_mode, plan=AgentPlan.model_validate(run.plan_json) if run.plan_json else None,
        result=run.result_json, error_code=run.error_code,
        state_signature=proposal.expected_state_signature if proposal else None,
        confirmation_token=confirmation_token(settings, run, proposal) if proposal and run.status in {"awaiting_confirmation",'awaiting_review'} else None,
        events=[{"id": e.id, "type": e.event_type, "payload": e.payload, "created_at": e.created_at.isoformat()} for e in events],
        jobs=jobs, outputs=gallery,verification=verification,execution_notice=run.result_json.get('execution_notice'),prompts=prompt_records(run,records),
        workspace_url=f"/tasks?batch_id={run.result_json['batch_id']}" if run.result_json.get("batch_id") else None)
