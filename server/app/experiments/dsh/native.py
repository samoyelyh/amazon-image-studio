"""Authenticated business boundary for native Harness Sessions. No graph planning."""
import asyncio
import base64
import gzip
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from time import time
from uuid import uuid5, NAMESPACE_URL

import httpx
from fastapi import APIRouter, Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from app.core.config import get_settings
from app.core.errors import AppError
from app.db.session import get_db_session, get_engine
from app.agents.dsh_settings import state, token, sidecar_url
STATE=state()
from app.infrastructure.redis import get_redis_client
from app.security.principal import require_permissions
from app.models.hermes_agent import HermesConversation, HermesMessage
from app.models.agent_control import AgentRun, AgentJobLink
from app.models.tasks import Job
from app.agents.capabilities.registry import CapabilityRegistry
from app.agents.capabilities.contracts import ExecutionContext
from app.agents.adapters import chat
from app.services.task_service import submit_job, dispatch_jobs
from app.schemas.tasks import JobSubmitRequest
from app.agents.contracts import StrictModel
from app.agents.amazon_contracts import ArtDirection
from pydantic import Field,ValidationError

class VisualRevision(StrictModel):
    plan_id:str
    expected_revision:int=Field(ge=1)
    module_id:str=Field(min_length=1,max_length=50)
    slot_id:str|None=None
    composition:str=Field(min_length=5,max_length=3000)
    image_prompt:str=Field(min_length=5,max_length=10000)
    art_direction:ArtDirection

router=APIRouter(prefix='/experiment/native')

def digest(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def assignment_id(native):
    return native.get('assignment') or next((e.get('assignment') for e in reversed(native.get('events',[])) if e['type']=='engine.assignment' and e.get('session')==native.get('executor_session')),None)

def connection():
    c=sqlite3.connect(STATE/'native-gateway.sqlite',timeout=30);c.row_factory=sqlite3.Row
    c.execute('CREATE TABLE IF NOT EXISTS turns(id TEXT PRIMARY KEY, owner TEXT, payload TEXT, permissions TEXT, ticket TEXT, conversation TEXT, run TEXT, created REAL)')
    c.execute('CREATE TABLE IF NOT EXISTS receipts(id TEXT PRIMARY KEY, turn_id TEXT, tool TEXT, args TEXT, state TEXT, result TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS model_jobs(turn_id TEXT,role TEXT,job TEXT PRIMARY KEY,model TEXT,created REAL)')
    c.execute('CREATE TABLE IF NOT EXISTS turn_policies(turn_id TEXT PRIMARY KEY,plan_only INTEGER NOT NULL)')
    return c

def get_turn(id):
    with connection() as c:r=c.execute('SELECT * FROM turns WHERE id=?',(id,)).fetchone()
    if not r:raise AppError('dsh.turn_missing','Session input does not exist',404)
    return dict(r)

async def internal_auth(x_dsh_token:str=Header(default='')):
    import secrets
    if not secrets.compare_digest(x_dsh_token,token()):
        raise AppError('dsh.internal_denied','Forbidden',403)

async def rpc(path,value,timeout=20):
    async with httpx.AsyncClient(timeout=timeout,trust_env=False) as client:
        response=await client.post(sidecar_url()+path,json=value,headers={'x-dsh-token':token()})
    if response.status_code!=200:raise AppError('dsh.runtime_error',response.json().get('error','Native runtime unavailable'),response.status_code)
    return response.json()

async def intake(payload,principal):
    from app.experiments.dsh.api import owner
    who=owner(principal);value=payload.model_dump(mode='json');id=digest([who,payload.session,payload.request])
    if payload.ticket and not any(t['id']==payload.ticket for t in await rpc('/tickets',who)):
        raise AppError('dsh.ticket_missing','Ticket not found',404)
    if payload.ticket and payload.mode in {'status','stop'}:
        # Explicit UI controls are authorization/state operations, no semantic
        # inference or paid model call is needed to inspect/stop a chosen Ticket.
        result=await rpc('/intake',{**who,'session':payload.session,'request':payload.request,'text':payload.text,'mode':payload.mode,'ticket':payload.ticket,'semantic':True})
        return {**result,'state':result['route'],'controller':'dsh-native','tickets':await rpc('/tickets',{**who,'session':payload.session})}
    async with async_sessionmaker(get_engine(),expire_on_commit=False)() as db:
        for aid in payload.asset_ids:
            image=await chat.asset(db,who['org'],who['user'],aid)
            image.metadata_json={**(image.metadata_json or {}),'private_scope':'agent_chat'}
        await db.commit()
    with connection() as c:
        prior=c.execute('SELECT payload FROM turns WHERE id=?',(id,)).fetchone()
        if prior and json.loads(prior['payload'])!=value:raise AppError('dsh.idempotency_conflict','Request already used',409)
        c.execute('INSERT OR IGNORE INTO turns VALUES(?,?,?,?,?,?,?,?)',(id,json.dumps(who),json.dumps(value,ensure_ascii=False),json.dumps(sorted(principal.permissions)),None,None,None,time()))
    await rpc('/native/intake',{'id':id,**who,**value})
    return await status(id,principal)

async def status(id,principal):
    from app.experiments.dsh.api import owner
    row=get_turn(id);who=owner(principal)
    if json.loads(row['owner'])!=who:raise AppError('dsh.turn_missing','Turn not found',404)
    native=await rpc('/native/status',{'id':id,**who})
    result={'request':json.loads(row['payload'])['request'],'ticket':row['ticket'],'conversation':row['conversation'],
        'route':native.get('route','main_session'),'state':native['state'],'elapsed':native.get('seconds',0),
        'answer':native.get('answer',''),'native':native,'controller':'dsh-native'}
    if row['run']:
        async with async_sessionmaker(get_engine(),expire_on_commit=False)() as db:
            run=await db.get(AgentRun,row['run']);conv=await owned_conversation(db,row)
            jobs=(await db.scalars(select(Job).join(AgentJobLink,AgentJobLink.job_id==Job.id).where(AgentJobLink.run_id==run.id,Job.capability!='text_generation'))).all()
            all_outputs=await chat.outputs(db,conv)
            job_ids={j.id for j in jobs};outputs=[o for o in all_outputs if o['job_id'] in job_ids]
            state=native['state']
            if jobs:
                from app.agents.samples import upstream_unknown
                if any(j.status in {'queued','dispatching','running','pending'} for j in jobs):state='waiting_jobs'
                elif all(j.status=='succeeded' for j in jobs):
                    state='waiting_jobs' if native.get('quality',{}).get('state') in {'pending','running'} else 'completed'
                else:state='remote_unknown' if any([await upstream_unknown(db,j) for j in jobs if j.status=='failed']) else 'failed'
                run.status=state;await db.commit()
                await rpc('/report',{**who,'ticket':row['ticket'],'assignment':assignment_id(native),'state':'ready' if state=='completed' else 'failed' if state=='failed' else 'blocked' if state=='remote_unknown' else 'progress',
                    'summary':f"DSH native: {sum(j.status=='succeeded' for j in jobs)}/{len(jobs)} images; {state}"})
            result['state']=state
            if state=='completed':result['answer']=f'已完成 {len(jobs)} 张独立图片，可预览和下载。'
            elif native.get('quality',{}).get('state') in {'pending','running'} and jobs and all(j.status=='succeeded' for j in jobs):result['answer']=f'{len(jobs)} 张图片已生成，正在检查整套叙事、商品保真和文案匹配，可先预览。'
            result['run']={'id':run.id,'status':state,'graph_version':'dsh-native-v1','plan':run.plan_json,
                'result':{'outputs':outputs,'all_outputs':all_outputs,'native':True},'outputs':outputs,
                'jobs':[{'id':j.id,'status':j.status,'error_code':j.error_code,'result':j.result_json} for j in jobs],
                'events':native.get('events',[]),'amazon_plans':await __import__('app.agents.amazon',fromlist=['list_plans']).list_plans(db,conv)}
    return result

@router.get('/turns/{request}')
async def read(request:str,session:str,principal=Depends(require_permissions('jobs.read'))):
    from app.experiments.dsh.api import owner
    return await status(digest([owner(principal),session,request]),principal)

@router.get('/latest')
async def latest(session:str,principal=Depends(require_permissions('jobs.read'))):
    from app.experiments.dsh.api import owner
    who=owner(principal)
    with connection() as c:
        rows=c.execute('SELECT id,owner,payload FROM turns ORDER BY created DESC').fetchall()
    row=next((r for r in rows if json.loads(r['owner'])==who and json.loads(r['payload'])['session']==session),None)
    if not row:raise AppError('dsh.turn_missing','No native turn in this session',404)
    return await status(row['id'],principal)

@router.post('/resume/{request}')
async def resume(request:str,session:str,principal=Depends(require_permissions('jobs.read'))):
    from app.experiments.dsh.api import owner
    who=owner(principal);id=digest([who,session,request]);row=get_turn(id)
    if json.loads(row['owner'])!=who:raise AppError('dsh.turn_missing','Turn not found',404)
    await rpc('/native/recover',{'id':id,**who});return await status(id,principal)

async def reconcile_jobs(db):
    """Job completion is a DSH Engine report; no LLM polling or graph replay."""
    from app.agents.samples import upstream_unknown
    runs=(await db.scalars(select(AgentRun).where(AgentRun.graph_version=='dsh-native-v1',AgentRun.status.in_(['planning','waiting_jobs','submitted'])))).all()
    for run in runs:
        jobs=(await db.scalars(select(Job).join(AgentJobLink,AgentJobLink.job_id==Job.id).where(AgentJobLink.run_id==run.id,Job.capability!='text_generation'))).all()
        if not jobs or any(j.status not in {'succeeded','failed','cancelled'} for j in jobs):continue
        native=await rpc('/native/status',{'id':run.result_json['dsh_turn'],'org':run.organization_id,'user':run.user_id})
        if all(j.status=='succeeded' for j in jobs) and any(j.input_json.get('metadata',{}).get('amazon_module',{}).get('design_trace',{}).get('creative_strategy_version') for j in jobs):
            if native.get('quality',{}).get('state') in {'pending','running'}:continue
        unknown=any([await upstream_unknown(db,j) for j in jobs if j.status=='failed'])
        run.status='remote_unknown' if unknown else 'completed' if all(j.status=='succeeded' for j in jobs) else 'failed'
        await db.commit()
        await rpc('/report',{'org':run.organization_id,'user':run.user_id,'ticket':run.result_json['dsh_ticket'],'assignment':assignment_id(native),
            'state':'ready' if run.status=='completed' else 'blocked' if unknown else 'failed','summary':f'DSH native Worker results: {run.status}; {len(jobs)} jobs.'})

async def owned_conversation(db,row):
    who=json.loads(row['owner']);conv=await db.get(HermesConversation,row['conversation'])
    if not conv or (conv.organization_id,conv.user_id)!=(who['org'],who['user']):raise AppError('dsh.scope_denied','Conversation not found',404)
    return conv

@router.post('/quality-context',dependencies=[Depends(internal_auth)])
async def quality_context(value:dict,db:AsyncSession=Depends(get_db_session)):
    """Read the complete latest suite, never resubmit Jobs or review legacy history."""
    from app.agents import amazon
    from app.agents.creative_strategy import VisualQualityReview
    row=get_turn(value['turn']);conv=await owned_conversation(db,row)
    run=await db.get(AgentRun,row['run'])
    jobs=(await db.scalars(select(Job).join(AgentJobLink,AgentJobLink.job_id==Job.id).where(AgentJobLink.run_id==run.id,Job.capability!='text_generation'))).all()
    if not jobs or any(j.status not in {'succeeded','failed','cancelled'} for j in jobs):return {'state':'pending'}
    if any(j.status!='succeeded' for j in jobs):return {'state':'unavailable','reason':'存在失败或未知付费结果；不自动重发或审核缺失图片。'}
    ids={j.input_json.get('metadata',{}).get('amazon_module',{}).get('plan_id') for j in jobs}
    if len(ids)!=1 or None in ids:return {'state':'not_applicable'}
    record,plan=await amazon.record(db,conv,ids.pop())
    if not plan.creative_strategy:return {'state':'not_applicable'}
    revision=record.metadata_json['revision']
    prior=next((r for r in record.metadata_json.get('visual_reviews',[]) if r['expected_revision']==revision),None)
    if prior:return {'state':'completed','review':prior}
    outputs=await chat.outputs(db,conv);latest={}
    for o in outputs:
        meta=o.get('amazon_module') or {}
        if meta.get('plan_id')!=record.id:continue
        key=(meta['module_id'],meta.get('slot_id','main'))
        if key not in latest or o['version']>latest[key]['version']:latest[key]=o
    ordered=list(latest.values())
    if len(ordered)>9:return {'state':'unavailable','reason':'本套超过9个独立画面，超出一次受控视觉检查的图片上限；保留全部输出供人工审阅。'}
    from app.agents.aplus_design import slots
    expected={(m.id,s['id']) for m in plan.modules for s in slots(plan,m)}
    if set(latest)!=expected:return {'state':'unavailable','reason':'整套输出尚不完整，不能声称已完成视觉审阅。'}
    source=plan.modules[0].reference_asset_ids[0]
    return {'state':'ready','plan_id':record.id,'expected_revision':revision,'plan':plan.model_dump(mode='json'),
        'authenticated_request':json.loads(row['payload'])['text'],
        'outputs':[{'id':o['id'],'asset_id':o['asset_id'],'module':o['amazon_module']['module_id'],'slot':o['amazon_module'].get('slot_id','main'),'version':o['version']} for o in ordered],
        'reference_asset_ids':[source,*[o['asset_id'] for o in ordered]],
        'reference_order':'第一张是商品原图，其余图片依次对应outputs。只评估实际可见画面；精确Logo/小字需人工核对。',
        'tool_schema':VisualQualityReview.model_json_schema()}

def registry(row):
    who=json.loads(row['owner'])
    return CapabilityRegistry(get_settings(),ExecutionContext(who['org'],who['user'],row['conversation'] or '',row['run'] or row['id'],frozenset(json.loads(row['permissions']))))

@router.post('/prepare',dependencies=[Depends(internal_auth)])
async def prepare(value:dict,db:AsyncSession=Depends(get_db_session)):
    row=get_turn(value['turn']);who=json.loads(row['owner']);p=json.loads(row['payload']);ticket=value['ticket']
    # Ticket ownership is checked by the domain engine before creating/binding records.
    tasks=await rpc('/tickets',who)
    target=next((t for t in tasks if t['id']==ticket),None)
    if not target:raise AppError('dsh.ticket_missing','Ticket not found',404)
    ui=p.get('selection',{})
    conv_id=ui.get('ui_conversation') or str(uuid5(NAMESPACE_URL,digest([who,ticket,'native'])))
    conv=await db.get(HermesConversation,conv_id)
    if conv and (conv.organization_id,conv.user_id)!=(who['org'],who['user']):raise AppError('dsh.scope_denied','Conversation not found',404)
    if not conv:
        conv=HermesConversation(id=conv_id,organization_id=who['org'],user_id=who['user'],controller_type='dsh',mode='chat',title=p['text'][:80]);db.add(conv)
    run=await db.get(AgentRun,ui['ui_run']) if ui.get('ui_run') else await db.scalar(select(AgentRun).where(AgentRun.conversation_id==conv_id,AgentRun.client_request_id==row['id']))
    if run and (run.conversation_id!=conv_id or run.user_id!=who['user'] or run.organization_id!=who['org']):raise AppError('dsh.scope_denied','Run not found',404)
    if not run:
        msg=HermesMessage(conversation_id=conv_id,organization_id=who['org'],user_id=who['user'],role='user',content=p['text'],metadata_json={'dsh_native':True},created_at=datetime.now(timezone.utc));db.add(msg);await db.flush()
        run=AgentRun(conversation_id=conv_id,organization_id=who['org'],user_id=who['user'],source_message_id=msg.id,
            client_request_id=row['id'],request_hash=digest(p),graph_version='dsh-native-v1',planner_mode='dsh-native',status='planning',
            selection_json=p['selection'],plan_json={},result_json={'dsh_ticket':ticket});db.add(run);await db.flush()
    from app.agents.contracts import AttachmentCreate
    existing={a['asset_id'] for a in await chat.attachments(db,conv)}
    for aid in p['asset_ids']:
        image=await chat.asset(db,who['org'],who['user'],aid)
        image.metadata_json={**(image.metadata_json or {}),'private_scope':'agent_chat'}
        if aid not in existing:await chat.attach(db,conv,AttachmentCreate(asset_id=aid))
    run.result_json={**run.result_json,'dsh_ticket':ticket}
    await db.commit()
    with connection() as c:c.execute('UPDATE turns SET ticket=?,conversation=?,run=? WHERE id=?',(ticket,conv_id,run.id,row['id']))
    await rpc('/bind',{**who,'ticket':ticket,'conversation':conv_id})
    row=get_turn(row['id'])
    with connection() as c:c.execute('INSERT OR REPLACE INTO turn_policies VALUES(?,?)',(row['id'],int(bool(value.get('plan_only')))))
    skill_ids=['amazon-market-insight'] if value.get('executor')=='research' else ['image-creation'] if value.get('executor')=='batch_images' else ['amazon-aplus-planner','image-creation']
    if value.get('needs_research') and 'amazon-market-insight' not in skill_ids:skill_ids.append('amazon-market-insight')
    skills=[await tool({'turn':row['id'],'name':'load_skill','args':{'id':sid},'call':'binding:'+sid},db) for sid in skill_ids]
    context=await tool({'turn':row['id'],'name':'read_context','args':{},'call':'binding:context'},db)
    return {'conversation':conv_id,'run':run.id,'catalog':catalog(row),'skills':skills,'context':context}

def catalog(row):
    from app.agents.amazon_brief import SaveDirectorAPlus as SaveProfessionalBrief, SaveDirectorListing as SaveDesignBrief
    from app.agents.amazon_contracts import ModuleRevisions,GenerateAPlus
    from app.agents.contracts import ChatImageAction
    reg=registry(row)
    tools=[{'name':'load_skill','description':'Load and apply the complete approved Skill body before using its business abilities.',
        'parameters':{'type':'object','properties':{'id':{'type':'string','enum':[s['id'] for s in reg.skill_catalog]}},'required':['id'],'additionalProperties':False}},
        {'name':'read_context','description':'Read owned assets, current outputs, plans, real Amazon module specifications and MCP schemas.',
         'parameters':{'type':'object','properties':{},'additionalProperties':False}},
        {'name':'save_design','description':'Save model-authored professional A+ design decisions. Validates identity facts and full module/slot coverage.', 'parameters':SaveProfessionalBrief.model_json_schema()},
        {'name':'save_listing','description':'Save a Listing suite using its separate visual rules and company design directions.', 'parameters':SaveDesignBrief.model_json_schema()},
        {'name':'revise_modules','description':'Update only the explicitly requested stable module IDs in the existing plan.', 'parameters':ModuleRevisions.model_json_schema()},
        {'name':'generate','description':'Submit authorized plan modules to existing concurrent image JobBatch; cached/unknown requests are never resent.', 'parameters':GenerateAPlus.model_json_schema()},
        {'name':'create_images','description':'Generate or edit independent images through the existing image-creation Skill and Job service.', 'parameters':ChatImageAction.model_json_schema()},
        {'name':'complete','description':'Finish this Executor turn or ask one essential question; no image fees are triggered.',
         'parameters':{'type':'object','properties':{'message':{'type':'string'}},'required':['message'],'additionalProperties':False}}]
    tools.append({'name':'record_visual_facts','description':'Record only product facts actually visible in the owned source images; select source product assets and list unknown claims separately.',
        'parameters':{'type':'object','properties':{'selected_asset_ids':{'type':'array','items':{'type':'string'},'minItems':1,'maxItems':3},
            'visible_facts':{'type':'array','items':{'type':'string'},'minItems':1,'maxItems':12},'identity_lock':{'type':'string'},
            'unknown_fields':{'type':'array','items':{'type':'string'}}},'required':['selected_asset_ids','visible_facts','identity_lock','unknown_fields'],'additionalProperties':False}})
    for cap in reg.capabilities.values():
        blocked=STATE/'mcp-unknown.json'
        unknown=json.loads(blocked.read_text()) if blocked.exists() else {}
        prior_unknown=any(asin.lower() in row['payload'].lower() for asin in unknown)
        if cap.source=='mcp' and cap.ready and not prior_unknown:
            tools.append({'name':'mcp_'+cap.id.replace('.','_'),'description':cap.description,'parameters':cap.input_schema,'capability_id':cap.id})
    tools.extend([
        {'name':'produce_aplus','description':'Design and immediately generate a complete professional A+ suite. Model supplies the full creative brief; existing approved SavePlan, Composer and concurrent JobBatch services execute it.', 'parameters':SaveProfessionalBrief.model_json_schema()},
        {'name':'produce_listing','description':'Design and immediately generate the Listing suite using its dedicated visual rules.', 'parameters':SaveDesignBrief.model_json_schema()},
        {'name':'revise_and_generate','description':'Atomically revise ONLY requested existing modules and generate only those modules, preserving other outputs.', 'parameters':ModuleRevisions.model_json_schema()}])
    tools.append({'name':'revise_visual','description':'Change ONLY the requested A+/Listing module image composition and lighting. Preserve all copy, specs, references and other modules automatically; generate only this module.', 'parameters':VisualRevision.model_json_schema()})
    return tools

@router.post('/model',dependencies=[Depends(internal_auth)])
async def model(value:dict,db:AsyncSession=Depends(get_db_session)):
    row=get_turn(value['turn']);who=json.loads(row['owner']);o=value['options'];role=value['role']
    from app.security.principal import resolve_principal
    current=await resolve_principal(db,who['user'],who['org'])
    if not {'jobs.read','projects.read','assets.read'}<=set(current.permissions):raise AppError('dsh.permission_revoked','当前账号已无权继续此任务。',403)
    if o['model'] not in {'gpt-6.1-sol','gpt-6.1-terra','kimi-for-coding'}:raise AppError('dsh.model_denied','Model not allowed',403)
    if value.get('replay_known'):
        with connection() as c:
            recorded=c.execute('SELECT job FROM model_jobs WHERE turn_id=? AND role=? AND model=? ORDER BY created DESC',(row['id'],role,o['model'])).fetchall()
        for known in recorded:
            job=await db.get(Job,known['job'])
            if job and job.status=='succeeded' and (job.organization_id,job.created_by)==(who['org'],who['user']) and ((job.result_json or {}).get('metadata',{}).get('tool_calls') or role=='main' and (job.result_json or {}).get('metadata',{}).get('text')):
                return {**job.result_json['metadata'],'replayed_from_job':job.id,'provider_requests_this_step':0}
            if job:
                from app.agents.samples import upstream_unknown
                if job.status not in {'succeeded','cancelled'} and (job.status!='failed' or await upstream_unknown(db,job)):
                    raise AppError('dsh.model_unknown','前次模型付费结果未知，禁止重新发送。',409)
    messages=[]
    for m in o['messages']:
        content=m.get('content') or [];texts='\n'.join(b.get('text','') for b in content if b['type']=='text')
        if m['role']=='tool':
            messages.append({'role':'tool','tool_call_id':m['toolCallId'],'content':texts})
        elif m['role']=='assistant':
            calls=[{'id':b['id'],'type':'function','function':{'name':b['name'],'arguments':b['arguments']}} for b in content if b['type']=='tool-call']
            reasoning=''.join(b.get('text','') for b in content if b['type']=='reasoning')
            messages.append({'role':'assistant','content':texts or None,**({'tool_calls':calls} if calls else {}),**({'reasoning_content':reasoning} if reasoning and o['model']=='kimi-for-coding' else {})})
        else:messages.append({'role':m['role'],'content':texts})
    # One immutable request per session transcript. Restart resumes this Job.
    key='dsh-native-model:'+digest([o['sessionId'],o['model'],messages,o.get('tools')])
    tools=[{'type':'function','function':t} for t in o.get('tools',[])]
    transcript=json.dumps({'agent_messages':messages,'agent_tools':tools},ensure_ascii=False,separators=(',',':')).encode()
    if len(transcript)>524288:raise AppError('dsh.context_limit','Session needs compaction before another model request',409)
    packed=base64.b64encode(gzip.compress(transcript,mtime=0)).decode('ascii')
    refs=[]
    if role=='vision' and row['conversation']:
        conv=await owned_conversation(db,row)
        refs=[a['asset_id'] for a in await chat.attachments(db,conv)][:6]
    elif role=='quality':
        qc=await quality_context({'turn':row['id']},db)
        if qc['state']!='ready':raise AppError('dsh.quality_unavailable','整套视觉检查条件已变化，请读取原回执。',409)
        refs=qc['reference_asset_ids']
    job,_=await submit_job(db,get_settings(),organization_id=who['org'],user_id=who['user'],payload=JobSubmitRequest(
        operation_code='listing.plan',workspace_type='listing',queue_name='planning_queue',capability='text_generation',model_code=o['model'],idempotency_key=key,
        input={'native_transcript_gzip':packed,'reference_asset_ids':refs,'stream':True,'response_format':None,
            'reasoning_effort':'low','max_tokens':o.get('maxTokens',12000),'metadata':{'workflow':'dsh_native_session','native_session':o['sessionId'],'native_role':role}}))
    job.max_attempts=1;await db.commit()
    with connection() as c:c.execute('INSERT OR IGNORE INTO model_jobs VALUES(?,?,?,?,?)',(row['id'],role,job.id,o['model'],time()))
    if job.status=='queued':await dispatch_jobs(db,[job])
    for _ in range(1200):
        await db.commit()  # MySQL repeatable-read must see Worker commits on each poll.
        await db.refresh(job)
        if job.status=='succeeded':return job.result_json.get('metadata') or {}
        if job.status in {'failed','cancelled'}:
            code=job.error_code or 'dsh.model_failed'
            message='验收调用次数已达上限，本次未发送上游请求。请检查 DSH_CALL_LIMIT 配置。' if code=='experiment.budget_exhausted' else f'模型调用未完成（{code}），请查看本任务调用记录。'
            raise AppError(code,message,409)
        await asyncio.sleep(.5)
    raise AppError('dsh.model_unknown','Model request still pending; never automatically repeat',409)

@router.post('/tool',dependencies=[Depends(internal_auth)])
async def tool(value:dict,db:AsyncSession=Depends(get_db_session)):
    row=get_turn(value['turn']);name=value['name'];args=value['args'];who=json.loads(row['owner'])
    from app.security.principal import resolve_principal
    current_principal=await resolve_principal(db,who['user'],who['org'])
    row['permissions']=json.dumps(sorted(current_principal.permissions));reg=registry(row)
    conv=await owned_conversation(db,row);run=await db.get(AgentRun,row['run']);p=json.loads(row['payload'])
    key='dsh-tool:'+digest([row['id'],value['call'],name,args])
    with connection() as c:
        old=c.execute('SELECT * FROM receipts WHERE id=?',(key,)).fetchone()
    if old and name!='read_context':
        if old['state']=='succeeded':return json.loads(old['result'])
        raise AppError('dsh.tool_unknown','Prior business tool outcome unknown; inspect receipt before retry',409)
    if name in {'produce_aplus','produce_listing','generate','create_images','revise_visual','revise_and_generate'}:
        with connection() as c:policy=c.execute('SELECT plan_only FROM turn_policies WHERE turn_id=?',(row['id'],)).fetchone()
        if policy and policy['plan_only']:raise AppError('dsh.plan_only','本轮仅审方案，不能创建付费图片任务。',409)
        # A new tool-call ID or prompt cannot bypass an unresolved paid image
        # request on the same durable Ticket, including generic image tasks.
        from app.agents.samples import upstream_unknown
        pending=(await db.scalars(select(Job).join(AgentJobLink,AgentJobLink.job_id==Job.id).join(AgentRun,AgentRun.id==AgentJobLink.run_id).where(
            AgentRun.organization_id==who['org'],AgentRun.user_id==who['user'],AgentRun.result_json['dsh_ticket'].as_string()==row['ticket'],Job.capability!='text_generation',Job.status=='failed'))).all()
        if any([await upstream_unknown(db,j) for j in pending]):
            raise AppError('dsh.remote_unknown','本任务存在付费结果未知的图片，请先核对或恢复原回执，不能新建请求重复生图。',409)
    if name not in {'load_skill','read_context','complete'}:
        tasks=await rpc('/tickets',who)
        ticket=next((t for t in tasks if t['id']==row['ticket']),None)
        if not ticket or (ticket.get('ended') or {}).get('by')=='human':
            raise AppError('dsh.authorization_stopped','Task authorization was stopped',409)
    if name=='load_skill':result=reg.load_skill(args['id'])
    elif name=='read_context':
        from app.agents import amazon
        result={**await chat.context(db,conv),'amazon_rules':amazon.rules(),'company_visual_rules':amazon.visual_rules(),
            'mcp_tools':[{'name':t['name'],'capability_id':t.get('capability_id')} for t in catalog(row) if t['name'].startswith('mcp_')],
            'facts_policy':'Visible design only; unknown material, performance, personalization service and licensed rights must be omitted. Templates are design reference, not own product truth.'}
        facts=await db.scalar(select(HermesMessage).where(HermesMessage.conversation_id==conv.id,HermesMessage.role=='dsh_visual_facts').order_by(HermesMessage.created_at.desc()).limit(1))
        if not facts:
            known={a['asset_id'] for a in await chat.attachments(db,conv)}
            candidates=(await db.scalars(select(HermesMessage).where(HermesMessage.organization_id==who['org'],HermesMessage.user_id==who['user'],HermesMessage.role=='dsh_visual_facts').order_by(HermesMessage.created_at.desc()).limit(10))).all()
            facts=next((f for f in candidates if f.metadata_json.get('selected_asset_ids') and set(f.metadata_json['selected_asset_ids'])<=known),None)
        result['visual_facts']=facts.metadata_json if facts else None
        blocked=STATE/'mcp-unknown.json'
        result['unresolved_research']=json.loads(blocked.read_text()) if blocked.exists() else {}
    elif name=='record_visual_facts':
        known={a['asset_id'] for a in await chat.attachments(db,conv)}
        if not set(args['selected_asset_ids'])<=known:raise AppError('dsh.asset_denied','Vision facts must reference owned attached images',403)
        result={**args,'source':'native-dsh-vision-session','scope':'visible_reference_only','not_user_confirmed':True}
        db.add(HermesMessage(conversation_id=conv.id,organization_id=who['org'],user_id=who['user'],role='dsh_visual_facts',content='Native DSH visual observations',metadata_json=result,created_at=datetime.now(timezone.utc)))
        await db.commit()
    elif name=='complete':result={'message':args['message']}
    elif name=='record_quality_review':
        from app.agents.creative_strategy import VisualQualityReview
        from app.agents import amazon
        review=VisualQualityReview.model_validate(args)
        qc=await quality_context({'turn':row['id']},db)
        if qc['state']=='completed':result=qc['review']
        else:
            if qc['state']!='ready' or review.plan_id!=qc['plan_id'] or review.expected_revision!=qc['expected_revision'] or set(review.inspected_output_ids)!={o['id'] for o in qc['outputs']}:
                raise AppError('dsh.quality_scope','视觉审阅必须覆盖本会话当前版本的整套图片。',409)
            if any(set(f.output_ids)-set(review.inspected_output_ids) for f in review.findings):raise AppError('dsh.quality_scope','审阅意见只能引用实际检查的图片。',409)
            record,_=await amazon.record(db,conv,review.plan_id,lock=True)
            if record.metadata_json['revision']!=review.expected_revision:raise AppError('dsh.quality_stale','方案已更新，本次审阅不能覆盖新版本。',409)
            result={**review.model_dump(mode='json'),'source':'native-dsh-visual-session','human_approved':False,'created_at':datetime.now(timezone.utc).isoformat()}
            record.metadata_json={**record.metadata_json,'visual_reviews':[*record.metadata_json.get('visual_reviews',[]),result]}
            await db.commit()
    else:
        with connection() as c:
            loaded=[json.loads(r[0])['id'] for r in c.execute("SELECT args FROM receipts WHERE turn_id=? AND tool='load_skill' AND state='succeeded'",(row['id'],))]
        required='amazon-market-insight' if name.startswith('mcp_') else 'image-creation' if name=='create_images' else 'amazon-aplus-planner'
        if required not in loaded:raise AppError('dsh.skill_required',f'First load and apply {required}',409)
        from app.agents import tool_registry,amazon,amazon_brief
        from app.agents.contracts import ToolAction
        if name in {'save_design','save_listing','produce_aplus','produce_listing'}:
            from app.agents.amazon_brief import SaveDirectorAPlus,SaveDirectorListing
            try:director=(SaveDirectorListing if name in {'save_listing','produce_listing'} else SaveDirectorAPlus).model_validate(args).brief
            except ValidationError as error:raise AppError('dsh.design_invalid','策划字段不完整：'+'; '.join('.'.join(map(str,e['loc']))+': '+e['msg'] for e in error.errors(include_input=False)),422) from None
            if director.creative_strategy.research_basis=='verified_mcp':
                from app.agents.amazon_research import receipts
                known={r['id'] for r in await receipts(db,conv) if r.get('data_available')}
                if not set(director.creative_strategy.research_receipt_ids)<=known:raise AppError('dsh.research_unverified','市场依据必须引用本会话真实取得数据的MCP回执。',422)
            source_texts=[p['text'],*(await db.scalars(select(HermesMessage.content).where(HermesMessage.conversation_id==conv.id,
                HermesMessage.organization_id==who['org'],HermesMessage.user_id==who['user'],HermesMessage.role=='user').order_by(HermesMessage.created_at.desc()).limit(100))).all()]
            for evidence in args.get('brief',{}).get('evidence',[]):
                if evidence.get('basis')=='user_confirmed' and (not evidence.get('source_quote') or not any(evidence['source_quote'] in s for s in source_texts)):
                    raise AppError('dsh.fact_quote_invalid','A user-confirmed fact needs an exact authenticated user quotation',422)
            normalized=amazon_brief.normalize_arguments(args)
            from app.agents.amazon_contracts import APlusPlan
            plan=APlusPlan.model_validate(normalized['plan'])
            expected='listing' if name in {'save_listing','produce_listing'} else 'aplus'
            if plan.deliverable!=expected:raise AppError('dsh.deliverable_mismatch','A+ and Listing use separate tools and specifications',422)
            # Full professional validation runs before any generation or approval.
            errors=amazon.findings(plan)
            if plan.deliverable=='aplus':
                from app.agents.aplus_design import quality
                errors+=quality(plan,complete=True)['errors']
            if errors:raise AppError('dsh.design_invalid','; '.join(dict.fromkeys(errors)),422)
            action=ToolAction(tool='save_aplus_plan',arguments=normalized)
            run.plan_json={'summary':getattr(amazon_brief.SaveProfessionalBrief.model_validate(args).brief,'suite_rationale','') if name in {'save_design','produce_aplus'} else 'Listing suite','actions':[action.model_dump(mode='json')]}
        elif name=='generate':
            from app.agents.amazon_contracts import GenerateAPlus
            request=GenerateAPlus.model_validate(args)
            # Authorization is the authenticated user's task request, recorded by Main;
            # the model cannot approve an arbitrary other plan or access another user.
            await amazon.authorize_review(db,conv,request,source='dsh-authenticated-task')
            action=ToolAction(tool='generate_aplus',arguments=args)
        elif name=='revise_visual':
            visual=VisualRevision.model_validate(args);_,plan=await amazon.record(db,conv,visual.plan_id)
            target=p.get('selection',{}).get('target_image',{}).get('amazon_module')
            if target and (visual.plan_id!=target['plan_id'] or visual.module_id!=target['module_id'] or visual.slot_id!=target.get('slot_id','main')):
                raise AppError('dsh.image_scope_mismatch','仅可修改用户选中的图片槽位，请使用指定 plan_id、module_id 和 slot_id。',409)
            module=next((m for m in plan.modules if m.id==visual.module_id),None)
            if module is None:raise AppError('agent.module_missing','Module not found',404)
            if visual.slot_id:
                from app.agents.aplus_design import slots
                if visual.slot_id not in {s['id'] for s in slots(plan,module)}:raise AppError('agent.slot_missing','图片槽位不存在。',404)
                updated=module.model_copy(update={'image_slots':[s.model_copy(update={'composition':visual.composition}) if s.id==visual.slot_id else s for s in module.image_slots]}) if module.image_slots else module.model_copy(update={'composition':visual.composition,'image_prompt':visual.image_prompt,'art_direction':visual.art_direction})
            else:
                updated=module.model_copy(update={'composition':visual.composition,'image_prompt':visual.image_prompt,'art_direction':visual.art_direction,
                    'image_slots':[s.model_copy(update={'composition':visual.composition}) for s in module.image_slots]})
            action=ToolAction(tool='revise_amazon_modules',arguments={'plan_id':visual.plan_id,'expected_revision':visual.expected_revision,'modules':[updated.model_dump(mode='json')]})
        elif name in {'revise_modules','revise_and_generate'}:action=ToolAction(tool='revise_amazon_modules',arguments=args)
        elif name=='create_images':action=ToolAction(tool='generate_chat_images',arguments=args)
        elif name.startswith('mcp_'):
            cap_id=next((t['capability_id'] for t in catalog(row) if t['name']==name),None)
            cap=reg.get(cap_id)
            # Upgrade only receipts proven to have made zero remote tool calls.
            # Historical unknown/paid attempts remain immutable and non-retriable.
            from app.models.hermes_agent import HermesToolAudit
            from app.experiments.dsh.ledger import Ledger
            ledger_key='mcp:'+hashlib.sha256(json.dumps([who['org'],who['user'],cap.id,cap.input_schema,args],sort_keys=True).encode()).hexdigest()
            with Ledger(STATE/'worker').connection() as c:
                proof=c.execute('SELECT state,details FROM calls WHERE id=?',(ledger_key,)).fetchone()
            if proof and proof[0]=='not_sent' and json.loads(proof[1]).get('actual_requests')==0:
                audits=(await db.scalars(select(HermesToolAudit).where(HermesToolAudit.organization_id==who['org'],HermesToolAudit.user_id==who['user'],HermesToolAudit.tool_name=='amazon.research'))).all()
                for audit in audits:
                    if audit.result_json.get('tool')==cap.id and audit.arguments_json==args and audit.status=='unknown':
                        audit.result_json={**audit.result_json,'status':'not_sent','actual_requests':0,'receipt_status':'not_sent','recovery_basis':'worker-ledger-zero-tool-calls'};audit.status='not_sent'
                await db.commit()
            from app.agents import amazon_research
            price=amazon_research.quote(reg,cap,args)
            action=ToolAction(tool='research_amazon',arguments={'capability_id':cap_id,'arguments':args,'max_charge_units':price['max_charge_units']})
        else:raise AppError('dsh.tool_denied','Tool unavailable',403)
        # Explicit registry allowlist; the old model planners are never callable here.
        if action.tool=='plan_intent':raise AppError('dsh.planner_denied','Legacy planner forbidden',403)
        # Validate first, then reserve immediately before business side effects.
        # Invalid plans never acquire an ambiguous paid-execution receipt.
        with connection() as c:c.execute('INSERT INTO receipts VALUES(?,?,?,?,?,?)',(key,row['id'],name,json.dumps(args,ensure_ascii=False),'started','{}'))
        result=await tool_registry.execute(db,get_settings(),get_redis_client(),org=who['org'],user=who['user'],permissions=json.loads(row['permissions']),
            action=action,action_key=key,confirmed=True,conversation_id=conv.id,human_request='' if name=='revise_visual' else p['text'],run_id=run.id)
        if name in {'save_design','save_listing','produce_aplus','produce_listing'}:
            plan_record,_=await amazon.record(db,conv,result['amazon_plan_id'])
            plan_record.metadata_json={**plan_record.metadata_json,'controller':'dsh-native','skill_trace':[
                {k:v for k,v in reg.load_skill(skill).items() if k in {'id','version','content_hash'}} for skill in loaded]}
        if name in {'produce_aplus','produce_listing','revise_and_generate','revise_visual'}:
            from app.agents.amazon_contracts import GenerateAPlus
            plan_id=args['plan_id'] if name in {'revise_and_generate','revise_visual'} else result['amazon_plan_id']
            plan_record,plan=await amazon.record(db,conv,plan_id)
            ids=[args['module_id']] if name=='revise_visual' else [m['id'] for m in args['modules']] if name=='revise_and_generate' else [m.id for m in plan.modules]
            generate_args=GenerateAPlus(plan_id=plan_id,expected_revision=plan_record.metadata_json['revision'],module_ids=ids,retry_failed=False,
                slot_ids={args['module_id']:[args['slot_id']]} if name=='revise_visual' and args.get('slot_id') else None)
            await amazon.authorize_review(db,conv,generate_args,source='dsh-authenticated-task')
            generated=await tool_registry.execute(db,get_settings(),get_redis_client(),org=who['org'],user=who['user'],permissions=json.loads(row['permissions']),
                action=ToolAction(tool='generate_aplus',arguments=generate_args.model_dump()),action_key=key+':images',confirmed=True,conversation_id=conv.id,human_request=p['text'],run_id=run.id)
            result={**result,**generated}
        for jid in result.get('job_ids',[]):
            if not await db.scalar(select(AgentJobLink.id).where(AgentJobLink.run_id==run.id,AgentJobLink.job_id==jid)):
                db.add(AgentJobLink(run_id=run.id,job_id=jid,role='generation'))
        if result.get('project_id') and not conv.context_project_id:conv.context_project_id=result['project_id']
        if result.get('job_ids'):run.status='waiting_jobs'
        await db.commit()
    with connection() as c:c.execute('INSERT OR REPLACE INTO receipts VALUES(?,?,?,?,?,?)',(key,row['id'],name,json.dumps(args,ensure_ascii=False),'succeeded',json.dumps(result,ensure_ascii=False,default=str)))
    return result
