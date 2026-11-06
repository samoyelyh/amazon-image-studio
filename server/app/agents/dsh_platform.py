"""Native Sessions behind the existing React Agent API; no graph planning."""
import json
from datetime import datetime,timezone
from types import SimpleNamespace
from sqlalchemy import select
from app.agents import dsh_settings
from app.core.errors import AppError
from app.models.agent_controller import AgentControllerSetting
from app.models.agent_control import AgentRun,AgentJobLink,AgentEvent
from app.models.hermes_agent import HermesMessage
from app.agents.adapters import chat
from app.experiments.dsh import native

async def controller(db):
    if not dsh_settings.enabled():return 'langgraph'
    row=await db.get(AgentControllerSetting,'default')
    return row.controller if row else 'dsh'

async def set_controller(db,name,user):
    if name not in {'dsh','langgraph'}:raise AppError('dsh.invalid_controller','请选择 DSH 或 LangGraph。',422)
    row=await db.get(AgentControllerSetting,'default',with_for_update=True)
    if not row:row=AgentControllerSetting(id='default',controller=name);db.add(row)
    row.controller=name;row.updated_by=user
    await db.commit()
    return {'controller':name,'history_preserved':True,'affects':'new messages only; existing runs keep their controller'}

async def send(db,settings,conv,payload,principal):
    if not settings.agent_control_writes_enabled or not settings.agent_control_model_calls_enabled:
        raise AppError('agent.writes_disabled','当前未启用总控执行。',409)
    prior=await db.scalar(select(AgentRun).where(AgentRun.conversation_id==conv.id,AgentRun.client_request_id==payload.client_request_id))
    request_hash=native.digest(payload.submission_payload())
    if prior:
        if prior.request_hash!=request_hash:raise AppError('agent.idempotency_conflict','请求编号已用于不同内容。',409)
        await sync(db,prior,principal);return prior
    conv.controller_type='dsh'
    if conv.title=='新的图片创作':conv.title=payload.content.strip().splitlines()[0][:60]
    attachments=await chat.attachments(db,conv)
    selected=set(payload.attachment_ids)
    if selected-{a['id'] for a in attachments}:raise AppError('agent.attachment_missing','所选素材不属于本对话。',404)
    selection={k:v for k,v in payload.model_dump(mode='json').items() if v is not None}
    ticket=None
    if payload.parent_output_id:
        outputs=await chat.outputs(db,conv)
        parent=next((o for o in outputs if o['id']==payload.parent_output_id),None)
        if not parent:raise AppError('agent.output_missing','所选图片不属于本对话。',404)
        selection['target_image']={k:parent.get(k) for k in ['id','asset_id','amazon_module','version','job_id']}
        origin=await db.get(AgentRun,parent['run_id'])
        if origin and not payload.start_new_task:ticket=origin.result_json.get('dsh_ticket')
    if payload.reply_to_run_id:
        previous=await db.get(AgentRun,payload.reply_to_run_id)
        if not previous or previous.conversation_id!=conv.id or previous.user_id!=principal.user.id:raise AppError('agent.run_missing','原任务不属于本对话。',404)
        if previous.revision!=payload.reply_to_revision:raise AppError('agent.revision_conflict','任务已更新，请刷新后继续。',409)
        ticket=previous.result_json.get('dsh_ticket')
    msg=HermesMessage(conversation_id=conv.id,organization_id=conv.organization_id,user_id=conv.user_id,role='user',content=payload.content,
        metadata_json={'dsh_native':True,'attachments':[a for a in attachments if not selected or a['id'] in selected],'sent_at':datetime.now(timezone.utc).isoformat()},created_at=datetime.now(timezone.utc))
    db.add(msg);await db.flush()
    for a in attachments:
        if selected and a['id'] in selected:
            attachment=await db.get(HermesMessage,a['id']);attachment.metadata_json={**attachment.metadata_json,'submitted':True}
    if payload.creative_module is not None:
        from app.agents import creative_modules
        await creative_modules.change(db,conv,payload.creative_module)
    run=AgentRun(conversation_id=conv.id,organization_id=conv.organization_id,user_id=conv.user_id,source_message_id=msg.id,
        client_request_id=payload.client_request_id,request_hash=request_hash,graph_version='dsh-native-v1',planner_mode='dsh-native',status='planning',
        selection_json=selection,plan_json={},result_json={})
    db.add(run);await db.flush()
    selection.update(ui_conversation=conv.id,ui_run=run.id)
    ids=[a['asset_id'] for a in attachments if not selected or a['id'] in selected]
    from app.experiments.dsh.api import Request,owner
    p=Request(session=conv.id,request=payload.client_request_id,text=payload.content,mode='chat' if payload.request_mode=='suggest' else 'auto',
        ticket=ticket,new_task=payload.start_new_task,selection=selection,asset_ids=ids[:50])
    turn=native.digest([owner(principal),p.session,p.request]);run.result_json={'dsh_turn':turn,'dsh_session':conv.id}
    db.add(HermesMessage(conversation_id=conv.id,organization_id=conv.organization_id,user_id=conv.user_id,role='assistant',content='DSH 正在理解需求…',
        metadata_json={'run_id':run.id,'dsh_turn':turn,'sent_at':datetime.now(timezone.utc).isoformat()},created_at=datetime.now(timezone.utc)))
    await db.commit()
    try:await native.intake(p,principal)
    except Exception:
        # Retain the same durable request. A browser retry never changes identity.
        run.result_json={**run.result_json,'delivery_pending':True};await db.commit()
        raise
    return run

async def sync(db,run,principal):
    turn=run.result_json.get('dsh_turn')
    if not turn:return
    await db.commit()  # Never hold MySQL row locks while the bridge settles Jobs.
    result=await native.status(turn,principal)
    from app.models.hermes_agent import HermesConversation
    await db.get(HermesConversation,run.conversation_id,with_for_update=True)
    await db.refresh(run,with_for_update=True)
    state=result['state'];detail=result['native']
    run.status={'accepted':'planning','main_session':'planning','routed':'planning','vision_session':'planning','executor_session':'planning','submitted':'waiting_jobs','needs_input':'needs_input','interrupted':'blocked'}.get(state,state)
    run.result_json={**run.result_json,'dsh_ticket':detail.get('ticket'),'native':True,'native_state':state,'native_sessions':{k:detail.get(k) for k in ['main_session','vision_session','executor_session']},
        'planning_seconds':detail.get('seconds'),'model_calls':{'main':detail.get('main_calls'),'executor':detail.get('executor_calls')},'delivery_pending':False}
    mapped={'produce_aplus':'save_aplus_plan','produce_listing':'save_aplus_plan','revise_visual':'revise_amazon_modules','revise_and_generate':'revise_amazon_modules','create_images':'generate_chat_images'}
    receipts=[{'tool':mapped[e['name']],'result':e['result']} for e in detail.get('events',[]) if e['type']=='tool.result' and e.get('name') in mapped]
    if receipts:run.result_json={**run.result_json,'actions':receipts}
    image_ids=list(dict.fromkeys(j for receipt in receipts for j in receipt['result'].get('job_ids',[])))
    if image_ids and not run.result_json.get('gallery_slots'):
        from app.agents.runtime import assign_gallery_slots
        conv=await db.get(HermesConversation,run.conversation_id)
        slots=await assign_gallery_slots(db,conv,run,image_ids,ordered=True)
        run.result_json={**run.result_json,'gallery_slots':slots}
        # Backfill the original upload receipt representation for native turns.
        for a in await chat.attachments(db,conv):
            if a['id'] in run.selection_json.get('attachment_ids',[]):
                m=await db.get(HermesMessage,a['id']);m.metadata_json={**m.metadata_json,'submitted':True}
    if detail.get('error'):run.result_json={**run.result_json,'error':detail['error']};run.error_code='dsh.session_failed'
    else:run.error_code=None;run.result_json={k:v for k,v in run.result_json.items() if k!='error'}
    for e in detail.get('events',[]):
        key='dsh:'+native.digest(e)
        if not await db.scalar(select(AgentEvent.id).where(AgentEvent.run_id==run.id,AgentEvent.event_key==key)):
            db.add(AgentEvent(run_id=run.id,event_key=key,event_type=e['type'],payload=e,created_at=datetime.now(timezone.utc)))
    with native.connection() as c:model_jobs=c.execute('SELECT job FROM model_jobs WHERE turn_id=?',(turn,)).fetchall()
    for j in model_jobs:
        if not await db.scalar(select(AgentJobLink.id).where(AgentJobLink.run_id==run.id,AgentJobLink.job_id==j['job'])):
            db.add(AgentJobLink(run_id=run.id,job_id=j['job'],role='decision'))
    reply=await db.scalar(select(HermesMessage).where(HermesMessage.conversation_id==run.conversation_id,HermesMessage.role=='assistant',HermesMessage.metadata_json['dsh_turn'].as_string()==turn))
    if reply:
        answer=result.get('answer')
        stage={'main_session':'正在理解需求','vision_session':'正在核对商品原图','executor_session':'正在应用专业 Skill 策划模块','interrupted':'会话已中断，保留原任务和付费回执，可恢复','failed':'任务中断，请查看调用记录'}
        reply.content=answer if state not in {'main_session','vision_session','executor_session','accepted'} and answer else stage.get(state,answer or 'DSH 正在处理任务…')
    await db.commit()

async def resume(db,run,principal):
    turn=run.result_json.get('dsh_turn')
    if turn:
        from app.experiments.dsh.api import owner
        await native.rpc('/native/recover',{'id':turn,**owner(principal)})
        await sync(db,run,principal)

async def stop(db,run,principal):
    ticket=run.result_json.get('dsh_ticket')
    if ticket:
        from app.experiments.dsh.api import owner
        await native.rpc('/intake',{**owner(principal),'session':run.conversation_id,'request':'stop:'+run.id,'text':'停止任务','mode':'stop','ticket':ticket,'semantic':True})
    run.status='cancelled';await db.commit()
