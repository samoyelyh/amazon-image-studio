"""Meaningful adapter failure-boundary tests. No paid providers."""
import pytest
from app.experiments.dsh.ledger import Ledger
from app.experiments.dsh.api import classify, Request
from app.experiments.dsh.storage import ExperimentStorage
from app.providers.base import ProviderError
from pydantic import ValidationError
from tests.test_agent_control import agent_context
from tests.test_agent_chat_v2 import chat_context


def test_call_ceiling_survives_restart_and_unknown_never_resends(tmp_path):
    ledger=Ledger(tmp_path,limit=2)
    assert ledger.reserve('job1','text','model') is None
    with pytest.raises(ProviderError,match='resend'):Ledger(tmp_path,limit=2).reserve('job1','text','model')
    ledger.finish('job1','succeeded',{'receipt':'durable'})
    assert ledger.reserve('job1','text','model')=={'receipt':'durable'}
    ledger.reserve('job2','text','model')
    with pytest.raises(ProviderError,match='ceiling'):ledger.reserve('job3','text','model')
    assert ledger.reserve('image1','image','image-model') is None


@pytest.mark.parametrize('text,route',[
    ('你好','chat'),('如何生成一张好看的产品图？','chat'),('A+和Listing主图有什么区别？','chat'),
    ('生成一张杯子的产品图','task'),('调研B0716YP6VJ的关键词，再出方案','task'),
    ('第2张背景换成蓝色，其他不变','continue'),('继续原来的任务','continue'),
    ('查看任务进度','status'),('停止当前任务','stop'),
    ('只修改第二个模块，其他不变','continue'),('重新生成第2张','continue'),
    ('修改背景一般需要多久？','chat'),('生成一张图要多少钱？','chat'),('请生成一张红杯图','task'),
])
def test_conservative_explicit_routing(text,route):
    assert classify(text,'auto',False)==route


def test_owner_cannot_be_forged_in_request():
    with pytest.raises(ValidationError):Request(session='s',request='request-id',text='生成图',user='forged')


def test_parallel_call_reservations_cannot_overspend(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    ledger=Ledger(tmp_path,limit=3)
    def reserve(i):
        try:ledger.reserve('job'+str(i),'text','model');return True
        except ProviderError:return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(reserve,range(12)))==3


def test_storage_rejects_traversal_and_keeps_exact_content(tmp_path):
    storage=ExperimentStorage(tmp_path/'objects')
    with pytest.raises(ValueError):storage.download('../other-user.png')
    storage.upload('org/user/a.png',b'content',content_type='image/png')
    assert storage.download('org/user/a.png')==b'content'
    assert storage.get_metadata('org/user/a.png').size==7


@pytest.fixture
async def experiment_context(chat_context,tmp_path,monkeypatch):
    """Real Node/SQLite DSH and platform ORM; Provider execution is disabled."""
    import asyncio,os,socket,subprocess,shutil
    from pathlib import Path
    import httpx
    from app.experiments.dsh import api
    ctx=chat_context
    listener=socket.socket();listener.bind(('127.0.0.1',0));port=listener.getsockname()[1];listener.close()
    root=Path(__file__).resolve().parents[2]
    token='isolated-test-token-with-no-provider-access'
    env={k:os.environ[k] for k in ['PATH','SystemRoot','TEMP','TMP'] if k in os.environ}
    env.update(DSH_PORT=str(port),DSH_STATE_DIR=str(tmp_path/'core'),DSH_INTERNAL_TOKEN=token)
    proc=subprocess.Popen([shutil.which('node'),'--experimental-transform-types',str(root/'experiments/dsh/sidecar.ts')],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{port}',headers={'x-dsh-token':token},trust_env=False,timeout=3) as client:
        for _ in range(100):
            try:
                if (await client.get('/health')).status_code==200:break
            except httpx.TransportError:pass
            await asyncio.sleep(.05)
        else:proc.terminate();raise AssertionError('Official core sidecar did not start')
        async def call(path,value):
            response=await client.post(path,json=value)
            if not response.is_success:
                from app.core.errors import AppError
                raise AppError('experiment.rejected',response.json()['error'],response.status_code)
            return response.json()
        monkeypatch.setattr(api,'STATE',tmp_path)
        monkeypatch.setattr(api,'sidecar',call)
        monkeypatch.setattr(api,'get_settings',lambda:ctx['settings'])
        ctx['settings'].agent_control_text_model='workflow-text'
        ctx['settings'].agent_auto_execute_enabled=True
        ctx['app'].include_router(api.router)
        try:yield ctx
        finally:proc.terminate();proc.wait(timeout=5)


async def test_http_chat_is_text_only_and_replay_has_no_extra_job(experiment_context):
    from sqlalchemy import select,func
    from app.models.tasks import Job
    from app.models.agent_control import AgentRun
    ctx=experiment_context
    body={'session':'main','request':'chat-request-001','text':'A+图片有什么用途？','mode':'chat'}
    first=await ctx['client'].post('/api/v1/experiment/messages',headers=ctx['headers'],json=body)
    assert first.status_code==200,first.text
    assert first.json()['route']=='chat' and first.json()['ticket'] is None and first.json()['answer'] is None
    repeat=await ctx['client'].post('/api/v1/experiment/messages',headers=ctx['headers'],json=dict(reversed(list(body.items()))))
    assert repeat.status_code==200 and repeat.json()['job_id']==first.json()['job_id']
    async with ctx['session_factory']() as db:
        assert await db.scalar(select(func.count()).select_from(Job))==1
        assert await db.scalar(select(func.count()).select_from(AgentRun))==0


async def test_new_task_attaches_owned_asset_in_its_own_conversation(experiment_context):
    ctx=experiment_context
    body={'session':'main','request':'task-request-001','text':'生成一张商品展示图','mode':'task','new_task':True,'asset_ids':[ctx['garment']['id']],'confirmed_facts':{'statement':'仅测试商品外观'}}
    response=await ctx['client'].post('/api/v1/experiment/messages',headers=ctx['headers'],json=body)
    assert response.status_code==200,response.text
    first=response.json();assert first['ticket'] and first['run']['id']
    history=await ctx['client'].get('/api/v1/agent/conversations/'+first['conversation'],headers=ctx['headers'])
    assert history.status_code==200
    assert any(a['asset_id']==ctx['garment']['id'] for a in history.json()['attachments'])
    assert any(m['role']=='user' and '仅测试商品外观' in m['content'] for m in history.json()['messages'])
    again=await ctx['client'].post('/api/v1/experiment/messages',headers=ctx['headers'],json=body)
    assert again.status_code==200 and again.json()['run']['id']==first['run']['id']


async def test_research_facts_must_be_confirmed_by_user_before_images(chat_context,tmp_path,monkeypatch):
    from datetime import datetime,timezone
    from types import SimpleNamespace
    from app.agents import runtime
    from app.experiments.dsh.ledger import install_guards
    from app.workers.tasks import jobs
    from app.agents.capabilities.mcp_gateway import MCPGateway
    from app.models.hermes_agent import HermesMessage
    from app.core.errors import AppError
    from mcp import ClientSession
    ctx=chat_context
    async def committed(*args):return {'authorized_business_service':True}
    monkeypatch.setattr(runtime,'_execute_committed',committed)
    for module,name in [(jobs,'_execute_job'),(jobs,'get_provider_adapter'),(MCPGateway,'call'),(ClientSession,'call_tool')]:
        monkeypatch.setattr(module,name,getattr(module,name))  # Restore experiment-only hooks after this test.
    install_guards(tmp_path)
    async with ctx['session_factory']() as db:
        row=HermesMessage(conversation_id=ctx['chat']['id'],organization_id=ctx['first_org'],user_id='test-owner',role='dsh_fact_gate',content='Unknown own-product facts',metadata_json={'confirmed':False},created_at=datetime.now(timezone.utc))
        # Use the actual conversation owner, preserving the existing FK rules.
        from app.models.hermes_agent import HermesConversation
        row.user_id=(await db.get(HermesConversation,ctx['chat']['id'])).user_id
        db.add(row);await db.commit()
        run=SimpleNamespace(conversation_id=ctx['chat']['id']);plan={'actions':[{'tool':'generate_aplus'}]}
        with pytest.raises(AppError) as blocked:await runtime._execute_committed(db,ctx['settings'],ctx['redis'],run,plan,[],True)
        assert blocked.value.code=='experiment.product_facts_required'
        row.metadata_json={'confirmed':True,'source':'authenticated_user'};await db.commit()
        assert await runtime._execute_committed(db,ctx['settings'],ctx['redis'],run,plan,[],True)=={'authorized_business_service':True}
