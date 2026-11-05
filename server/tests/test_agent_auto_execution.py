"""Bounded human-send consent. Isolated DB, storage and native Worker with Mock provider."""
from datetime import datetime, timezone
from uuid import uuid4
import os
import asyncio

import pytest
from sqlalchemy import select, func
from app.agents import auto_execution as auto
from app.agents.contracts import AgentPlan, ToolAction, MessageCreate
from app.infrastructure.redis import get_redis_client
from app.models.tasks import Job
from tests.conftest import FakeRedis
from tests.test_agent_control import agent_context
from tests.test_agent_chat_v2 import chat_context, send, confirm
from tests.test_agent_second_round import second_context, attach, finish


class AutoRedis(FakeRedis):
    async def eval(self, script, numkeys, *args):
        if 'agent-auto-rate-v1' not in script:
            return await super().eval(script,numkeys,*args)
        receipt,minute,hour,max_rate,max_credits,credits=args
        if receipt in self.values:return 1
        if int(self.values.get(minute,0))>=int(max_rate):return -1
        if int(self.values.get(hour,0))+int(credits)>int(max_credits):return -2
        self.values[minute]=int(self.values.get(minute,0))+1
        self.values[hour]=int(self.values.get(hour,0))+int(credits)
        self.values[receipt]=1
        return 1


@pytest.fixture
async def auto_context(second_context):
    ctx=second_context
    ctx['settings'].agent_auto_execute_enabled=True
    ctx['settings'].agent_execution_mode='bounded'  # Historical v1 policy remains replayable.
    ctx['redis']=AutoRedis()
    ctx['app'].dependency_overrides[get_redis_client]=lambda:ctx['redis']
    return ctx


async def test_small_send_generates_without_confirmation_and_refresh_is_idempotent(auto_context):
    ctx=auto_context
    _,a=await attach(ctx,'shirt.png')
    run=await send(ctx,'生成一张球衣模特图',[a['id']],auto_execute=True)
    assert run['status']=='waiting_jobs',run
    assert len(run['jobs'])==1 and run['execution_notice']['automatic']
    assert run['execution_notice']['estimate']['maximum_seconds']==180
    for _ in range(3):
        replay=(await ctx['client'].get('/api/v1/agent/runs/'+run['id'],headers=ctx['headers'])).json()
        assert len(replay['jobs'])==1
    duplicate=await send(ctx,'生成一张球衣模特图',[a['id']],auto_execute=True)
    assert duplicate['id']==run['id']
    result=await finish(ctx,run)
    assert result['status']=='completed' and len(result['outputs'])==1
    assert result['result']['auto_execution']['used']=={'images':1,'credits':10,'text_jobs':0,'steps':1}
    edit=await send(ctx,'背景换成球场，服装不变',parent_output_id=result['outputs'][0]['id'],auto_execute=True)
    assert edit['status']=='waiting_jobs'
    edited=await finish(ctx,edit)
    assert edited['outputs'][0]['parent_output_id']==result['outputs'][0]['id']


async def test_model_then_image_automatically_progresses_but_is_mock_provider(auto_context):
    ctx=auto_context;ctx['settings'].agent_control_planner='existing_text'
    image,a=await attach(ctx,'garment-dynamic.png')
    ctx['mock_decision']={'summary':'生成球衣模特图','skills':['image-creation'],
        'asset_roles':[{'asset_id':image['id'],'role':'garment','confidence':.98,'reason':'单件服装'}],
        'steps':[{'capability_id':'business.create_images','arguments':{'instruction':'生成穿这件球衣的模特展示图'},'reason':'选择原生图片工具'}]}
    text=await send(ctx,'生成穿这件球衣的模特展示图',[a['id']],auto_execute=True)
    assert text['status']=='waiting_jobs' and text['jobs'][0]['capability']=='text_generation',text
    images=await finish(ctx,text)
    assert images['status']=='waiting_jobs' and len(images['jobs'])==2,images
    assert images['result']['auto_execution']['used']['credits']==11
    result=await finish(ctx,images)
    assert result['status']=='completed' and len(result['outputs'])==1
    assert result['verification']['model_inference']=='mock'
    assert result['verification']['mock_image_response_count']==1


async def test_four_images_requires_confirmation_and_keeps_estimate(auto_context):
    ctx=auto_context
    run=await send(ctx,'生成4张写实球衣产品图',auto_execute=True)
    assert run['status']=='awaiting_confirmation' and not run['jobs']
    assert '超过 3 张' in run['execution_notice']['reason']
    assert run['execution_notice']['estimate']['maximum_seconds']>=360
    # Refresh does not silently turn an already shown confirmation into a paid submission.
    ctx['settings'].agent_auto_max_images=10
    ctx['settings'].agent_auto_max_seconds=1800
    refreshed=(await ctx['client'].get('/api/v1/agent/runs/'+run['id'],headers=ctx['headers'])).json()
    assert refreshed['status']=='awaiting_confirmation' and not refreshed['jobs']
    result=await confirm(ctx,run)
    assert len(result['jobs'])==4
    assert len((await confirm(ctx,run))['jobs'])==4


async def test_long_wait_and_unknown_resource_require_confirmation(auto_context,monkeypatch):
    ctx=auto_context
    async def long(*a):return {'text':'预计约 4–8 分钟','maximum_seconds':480,'sample_count':5,'source':'recent_successes'}
    monkeypatch.setattr(auto,'estimate',long)
    run=await send(ctx,'生成一张长时样图',auto_execute=True)
    assert not run['jobs'] and '时间较长' in run['execution_notice']['reason']
    async def unavailable(*a):raise ConnectionError('mock-unavailable')
    monkeypatch.setattr(auto,'estimate',unavailable)
    blocked=await send(ctx,'生成一张新样图',auto_execute=True)
    assert not blocked['jobs'] and '无法估计' in blocked['execution_notice']['reason']


@pytest.mark.parametrize('setting,value,reason',[
    ('agent_auto_max_credits',5,'平台额度'),
    ('agent_auto_submissions_per_minute',1,'频繁'),
    ('agent_auto_credits_per_hour',10,'小时额度'),
    ('agent_auto_max_active_runs',1,'多个任务'),
])
async def test_credits_rate_hour_and_parallel_limits(auto_context,setting,value,reason):
    ctx=auto_context;setattr(ctx['settings'],setting,value)
    if setting!='agent_auto_max_credits':
        first=await send(ctx,'生成一张测试图一',auto_execute=True)
        assert len(first['jobs'])==1,first
    blocked=await send(ctx,'生成一张测试图二',auto_execute=True)
    assert blocked['status']=='awaiting_confirmation' and not blocked['jobs'],blocked
    assert reason in blocked['execution_notice']['reason']


async def test_no_flag_no_auto_and_redis_failure_fails_closed(auto_context,monkeypatch):
    ctx=auto_context
    old=await send(ctx,'生成一张旧客户端图')
    assert old['status']=='awaiting_confirmation' and 'auto_execution' not in old['result']
    async def broken(*args):raise ConnectionError('test')
    monkeypatch.setattr(ctx['redis'],'eval',broken)
    failed=await send(ctx,'生成一张新客户端图',auto_execute=True)
    assert not failed['jobs'] and '保护暂不可用' in failed['execution_notice']['reason']


async def test_text_budget_stops_replanning(auto_context):
    ctx=auto_context;ctx['settings'].agent_control_planner='existing_text'
    ctx['settings'].agent_auto_max_text_jobs=1
    ctx['mock_decision']={'summary':'读取素材','steps':[{'capability_id':'business.current_context','arguments':{},'reason':'核实数据'}]}
    run=await send(ctx,'查看当前素材',auto_execute=True)
    next_run=await finish(ctx,run)
    assert next_run['status']=='awaiting_confirmation' and len(next_run['jobs'])==1,next_run
    assert '自动处理上限' in next_run['execution_notice']['reason']


async def test_expired_consent_does_not_submit(auto_context):
    from app.models.agent_control import AgentRun
    ctx=auto_context
    run=await send(ctx,'生成一张过期测试图')
    async with ctx['session_factory']() as db:
        row=await db.get(AgentRun,run['id'])
        state=auto.grant(ctx['settings'],MessageCreate(content='x',client_request_id='12345678',chat_mode=True,auto_execute=True))
        state['expires_at']='2000-01-01T00:00:00+00:00'
        row.result_json={**row.result_json,'auto_execution':state}
        await db.commit()
    result=(await ctx['client'].get('/api/v1/agent/runs/'+run['id'],headers=ctx['headers'])).json()
    assert not result['jobs'] and '已过期' in result['execution_notice']['reason']


async def test_native_guard_failure_is_visible_and_never_automatically_retried(auto_context,monkeypatch):
    from app.agents import runtime
    from app.core.errors import AppError
    ctx=auto_context;calls=[]
    async def changed(*a,**k):
        calls.append(1)
        raise AppError('agent.price_changed','费用规则已变化，请重新发送需求。',409)
    monkeypatch.setattr(runtime,'confirm',changed)
    run=await send(ctx,'生成一张费用变化测试图',auto_execute=True)
    assert not run['jobs'] and '费用规则已变化' in run['execution_notice']['reason']
    assert run['result']['auto_execution']['suspended']
    again=(await ctx['client'].get('/api/v1/agent/runs/'+run['id'],headers=ctx['headers'])).json()
    assert not again['jobs'] and len(calls)==1


def test_unapproved_tools_never_auto_and_grants_only_from_human_send():
    for tool in ('research_amazon','review_output','submit_tryon_batch'):
        assert auto.quantities(AgentPlan(summary='x',actions=[ToolAction(tool=tool)])) is None
    from app.core.config import Settings
    s=Settings(_env_file=None,agent_auto_execute_enabled=True,agent_execution_mode='bounded')
    assert auto.grant(s,MessageCreate(content='x',client_request_id='12345678',chat_mode=True)) is None
    assert auto.grant(s,MessageCreate(content='x',client_request_id='12345678',auto_execute=True)) is None


async def test_small_tryon_sample_auto_but_rules_and_approval_are_still_required(auto_context):
    ctx=auto_context
    ids=[(await attach(ctx,'template.png'))[1]['id'],(await attach(ctx,'garment.png'))[1]['id']]
    await finish(ctx,await confirm(ctx,await send(ctx,'批量套图',ids)))
    history=(await ctx['client'].get('/api/v1/agent/conversations/'+ctx['chat']['id'],headers=ctx['headers'])).json()
    p=history['production_plans'][0]
    base=f"/api/v1/agent/conversations/{ctx['chat']['id']}/production-plans/{p['id']}"
    result=await ctx['client'].post(base+'/confirm',headers=ctx['headers'],json={'expected_revision':p['revision']})
    assert result.status_code==200,result.text
    revision=result.json()['revision']
    sample=await send(ctx,'生成样图',auto_execute=True,production_plan_id=p['id'],production_revision=revision,production_stage='validation')
    assert sample['status']=='waiting_jobs' and len(sample['jobs'])==1,sample
    # Auto consent does not bypass mandatory sample approval for formal production.
    blocked=await ctx['client'].post(f"/api/v1/agent/conversations/{ctx['chat']['id']}/messages",headers=ctx['headers'],json={
        'content':'正式批量套图','client_request_id':str(uuid4()),'chat_mode':True,'auto_execute':True,
        'production_plan_id':p['id'],'production_revision':revision,'production_stage':'production'})
    assert blocked.status_code==409 and 'samples_not_approved' in blocked.text


async def test_native_capacity_and_observed_history_estimation(auto_context):
    ctx=auto_context
    async with ctx['session_factory']() as db:
        result=await auto.estimate(db,ctx['redis'],ctx['settings'],ctx['first_org'],'listing.generate',None,4)
        assert result['maximum_seconds']==360 and result['source']=='conservative_reservation'
        # Native Jobs, not model analysis success, supply historical image durations.
        run=await send(ctx,'生成一张计时样图',auto_execute=True)
        original=await db.get(Job,run['jobs'][0]['id'])
        original.status='succeeded';original.generation_duration_ms=120000;original.finished_at=datetime.now(timezone.utc)
        await db.commit()
        measured=await auto.estimate(db,ctx['redis'],ctx['settings'],ctx['first_org'],'listing.generate',None,1)
        assert measured['sample_count']==1 and measured['source']=='conservative_reservation'
        from app.models.tasks import ApiKey
        key=await db.scalar(select(ApiKey))
        key.max_concurrency=1
        await db.commit()
        single=await auto.estimate(db,ctx['redis'],ctx['settings'],ctx['first_org'],'listing.generate',None,4)
        assert single['maximum_seconds']==720  # Never estimate with the UI's target 12.


async def test_another_user_cannot_read_or_drive_automatic_run(auto_context):
    ctx=auto_context
    run=await send(ctx,'生成一张私有图片',auto_execute=True)
    login=(await ctx['client'].post('/api/v1/auth/login',json={'account':'first-viewer','password':'viewer-password'})).json()
    denied=await ctx['client'].get('/api/v1/agent/runs/'+run['id'],headers={'Authorization':'Bearer '+login['access_token']})
    assert denied.status_code in (403,404)
    async with ctx['session_factory']() as db:
        assert await db.scalar(select(func.count(Job.id)))==1


@pytest.mark.skipif(not os.environ.get('AGENT_AUTO_TEST_REDIS_URL'),reason='Explicit isolated Redis only')
async def test_real_redis_lua_atomic_limits_and_receipt_replay():
    import redis.asyncio as redis
    r=redis.Redis.from_url(os.environ['AGENT_AUTO_TEST_REDIS_URL'],decode_responses=True)
    prefix='test-agent-auto:'+str(uuid4())
    minute,hour=prefix+':minute',prefix+':hour'
    keys=[prefix+':receipt:'+str(i) for i in range(10)]
    try:
        results=await asyncio.gather(*(r.eval(auto.RATE_SCRIPT,3,key,minute,hour,6,300,10) for key in keys))
        assert results.count(1)==6 and results.count(-1)==4
        assert int(await r.get(hour))==60
        accepted=keys[results.index(1)]
        assert await r.eval(auto.RATE_SCRIPT,3,accepted,minute,hour,6,300,10)==1
        assert int(await r.get(hour))==60
        assert 0<await r.ttl(hour)<=3700
        assert await r.eval(auto.RATE_SCRIPT,3,prefix+':expensive',minute,hour,100,65,10)==-2
    finally:
        await r.delete(minute,hour,*keys,prefix+':expensive')
        await r.aclose()
