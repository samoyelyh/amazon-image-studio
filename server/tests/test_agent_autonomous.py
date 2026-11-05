"""Actual native Job/Worker and isolated disk/SQLite; all providers are test doubles."""
import json
import os,asyncio
from uuid import uuid4
import pytest
from sqlalchemy import select,func
from app.models.tasks import Job
from app.models.agent_control import AgentRun
from app.infrastructure.redis import get_redis_client
from tests.test_agent_control import agent_context
from tests.test_agent_chat_v2 import chat_context,send
from tests.test_agent_second_round import second_context,attach,finish
from tests.test_agent_auto_execution import AutoRedis


class AutonomousRedis(AutoRedis):
    async def eval(self,script,numkeys,*args):
        if 'agent-autonomous-rate-v2' not in script:return await super().eval(script,numkeys,*args)
        receipt,minute,limit=args
        if receipt in self.values:return 1
        if int(self.values.get(minute,0))>=int(limit):return 0
        self.values[minute]=int(self.values.get(minute,0))+1;self.values[receipt]=1
        return 1


@pytest.fixture
async def autonomous_context(second_context):
    ctx=second_context
    ctx['settings'].agent_auto_execute_enabled=True
    ctx['settings'].agent_execution_mode='autonomous'
    ctx['redis']=AutonomousRedis()
    ctx['app'].dependency_overrides[get_redis_client]=lambda:ctx['redis']
    return ctx


def decision(instruction,**arguments):
    return {'summary':'根据参考图片生成','skills':['image-creation'],'steps':[
        {'capability_id':'business.create_images','arguments':{'instruction':instruction,**arguments},'reason':'原生图片工具'}]}


@pytest.mark.parametrize('content,review,sample',[
    ('生成一张商品图',False,False),('不用确认，直接生成',False,False),('先给我看看方案',True,False),
    ('先看方案，但不用确认费用',True,False),('不用先做样图，直接生成',False,False),('先做样图，通过后再生成',False,True),
])
def test_human_review_intent_is_not_inferred_from_negated_fee_or_sample_words(content,review,sample):
    from app.agents.execution_policy import wants_review,wants_sample_review
    assert wants_review(content)==review
    assert wants_sample_review(content)==sample


async def test_upload_model_plan_auto_image_then_implicit_output_edit(autonomous_context):
    ctx=autonomous_context;ctx['settings'].agent_control_planner='existing_text'
    garment,a=await attach(ctx,'jersey.png')
    ctx['mock_decision']=decision('生成穿参考球衣的模特，严格保留颜色、图案、号码、领口和袖口。',edit=True,reference_number=1,reference_asset_ids=[garment['id']])
    first=await send(ctx,'帮我生成一张模特展示图',[a['id']])
    assert first['status']=='waiting_jobs' and first['jobs'][0]['capability']=='text_generation'
    images=await finish(ctx,first)
    assert images['status']=='waiting_jobs' and len(images['jobs'])==2,images
    assert any(p['source']=='submitted' for p in images['prompts'])
    result=await finish(ctx,images)
    assert result['status']=='completed' and len(result['outputs'])==1
    assert any(p['source']=='executed' for p in result['prompts'])
    base=result['outputs'][0]
    ctx['mock_decision']=decision('背景换成球场，保持衣服和人物不变。',edit=True)
    editing=await send(ctx,'背景换成球场，衣服保持不变。')
    async with ctx['session_factory']() as db:
        job=await db.get(Job,editing['jobs'][0]['id'])
        assert job.input_json['reference_asset_ids']==[base['asset_id']]
    editing=await finish(ctx,editing)
    edited=await finish(ctx,editing)
    assert edited['outputs'][0]['parent_output_id']==base['id']
    assert edited['outputs'][0]['version']==2
    assert not any(e['type']=='awaiting_confirmation' for e in edited['events'])


async def test_redundant_model_confirmation_does_not_block(autonomous_context):
    ctx=autonomous_context;ctx['settings'].agent_control_planner='existing_text'
    _,a=await attach(ctx,'garment.png')
    ctx['mock_decision']={**decision('使用当前上传图生成白底展示图。',edit=True,reference_number=1),'question':'是否确认提交这张电商主图的生成任务？'}
    run=await finish(ctx,await send(ctx,'生成一张白底商品图',[a['id']]))
    assert run['status']=='waiting_jobs' and len(run['jobs'])==2,run
    assert any(e['type']=='redundant_confirmation_ignored' for e in run['events'])


async def test_empty_model_reference_list_cannot_drop_selected_uploads(autonomous_context):
    ctx=autonomous_context;ctx['settings'].agent_control_planner='existing_text'
    garment,a=await attach(ctx,'selected-upload.png')
    ctx['mock_decision']=decision('背景换成球场，服装保持不变。',edit=True,reference_number=1,reference_asset_ids=[])
    run=await finish(ctx,await send(ctx,'先分析上传图片，再把上传图片的背景换成球场',[a['id']]))
    assert run['status']=='waiting_jobs',run
    async with ctx['session_factory']() as db:
        job=await db.get(Job,next(j['id'] for j in run['jobs'] if j['capability']!='text_generation'))
        assert job.input_json['reference_asset_ids']==[garment['id']]


async def test_explicit_review_and_short_continue_reuses_pending_action(autonomous_context):
    ctx=autonomous_context
    _,a=await attach(ctx,'garment.png')
    first=await send(ctx,'先给我看看方案，生成2张模特展示图',[a['id']])
    assert first['status']=='awaiting_review' and not first['jobs'],first
    key=str(uuid4())
    resumed=await send(ctx,'按刚才的做。',client_request_id=key)
    assert resumed['id']==first['id'] and resumed['status']=='waiting_jobs' and len(resumed['jobs'])==2,resumed
    replay=await send(ctx,'按刚才的做。',client_request_id=key)
    assert replay['id']==first['id'] and len(replay['jobs'])==2
    continued=await send(ctx,'继续。')
    assert continued['id']==first['id'] and len(continued['jobs'])==2


async def test_real_clarification_inherits_goal_and_images_on_normal_composer_reply(autonomous_context):
    ctx=autonomous_context;ctx['settings'].agent_control_planner='existing_text'
    _,a=await attach(ctx,'two-people.png')
    previous_prompt='为指定人物换上参考球衣，保持服装颜色、号码和结构。'
    ctx['mock_decision']={**decision(previous_prompt,edit=True),'summary':'需要确定替换目标','question':'需要替换哪个人物的上衣？'}
    pending=await finish(ctx,await send(ctx,'换成参考球衣',[a['id']]))
    assert pending['status']=='awaiting_clarification'
    ctx['mock_decision']=decision('只替换左边人物的上衣，其他人保持不变。',edit=True)
    reply=await send(ctx,'左边的人。')
    async with ctx['session_factory']() as db:
        row=await db.get(AgentRun,reply['id'])
        assert row.selection_json['attachment_ids']==[a['id']]
        assert '换成参考球衣' in row.selection_json['content']
        assert row.selection_json['reply_to_run_id']==pending['id']
        job=await db.get(Job,reply['jobs'][0]['id'])
        inherited=json.loads(job.input_json['user_prompt'])['context']['previous_proposal_not_authorization']
        assert inherited[0]['arguments']['instruction']==previous_prompt
    ready=await finish(ctx,reply)
    assert ready['status']=='waiting_jobs' and len(ready['jobs'])==2,ready


async def test_large_count_and_long_estimate_are_not_fee_gates(autonomous_context,monkeypatch):
    from app.agents import auto_execution
    ctx=autonomous_context
    async def long(*args):return {'text':'预计约10–20分钟','maximum_seconds':1200,'sample_count':5,'source':'recent_successes'}
    monkeypatch.setattr(auto_execution,'estimate',long)
    ctx['settings'].agent_auto_max_images=1;ctx['settings'].agent_auto_max_credits=1
    run=await send(ctx,'生成4张球衣商品图')
    assert run['status']=='waiting_jobs' and len(run['jobs'])==4,run
    assert run['execution_notice']['automatic'] and not run['execution_notice']['reason']


async def test_prompt_versions_do_not_mutate_jobs_and_can_start_an_exact_new_task(autonomous_context):
    ctx=autonomous_context
    first=await send(ctx,'生成一张商品展示图')
    submitted=next(p for p in first['prompts'] if p['source']=='submitted')
    url='/api/v1/agent/runs/'+first['id']+'/prompts'
    response=await ctx['client'].post(url,headers=ctx['headers'],json={
        'expected_revision':first['revision'],'source_id':submitted['id'],'content':'生成白底商品图，保持酒红球衣，柔和商业光线。'})
    assert response.status_code==200,response.text
    saved=response.json();version=next(p for p in saved['prompts'] if p['source']=='user')
    async with ctx['session_factory']() as db:
        job=await db.get(Job,first['jobs'][0]['id'])
        assert job.input_json['prompt']!='生成白底商品图，保持酒红球衣，柔和商业光线。'
    new=await send(ctx,'用保存的提示词生成',prompt_source_run_id=first['id'],prompt_version_id=version['id'])
    assert new['status']=='waiting_jobs' and len(new['jobs'])==1,new
    async with ctx['session_factory']() as db:
        job=await db.get(Job,new['jobs'][0]['id'])
        assert job.input_json['prompt']==version['content']
    stale=await ctx['client'].post(url,headers=ctx['headers'],json={
        'expected_revision':first['revision'],'source_id':submitted['id'],'content':'旧版本编辑'})
    assert stale.status_code==409


async def test_old_pending_model_action_can_continue_without_another_model_call(autonomous_context):
    ctx=autonomous_context;ctx['settings'].agent_control_planner='existing_text'
    ctx['settings'].agent_execution_mode='bounded'
    _,a=await attach(ctx,'legacy-upload.png')
    ctx['mock_decision']={**decision('编辑当前上传图，背景换成球场。',edit=True,reference_number=1),'question':'是否确认提交这张图片的生成任务？'}
    pending=await finish(ctx,await send(ctx,'背景换成球场',[a['id']],auto_execute=True))
    assert pending['status']=='needs_input'
    ctx['settings'].agent_execution_mode='autonomous'
    resumed=await send(ctx,'是。')
    assert resumed['id']==pending['id'] and resumed['status']=='waiting_jobs',resumed
    assert len([j for j in resumed['jobs'] if j['capability']=='text_generation'])==1
    assert len([j for j in resumed['jobs'] if j['capability']!='text_generation'])==1


async def test_closed_switches_cannot_be_overridden_by_autonomy(autonomous_context):
    ctx=autonomous_context;ctx['settings'].agent_control_model_calls_enabled=False
    run=await send(ctx,'生成一张商品图')
    assert run['status']=='failed' and run['error_code']=='agent.execution_disabled' and not run['jobs'],run


async def test_rate_limiter_waits_without_a_confirmation_bypass(autonomous_context):
    ctx=autonomous_context;ctx['settings'].agent_auto_submissions_per_minute=1
    first=await send(ctx,'生成一张商品图甲')
    waiting=await send(ctx,'生成一张商品图乙')
    assert len(first['jobs'])==1 and waiting['status']=='ready_to_submit' and not waiting['jobs']
    assert waiting['confirmation_token'] is None and waiting['execution_notice']['retry_at']
    ctx['redis'].values.clear()
    async with ctx['session_factory']() as db:
        row=await db.get(AgentRun,waiting['id']);row.result_json={**row.result_json,'execution_notice':{}}
        await db.commit()
    resumed=(await ctx['client'].get('/api/v1/agent/runs/'+waiting['id'],headers=ctx['headers'])).json()
    assert resumed['status']=='waiting_jobs' and len(resumed['jobs'])==1


async def test_unknown_remote_result_is_not_reissued_by_continue(autonomous_context):
    ctx=autonomous_context
    run=await send(ctx,'生成一张超时测试图')
    async with ctx['session_factory']() as db:
        job=await db.get(Job,run['jobs'][0]['id']);job.status='failed';job.error_code='provider.remote_unknown'
        await db.commit()
    observed=(await ctx['client'].get('/api/v1/agent/runs/'+run['id'],headers=ctx['headers'])).json()
    assert observed['status']=='remote_unknown'
    after=await send(ctx,'继续')
    assert after['id']==run['id'] and after['status']=='remote_unknown' and len(after['jobs'])==1


async def test_prompt_and_pending_permissions_remain_user_and_conversation_scoped(autonomous_context):
    ctx=autonomous_context
    run=await send(ctx,'先给我看看方案，生成一张商品图')
    source=run['prompts'][0]
    login=(await ctx['client'].post('/api/v1/auth/login',json={'account':'first-viewer','password':'viewer-password'})).json()
    denied=await ctx['client'].post('/api/v1/agent/runs/'+run['id']+'/prompts',headers={'Authorization':'Bearer '+login['access_token']},json={
        'expected_revision':run['revision'],'source_id':source['id'],'content':'不允许的编辑'})
    assert denied.status_code in {403,404}
    another=(await ctx['client'].post('/api/v1/agent/conversations',headers=ctx['headers'],json={'context_kind':'chat'})).json()
    wrong=await ctx['client'].post('/api/v1/agent/conversations/'+another['id']+'/messages',headers=ctx['headers'],json={
        'content':'继续','chat_mode':True,'client_request_id':str(uuid4()),'reply_to_run_id':run['id'],'reply_to_revision':run['revision']})
    assert wrong.status_code==404


async def test_explicit_sample_review_survives_later_requests(autonomous_context):
    from app.models.hermes_agent import HermesMessage
    from app.agents.production import ProductionRules,AssetUnderstanding,image_quote,PlanAction
    ctx=autonomous_context
    template,_=await attach(ctx,'template-small.png');garment,_=await attach(ctx,'garment-small.png')
    async with ctx['session_factory']() as db:
        from app.models.hermes_agent import HermesConversation
        conv=await db.get(HermesConversation,ctx['chat']['id'])
        rules=ProductionRules(common_prompt='保留模板，只替换当前服装',
            template_rules={template['id']:AssetUnderstanding(role='template',confidence=.99)},
            garment_rules={garment['id']:AssetUnderstanding(role='garment',confidence=.99)},sample_review_required=True)
        from datetime import datetime,timezone
        row=HermesMessage(conversation_id=conv.id,organization_id=conv.organization_id,user_id=conv.user_id,
            role='production_plan',content='隔离样图审核方案',metadata_json=rules.model_dump(mode='json'),created_at=datetime.now(timezone.utc))
        db.add(row);await db.flush()
        from app.core.errors import AppError
        with pytest.raises(AppError) as error:
            await image_quote(db,conv,PlanAction(plan_id=row.id,expected_revision=1,stage='production'),autonomous=True)
        assert error.value.code=='agent.samples_not_approved'


async def test_confirmation_only_model_reply_has_one_bounded_replan_not_an_approval_dialog(autonomous_context):
    ctx=autonomous_context;ctx['settings'].agent_control_planner='existing_text'
    ctx['mock_decision']={'summary':'请求确认','question':'是否确认提交图片生成任务？','steps':[]}
    first=await finish(ctx,await send(ctx,'生成一张商品图'))
    assert first['status']=='waiting_jobs' and len(first['jobs'])==2,first
    ctx['mock_decision']=decision('生成白底商品图，保留商品结构。')
    next_run=await finish(ctx,first)
    assert next_run['status']=='waiting_jobs' and len(next_run['jobs'])==3,next_run
    assert len([j for j in next_run['jobs'] if j['capability']=='text_generation'])==2


async def test_non_dynamic_compatible_router_also_has_no_routine_fee_gate(autonomous_context):
    ctx=autonomous_context;ctx['settings'].agent_dynamic_capabilities_enabled=False
    ctx['settings'].agent_control_planner='existing_text'
    _,a=await attach(ctx,'plain-reference.png')
    ctx['mock_decision']={'intent':'generate','summary':'编辑上传图','workflow':'edit','image_count':1,'reference_number':1,
        'question':'是否确认提交图片生成任务？'}
    run=await finish(ctx,await send(ctx,'背景换成球场',[a['id']]))
    assert run['status']=='waiting_jobs' and len(run['jobs'])==2,run


async def test_start_new_task_does_not_inherit_an_unrelated_pending_action(autonomous_context):
    ctx=autonomous_context
    pending=await send(ctx,'先给我看看方案，生成一张球衣图')
    fresh=await send(ctx,'生成一张鞋子图',start_new_task=True)
    assert fresh['id']!=pending['id'] and fresh['status']=='waiting_jobs'
    async with ctx['session_factory']() as db:
        row=await db.get(AgentRun,fresh['id'])
        assert row.selection_json['attachment_ids']==[] and not row.selection_json.get('reply_to_run_id')


@pytest.mark.skipif(not os.environ.get('AGENT_AUTONOMOUS_TEST_REDIS_URL'),reason='Explicit isolated Redis only')
async def test_real_redis_autonomous_rate_receipts_are_atomic_without_credit_approval():
    from app.agents.autonomous_execution import RATE_SCRIPT
    import redis.asyncio as redis
    url=os.environ['AGENT_AUTONOMOUS_TEST_REDIS_URL']
    assert url.startswith('redis://127.0.0.1:16388/'), 'Use the separately bound isolated Redis, never production'
    client=redis.Redis.from_url(url,decode_responses=True)
    prefix='test-autonomous:'+str(uuid4());minute=prefix+':minute'
    keys=[prefix+':receipt:'+str(i) for i in range(10)]
    try:
        results=await asyncio.gather(*(client.eval(RATE_SCRIPT,2,key,minute,6) for key in keys))
        assert results.count(1)==6 and results.count(0)==4
        accepted=keys[results.index(1)]
        assert await client.eval(RATE_SCRIPT,2,accepted,minute,6)==1
        assert int(await client.get(minute))==6
        assert 0<await client.ttl(minute)<=120
    finally:
        await client.delete(minute,*keys);await client.aclose()


async def test_explicit_6_by_32_production_uses_original_batch_path_without_sample_gate(autonomous_context):
    from app.models.tasks import JobBatch
    ctx=autonomous_context;ctx['settings'].agent_control_planner='existing_text'
    assets=[];attachments=[]
    for prefix,count in [('template',6),('garment',32)]:
        for i in range(count):
            asset,a=await attach(ctx,f'{prefix}_{i:02}.png');assets.append(asset['id']);attachments.append(a['id'])
    ctx['mock_decision']={'summary':'逐图识别素材','skills':['batch-production'],'steps':[
        {'capability_id':'business.analyze_assets','arguments':{'asset_ids':assets},'reason':'识别实际模板和服装'}]}
    first=await finish(ctx,await send(ctx,'用6个模板和32件服装直接生成全部192张组合，不用先做样图。',attachments))
    assert len([j for j in first['jobs'] if j['capability']=='text_generation'])==39,first
    analyzed=await finish(ctx,first)
    assert analyzed['status']=='waiting_jobs',analyzed
    detail=(await ctx['client'].get('/api/v1/agent/conversations/'+ctx['chat']['id'],headers=ctx['headers'])).json()
    plan=detail['production_plans'][0]
    assert plan['combination_count']==192 and plan['samples']=={}
    ctx['mock_decision']={'summary':'提交完整批量任务','skills':['batch-production'],'steps':[
        {'capability_id':'business.generate_tryon','arguments':{'plan_id':plan['id'],'expected_revision':plan['revision'],'stage':'production'},'reason':'员工明确要求整批生成，不要求先审核样图'}]}
    submitted=await finish(ctx,analyzed)
    images=[j for j in submitted['jobs'] if j['capability']!='text_generation']
    assert submitted['status']=='waiting_jobs' and len(images)==192,submitted
    async with ctx['session_factory']() as db:
        job=await db.get(Job,images[0]['id']);batch=await db.get(JobBatch,job.batch_id)
        assert batch.workspace_type=='batch_tryon' and batch.batch_kind=='production' and batch.total_jobs==192
    await ctx['worker']._execute_job(images[0]['id'])
    progress=(await ctx['client'].get('/api/v1/agent/runs/'+submitted['id'],headers=ctx['headers'])).json()
    assert progress['status']=='waiting_jobs' and len(progress['outputs'])==1
