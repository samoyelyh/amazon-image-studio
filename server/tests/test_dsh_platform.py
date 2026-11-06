"""Platform API contract tests. Native model decisions are separately live-tested."""
import pytest
from sqlalchemy import select,func
from app.agents import dsh_platform,runtime
from app.core.config import get_settings
from app.models.agent_control import AgentRun
from app.models.hermes_agent import HermesMessage
from tests.test_agent_control import agent_context

async def test_original_api_persists_native_chat_idempotently_without_graph(agent_context,monkeypatch):
    ctx=agent_context;monkeypatch.setenv('DSH_ENABLED','true')
    settings=ctx['settings'].model_copy(update={'agent_control_writes_enabled':True,'agent_control_model_calls_enabled':True})
    ctx['app'].dependency_overrides[get_settings]=lambda:settings
    calls=[]
    async def intake(p,principal):calls.append(p);return {'state':'accepted'}
    async def status(id,principal):return {'state':'completed','answer':'你好，我是 DSH。','native':{'state':'completed','events':[]}}
    async def forbidden(*args,**kwargs):raise AssertionError('Legacy planner entered DSH path')
    monkeypatch.setattr(dsh_platform.native,'intake',intake);monkeypatch.setattr(dsh_platform.native,'status',status)
    monkeypatch.setattr(runtime,'create_run',forbidden)
    url='/api/v1/agent/conversations/'+ctx['conversation']['id']+'/messages'
    data={'content':'普通聊天','chat_mode':True,'client_request_id':'native-chat-test-v1'}
    r=await ctx['client'].post(url,json=data,headers=ctx['headers']);assert r.status_code==200,r.text
    first=r.json();assert first['planner_mode']=='dsh-native'
    r=await ctx['client'].post(url,json=data,headers=ctx['headers']);assert r.status_code==200,r.text
    assert r.json()['id']==first['id'];assert len(calls)==1
    detail=await ctx['client'].get('/api/v1/agent/conversations/'+ctx['conversation']['id'],headers=ctx['headers']);assert detail.status_code==200,detail.text
    assert [m['content'] for m in detail.json()['messages']]==['普通聊天','你好，我是 DSH。']
    r=await ctx['client'].post(url,json={**data,'content':'different'},headers=ctx['headers']);assert r.status_code==409

async def test_controller_switch_preserves_existing_conversation(agent_context,monkeypatch):
    ctx=agent_context;monkeypatch.setenv('DSH_ENABLED','true')
    c=ctx['client'];headers=ctx['headers']
    # Team members cannot change a platform-wide emergency switch.
    denied=await c.put('/api/v1/agent/controller',json={'controller':'langgraph'},headers=headers);assert denied.status_code==403
    from tests.test_batch_tryon_workflow import auth_headers
    login=await c.post('/api/v1/auth/login',json={'account':'platform-admin','password':'platform-password'})
    headers={'Authorization':'Bearer '+login.json()['access_token']}
    for mode in ['langgraph','dsh']:
        r=await c.put('/api/v1/agent/controller',json={'controller':mode},headers=headers);assert r.status_code==200,r.text
        r=await c.get('/api/v1/agent/status',headers=headers);assert r.json()['controller']==mode
        r=await c.get('/api/v1/agent/conversations/'+ctx['conversation']['id'],headers=ctx['headers']);assert r.status_code==200

async def test_native_slot_edit_reuses_siblings_and_blocks_unknown(monkeypatch):
    from copy import deepcopy
    from types import SimpleNamespace
    from app.agents import amazon
    from app.agents.amazon_contracts import APlusPlan,GenerateAPlus
    from app.agents.amazon_brief import normalize_arguments
    from app.agents.aplus_design import slots
    from app.core.errors import AppError
    from tests.test_aplus_professional import professional_brief
    plan=APlusPlan.model_validate(normalize_arguments({'brief':professional_brief('asset')})['plan'])
    module=plan.modules[1];old=deepcopy(module)
    signatures={module.id+'::'+s['id']:amazon.slot_signature(plan,module,s) for s in slots(plan,module)}
    jobs={s['id']:SimpleNamespace(id=s['id'],status='succeeded') for s in slots(plan,module)}
    data={'controller':'dsh-native','submissions':[{'module_ids':[module.id]*3,'slot_ids':list(jobs),'job_ids':list(jobs),'module_signatures':signatures}]}
    class DB:
        async def get(self,model,id):return jobs[id]
    module.image_slots[1].composition='仅改第二槽位的摄影背景，其他槽位保持不变。'
    args=GenerateAPlus(plan_id='p',expected_revision=2,module_ids=[module.id])
    pending,reused=await amazon._slot_work(DB(),plan,data,args)
    assert [s['id'] for m,s in pending]==['block2'];assert set(reused)=={(module.id,'block1'),(module.id,'block3')}
    args.slot_ids={module.id:['block2']}
    pending,reused=await amazon._slot_work(DB(),plan,data,args);assert len(pending)==1 and not reused
    jobs['block2'].status='failed'
    async def unknown(*args):return True
    monkeypatch.setattr('app.agents.samples.upstream_unknown',unknown)
    with pytest.raises(AppError,match='前次上游结果未知'):await amazon._slot_work(DB(),plan,data,args)

async def test_native_lost_worker_is_not_safe_to_resend():
    from types import SimpleNamespace
    from app.agents.samples import upstream_unknown
    job=SimpleNamespace(input_json={'metadata':{'dsh_native':True}},status='failed',error_code='job.worker_lost')
    assert await upstream_unknown(None,job) is True

async def test_model_failure_uses_the_real_code_and_human_message(agent_context,monkeypatch):
    ctx=agent_context;monkeypatch.setenv('DSH_ENABLED','true')
    settings=ctx['settings'].model_copy(update={'agent_control_writes_enabled':True,'agent_control_model_calls_enabled':True})
    ctx['app'].dependency_overrides[get_settings]=lambda:settings
    async def intake(p,principal):return {'state':'accepted'}
    async def status(id,principal):return {'state':'failed','answer':'','native':{'state':'failed','error_code':'experiment.budget_exhausted','error':'验收调用次数已达上限，本次未发送上游请求。','events':[]}}
    monkeypatch.setattr(dsh_platform.native,'intake',intake);monkeypatch.setattr(dsh_platform.native,'status',status)
    url='/api/v1/agent/conversations/'+ctx['conversation']['id']+'/messages'
    response=await ctx['client'].post(url,json={'content':'测试模型失败显示','chat_mode':True,'client_request_id':'native-error-message-v1'},headers=ctx['headers'])
    assert response.status_code==200,response.text
    response=await ctx['client'].get('/api/v1/agent/runs/'+response.json()['id'],headers=ctx['headers'])
    assert response.status_code==200,response.text
    assert response.json()['error_code']=='experiment.budget_exhausted'
    assert response.json()['result']['execution_error']=='验收调用次数已达上限，本次未发送上游请求。'
