"""Production-shaped import races and planner payloads; isolated Mock only."""
from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.agents.adapters.chat import analysis_confirmation_context
from app.models.tasks import Job, JobAttempt
from tests.test_agent_control import agent_context
from tests.test_agent_chat_v2 import chat_context, send
from tests.test_agent_second_round import second_context, finish
from tests.test_agent_autonomous import autonomous_context
from tests.test_agent_material_import import imported, MSG
from tests.test_batch_tryon_workflow import upload


def scope_fixture():
    return {'conversation_id':'c','assets':[{'asset_id':'a','role':'garment','sha256':'hash'}],
            'batch_input_manifest':{'entries':[{'asset_id':'a','role':'garment','garment_key':'sku','manual':True,'enabled':True}]}}


def scope_plan():
    return {'actions':[{'tool':'analyze_chat_assets','arguments':{'asset_ids':['a']}}]}


def test_appended_inputs_and_progress_do_not_invalidate_immutable_analysis():
    before=scope_fixture();after=deepcopy(before)
    after['assets'].append({'asset_id':'new','role':'template','sha256':'another'})
    after['batch_input_manifest']['entries'].append({'asset_id':'new','role':'template'})
    after['batch_input_manifest']['revision']=12
    after['batch_input_manifest']['entries'][0]['analysis']={'confidence':.99}
    assert analysis_confirmation_context(before,scope_plan())==analysis_confirmation_context(after,scope_plan())


@pytest.mark.parametrize('change',['deleted','bytes','role','group','enabled','conversation'])
def test_changed_referenced_input_still_invalidates_analysis(change):
    before=scope_fixture();after=deepcopy(before)
    if change=='deleted':after['assets']=[]
    elif change=='bytes':after['assets'][0]['sha256']='changed'
    elif change=='role':after['assets'][0]['role']='template'
    elif change=='group':after['batch_input_manifest']['entries'][0]['garment_key']='other'
    elif change=='enabled':after['batch_input_manifest']['entries'][0]['enabled']=False
    else:after['conversation_id']='another'
    assert analysis_confirmation_context(before,scope_plan())!=analysis_confirmation_context(after,scope_plan())


@pytest.mark.parametrize('mixed',[False,True])
async def test_batch_planner_only_receives_unresolved_pixels_not_known_garments(autonomous_context,mixed):
    ctx=autonomous_context;ctx['settings'].agent_control_planner='existing_text'
    asset,_=await imported(ctx,'model.png','model.png' if mixed else 'templates/model.png','auto' if mixed else 'template')
    await imported(ctx,'jersey.png','服装/0000532/front.png','garment')
    pending=await send(ctx,MSG,use_batch_inputs=True)
    async with ctx['session_factory']() as db:
        job=await db.get(Job,pending['jobs'][0]['id'])
        assert job.input_json['reference_asset_ids']==([asset['id']] if mixed else [])
    summary=pending['plan']['actions'][0]['arguments']['context_summary']
    assert summary['asset_total']==2 and len(summary['assets'])==2


async def test_append_during_analysis_submission_does_not_stale_or_expand_scope(autonomous_context,monkeypatch):
    from app.agents import runtime,batch_manifest
    from app.agents.adapters import chat
    from app.agents.contracts import AttachmentCreate
    from app.models.hermes_agent import HermesConversation
    ctx=autonomous_context;ctx['settings'].agent_control_planner='existing_text'
    t,_=await imported(ctx,'model.png','templates/model.png','template')
    g,_=await imported(ctx,'front.png','服装/0000532/front.png','garment')
    extra=await upload(ctx['client'],ctx['headers'],'product_reference','extra-front.png')
    ctx['mock_decision']={'summary':'分析当前模板和服装','skills':['batch-production'],'steps':[{
        'capability_id':'business.analyze_assets','arguments':{'asset_ids':[t['id'],g['id']]},'reason':'准备样图'}]}
    pending=await send(ctx,MSG,use_batch_inputs=True)
    original=runtime.confirm;added=False
    async def append_before_confirm(db,settings,redis,run,request,permissions):
        nonlocal added
        if not added and any(a['tool']=='analyze_chat_assets' for a in run.plan_json['actions']):
            added=True
            conv=await db.get(HermesConversation,run.conversation_id)
            await chat.attach(db,conv,AttachmentCreate(asset_id=extra['id'],role='garment'))
            await batch_manifest.sync(db,conv)
        return await original(db,settings,redis,run,request,permissions)
    monkeypatch.setattr(runtime,'confirm',append_before_confirm)
    analyzing=await finish(ctx,pending)
    assert added and analyzing['status']=='waiting_jobs' and not analyzing['error_code'],analyzing
    receipt=next(a['result'] for a in analyzing['result']['actions'] if a['tool']=='analyze_chat_assets')
    assert set(receipt['understanding_asset_ids'])=={t['id'],g['id']}
    assert extra['id'] not in receipt['understanding_asset_ids']
    assert analyzing['result']['confirmation_scope']=='chat-analysis-v1'
    assert not analyzing['result'].get('submitted_import_keys')  # Extra image was not part of this analysis.


async def test_expanded_analysis_input_scope_is_durable_and_not_automatically_resubmitted(autonomous_context):
    from tests.test_agent_material_import import manifest
    ctx=autonomous_context;ctx['settings'].agent_control_planner='existing_text'
    template,_=await imported(ctx,'template.png','模板/template.png','template')
    first=await send(ctx,MSG,use_batch_inputs=True,client_request_id='imports:original',creative_module='batch_tryon')
    await imported(ctx,'front.png','服装/0000532/front.png','garment')
    current=await manifest(ctx)
    ctx['mock_decision']={'summary':'分析当前素材','skills':['batch-production'],'steps':[{
        'capability_id':'business.analyze_assets','arguments':{'asset_ids':[template['id']]},'reason':'准备当前批次'}]}
    analyzing=await finish(ctx,first)
    assert analyzing['result']['submitted_import_keys']==[current['continuation_key']]
    replanning=await finish(ctx,analyzing)
    ctx['mock_decision']={'summary':'素材理解已完成。','steps':[],'done':True}
    settled=await finish(ctx,replanning)
    assert settled['status']=='completed' and settled['result']['submitted_import_keys']==[current['continuation_key']]
    replay=await send(ctx,MSG,use_batch_inputs=True,client_request_id='imports:'+current['continuation_key'],creative_module='batch_tryon')
    assert replay['id']==first['id'] and len(replay['jobs'])==len(settled['jobs'])


async def test_auto_import_coalesces_but_manual_chat_remains_parallel(autonomous_context):
    ctx=autonomous_context;ctx['settings'].agent_control_planner='existing_text'
    await imported(ctx,'model.png','templates/model.png','template')
    await imported(ctx,'front.png','服装/0000532/front.png','garment')
    first=await send(ctx,MSG,use_batch_inputs=True,client_request_id='imports:first',creative_module='batch_tryon')
    await imported(ctx,'front2.png','服装/0000533/front.png','garment')
    url=f"/api/v1/agent/conversations/{ctx['chat']['id']}/messages"
    blocked=await ctx['client'].post(url,headers=ctx['headers'],json={
        'chat_mode':True,'content':MSG,'use_batch_inputs':True,'client_request_id':'imports:second','creative_module':'batch_tryon'})
    assert blocked.status_code==409 and 'agent.import_preparation_pending' in blocked.text
    replay=await send(ctx,MSG,use_batch_inputs=True,client_request_id='imports:first',creative_module='batch_tryon')
    assert replay['id']==first['id'] and len(replay['jobs'])==1
    independent=await send(ctx,'另外生成一张山景图',client_request_id=str(uuid4()))
    assert independent['id']!=first['id'] and independent['status']=='waiting_jobs'
    async with ctx['session_factory']() as db:
        assert await db.scalar(select(func.count()).select_from(Job))==2


async def test_text_524_is_unknown_not_image_failure_and_not_reissued(autonomous_context):
    ctx=autonomous_context;ctx['settings'].agent_control_planner='existing_text'
    run=await send(ctx,'开始批量换衣，请引导上传。')
    async with ctx['session_factory']() as db:
        job=await db.get(Job,run['jobs'][0]['id'])
        job.status='failed';job.error_code='job.max_attempts'
        db.add(JobAttempt(job_id=job.id,organization_id=job.organization_id,attempt_number=1,
            status='failed',http_status=524,error_code='provider.upstream_error',started_at=job.created_at))
        await db.commit()
    observed=(await ctx['client'].get('/api/v1/agent/runs/'+run['id'],headers=ctx['headers'])).json()
    assert observed['status']=='remote_unknown'
    assert '尚未提交图片生成' in observed['result']['execution_error']
    assert not observed['outputs'] and len(observed['jobs'])==1
    replay=await send(ctx,'继续')
    assert replay['id']==run['id'] and len(replay['jobs'])==1
