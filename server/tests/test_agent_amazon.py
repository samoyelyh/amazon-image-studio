"""No external API/model requests: native services, isolated DB and Mock Provider."""
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4
from contextlib import asynccontextmanager
from zipfile import ZipFile
import io
import json
import pytest
from sqlalchemy import select, func
from app.agents import amazon, amazon_research
from app.agents.amazon_contracts import APlusPlan, GenerateAPlus
from app.agents.capabilities.contracts import CapabilityDecision, PlannedStep, ResearchAction
from app.agents.capabilities.registry import CapabilityRegistry, ToolSelector
from app.agents.capabilities.planner import Planner
from app.agents.capabilities.mcp_gateway import MCPGateway
from app.core.errors import AppError
from app.models.tasks import Job, ProviderModel, ResourcePool, OperationResourcePool
from app.models.hermes_agent import HermesConversation
from app.models.quota import QuotaRule
from tests.test_agent_control import agent_context
from tests.test_agent_chat_v2 import chat_context, send, confirm, complete
from tests.test_agent_capabilities import dynamic_context, exec_context


def sample_plan(asset_id):
    return APlusPlan.model_validate({'marketplace':'US','aplus_type':'basic','rules_version':amazon.rules()['version'],
        'product_identity_lock':'保留原球衣颜色、Logo、领袖结构，不编造尺寸。','campaign_style_lock':'酒红/白色，柔和左侧光，简洁无衬线字体。',
        'insight':{'limitations':['未进行付费市场研究。'],'evidence':[{'id':'fact1','statement':'酒红色球衣','source':'运营提供商品原图',
            'collected_at':datetime.now(timezone.utc).isoformat(),'scope':'own_product','status':'fact'}]},
        'modules':[{'id':f'm{i}','title':f'模块{i}','spec_id':'basic_image_text_overlay','main_point':'真实商品展示','evidence_ids':['fact1'],
            'composition':'商品位于左侧，右侧留白。','image_prompt':'Photorealistic product photograph, no text.',
            'reference_asset_ids':[asset_id],'headline':'Game Day Style','body':'See the details.',
            'desktop_layout':'左图右文','mobile_layout':'上图下文，文字不嵌入图像'} for i in range(1,4)]})


@pytest.fixture
async def amazon_context(dynamic_context):
    ctx=dynamic_context
    async with ctx['session_factory']() as db:
        model=await db.scalar(select(ProviderModel).where(ProviderModel.code=='workflow-image'))
        pool=await db.scalar(select(ResourcePool).where(ResourcePool.model_id==model.id))
        for cap in ('image_edit','multi_image_reference'):
            db.add(OperationResourcePool(operation_code='aplus.generate',resource_pool_id=pool.id,required_capability=cap))
        db.add(QuotaRule(organization_id=None,operation_code='aplus.generate',name='Mock A+',base_cost=1,
            model_multipliers={},quality_multipliers={},resolution_multipliers={},effective_from=datetime(2020,1,1,tzinfo=timezone.utc)))
        await db.commit()
    r=await ctx['client'].post(f"/api/v1/agent/conversations/{ctx['chat']['id']}/attachments",headers=ctx['headers'],json={'asset_id':ctx['garment']['id']})
    assert r.status_code==201,r.text
    ctx['attachment']=r.json();yield ctx


async def make_plan(ctx,monkeypatch):
    plan=sample_plan(ctx['garment']['id'])
    monkeypatch.setattr(Planner,'simulate',lambda *a,**k:CapabilityDecision(summary='依据已提供资料规划，不必调研。',
        skills=['amazon-aplus-planner'],steps=[PlannedStep(capability_id='business.save_aplus_plan',arguments={'plan':plan.model_dump(mode='json')},reason='完整商品资料足够')]))
    proposed=await send(ctx,'为亚马逊 A+ 策划三个模块，使用完整产品资料，不需要外部调研',[ctx['attachment']['id']])
    result=await confirm(ctx,proposed)
    pid=result['result']['actions'][0]['result']['amazon_plan_id']
    return pid,plan


async def test_discovery_and_native_aplus_closed_loop(amazon_context,monkeypatch):
    ctx=amazon_context;reg=CapabilityRegistry(ctx['settings'],ctx['scope'])
    selected=ToolSelector.select(reg,'亚马逊 ASIN 竞品研究与 A+ 运营策划生成')
    assert {s['id'] for s in selected['skills']}=={'amazon-market-insight','amazon-aplus-planner','amazon-visual-brief'}
    pid,plan=await make_plan(ctx,monkeypatch)
    c=ctx['chat']['id'];url=f'/api/v1/agent/conversations/{c}/amazon-plans/{pid}'
    async with ctx['session_factory']() as db:
        conv=await db.get(HermesConversation,c)
        with pytest.raises(AppError,match='模块尚未'):
            await amazon.image_quote(db,conv,GenerateAPlus(plan_id=pid,expected_revision=1,module_ids=['m3']))
        assert await db.scalar(select(func.count()).select_from(Job))==0
    r=await ctx['client'].post(url+'/confirm',headers=ctx['headers'],json={'expected_revision':1,'module_ids':['m3'],
        'verified_evidence_ids':['fact1'],'commercial_rights_confirmed':True})
    assert r.status_code==200,r.text
    run=await send(ctx,'生成已确认的 A+ 模块',amazon_plan_id=pid,amazon_revision=1,amazon_module_ids=['m3'])
    assert run['status']=='awaiting_confirmation' and run['plan']['image_count']==1
    submitted=await confirm(ctx,run);assert len(submitted['jobs'])==1
    replay=await confirm(ctx,run);assert replay['result']==submitted['result']
    jid=submitted['jobs'][0]['id']
    async with ctx['session_factory']() as db:
        job=await db.get(Job,jid)
        assert job.operation_code=='aplus.generate' and job.workspace_type=='aplus'
        assert job.input_json['metadata']['amazon_module']['module_id']=='m3'
        assert 'Do not render' in job.input_json['prompt']
    await complete(ctx,monkeypatch,jid)
    r=(await ctx['client'].get('/api/v1/agent/runs/'+run['id'],headers=ctx['headers'])).json()
    assert r['status']=='completed' and len(r['outputs'])==1
    output=r['outputs'][0]
    assert (await ctx['client'].get(output['download_url'],headers=ctx['headers'])).status_code==200
    exported=await ctx['client'].get(url+'/export',headers=ctx['headers'])
    assert exported.status_code==200 and exported.json()['publish_ready'] is False
    # The existing native Worker fulfills the canonical delivery size even when
    # the Mock Provider returns a differently sized source image.
    assert exported.json()['outputs'][0]['dimensions_match'] is True
    assert (output['width'],output['height'])==(970,300)
    packed=await ctx['client'].get(url+'/archive',headers=ctx['headers'])
    assert packed.status_code==200,packed.text
    with ZipFile(io.BytesIO(packed.content)) as z:
        assert z.testzip() is None and len(z.namelist())==4
        manifest=json.loads(z.read('manifest.json'))
        assert manifest['modules_without_output']==['m1','m2']
        assert manifest['outputs'][0]['archive_path'] in z.namelist()
        assert 'Game Day Style' in z.read('preview.html').decode()
    before=(await ctx['client'].get(f'/api/v1/agent/conversations/{c}',headers=ctx['headers'])).json()['amazon_plans'][0]
    modified=plan.modules[2].model_copy(update={'composition':'仅将第三模块改成球场背景'})
    r=await ctx['client'].put(url+'/module',headers=ctx['headers'],json={'plan_id':pid,'expected_revision':1,'module':modified.model_dump()})
    assert r.status_code==200 and r.json()['revision']==2
    assert r.json()['plan']['modules'][:2]==before['plan']['modules'][:2]
    assert 'm3' not in r.json()['approvals']
    # Export keeps the old result's composition, not the later edited draft.
    original=(await ctx['client'].get(url+'/export',headers=ctx['headers'])).json()
    assert original['outputs'][0]['module_snapshot']['composition']=='商品位于左侧，右侧留白。'
    # Old browser revision may not overwrite the new one.
    assert (await ctx['client'].put(url+'/module',headers=ctx['headers'],json={'plan_id':pid,'expected_revision':1,'module':modified.model_dump()})).status_code==409
    await ctx['client'].post(url+'/confirm',headers=ctx['headers'],json={'expected_revision':2,'module_ids':['m3'],'verified_evidence_ids':['fact1'],'commercial_rights_confirmed':True})
    second=await send(ctx,'重做第三个 A+ 模块',amazon_plan_id=pid,amazon_revision=2,amazon_module_ids=['m3'])
    second=await confirm(ctx,second)
    async with ctx['session_factory']() as db:
        job=await db.get(Job,second['jobs'][0]['id'])
        assert job.input_json['metadata']['agent_image']['parent_output_id']==output['id']
        assert job.input_json['metadata']['agent_image']['version']==2
        assert await db.scalar(select(func.count()).select_from(Job))==2


async def test_unfounded_claim_rights_and_conversation_isolation(amazon_context,monkeypatch):
    ctx=amazon_context;pid,p=await make_plan(ctx,monkeypatch);c=ctx['chat']['id']
    url=f'/api/v1/agent/conversations/{c}/amazon-plans/{pid}'
    bad={'expected_revision':1,'module_ids':['m1'],'verified_evidence_ids':[],'commercial_rights_confirmed':False}
    assert (await ctx['client'].post(url+'/confirm',headers=ctx['headers'],json=bad)).status_code==422
    bad['commercial_rights_confirmed']=True
    assert (await ctx['client'].post(url+'/confirm',headers=ctx['headers'],json=bad)).status_code==422
    p.insight.evidence[0].scope='competitor'
    assert any('我方' in f for f in amazon.findings(p))
    p.modules[0].headline='Buy now for $10'
    assert any('促销' in f for f in amazon.findings(p))
    async with ctx['session_factory']() as db:
        real=await db.get(HermesConversation,c)
        for other in (SimpleNamespace(id=c,organization_id=real.organization_id,user_id=str(uuid4())),
            SimpleNamespace(id=c,organization_id=str(uuid4()),user_id=real.user_id)):
            with pytest.raises(AppError):await amazon.record(db,other,pid)
    other=(await ctx['client'].post('/api/v1/agent/conversations',headers=ctx['headers'],json={'context_kind':'chat'})).json()['id']
    assert (await ctx['client'].get(f'/api/v1/agent/conversations/{other}/amazon-plans/{pid}/export',headers=ctx['headers'])).status_code==404


def seller_manifest(ctx,tmp_path):
    schema={'type':'object','properties':{'asin':{'type':'string','pattern':'^[A-Z0-9]{10}$'}},'required':['asin'],'additionalProperties':False}
    data={'mcp_servers':[{'id':'seller','version':'test-schema','enabled':True,'approved_by':'test-admin','profile':'sellersprite',
        'organizations':[ctx['scope'].organization_id],'url':'http://127.0.0.1:18481/mcp','allow_local_http':True,
        'daily_unit_limit':4,'calls_per_minute':3,'max_calls_per_run':2,'tools':[{'name':'asin.detail','description':'亚马逊 ASIN 竞品资料',
            'input_schema':schema,'may_charge':True,'max_charge_units':2,'keywords':['ASIN','竞品']}]}]}
    path=tmp_path/'manifest.json';path.write_text(json.dumps(data),encoding='utf8');ctx['settings'].agent_capability_manifest=str(path)
    return data,path


async def test_research_budget_receipt_cache_asin_and_owner_isolation(dynamic_context,tmp_path,monkeypatch):
    ctx=dynamic_context;data,path=seller_manifest(ctx,tmp_path);calls=[]
    original_call=MCPGateway.call
    async def mocked(self,cap,arguments,**kwargs):
        assert kwargs['charge_confirmed'] is True;calls.append(arguments)
        return {'chargedUnits':1,'content':{'asin':arguments['asin'],'sales_estimated':True}}
    monkeypatch.setattr(MCPGateway,'call',mocked)
    async with ctx['session_factory']() as db:
        conv=await db.get(HermesConversation,ctx['chat']['id'])
        args=ResearchAction(capability_id='mcp.seller.asin.detail',arguments={'asin':'B012345678'},max_charge_units=2)
        a=await amazon_research.execute(db,ctx['settings'],conv,ctx['scope'].permissions,args,'run1')
        b=await amazon_research.execute(db,ctx['settings'],conv,ctx['scope'].permissions,args,'run2')
        assert a['chargedUnits']==1 and b['cache_hit'] and len(calls)==1
        args.arguments={'asin':'B012345679'}
        await amazon_research.execute(db,ctx['settings'],conv,ctx['scope'].permissions,args,'run3')
        assert len(calls)==2
        args.arguments={'asin':'B012345670'}
        with pytest.raises(AppError,match='预算'):await amazon_research.execute(db,ctx['settings'],conv,ctx['scope'].permissions,args,'run4')
    reg=CapabilityRegistry(ctx['settings'],ctx['scope'])
    cap=reg.get('mcp.seller.asin.detail')
    with pytest.raises(AppError):await original_call(MCPGateway(reg),cap,{'asin':'B012345678'},calls_used=0)


async def test_timeout_is_durable_and_never_reported_free(dynamic_context,tmp_path,monkeypatch):
    ctx=dynamic_context;seller_manifest(ctx,tmp_path)
    async def timeout(*a,**k):raise AppError('agent.mcp_timeout','timeout',503)
    monkeypatch.setattr(MCPGateway,'call',timeout)
    async with ctx['session_factory']() as db:
        conv=await db.get(HermesConversation,ctx['chat']['id']);args=ResearchAction(capability_id='mcp.seller.asin.detail',arguments={'asin':'B012345678'},max_charge_units=2)
        value=await amazon_research.execute(db,ctx['settings'],conv,ctx['scope'].permissions,args,'failed-run')
        assert value['chargedUnits'] is None and value['status']=='unknown' and 'content' not in value
    async with ctx['session_factory']() as db:
        conv=await db.get(HermesConversation,ctx['chat']['id'])
        with pytest.raises(AppError,match='禁止重复'):await amazon_research.execute(db,ctx['settings'],conv,ctx['scope'].permissions,args,'failed-run')


async def test_allowlist_and_schema_drift_fail_closed(dynamic_context,tmp_path):
    ctx=dynamic_context;data,path=seller_manifest(ctx,tmp_path)
    registry=CapabilityRegistry(ctx['settings'],ctx['scope']);cap=registry.get('mcp.seller.asin.detail')
    with pytest.raises(AppError,match='只启用'):await MCPGateway(registry).call(cap,{'asin':'B012345678'},calls_used=0)
    with pytest.raises(AppError):MCPGateway(registry).check_arguments(cap,{'asin':'B012345678','secret-key':'test-only'})
    data['mcp_servers'][0]['tools'][0]['name']='delete.account';path.write_text(json.dumps(data),encoding='utf8')
    with pytest.raises(AppError,match='六项'):CapabilityRegistry(ctx['settings'],ctx['scope'])


async def test_real_gateway_protocol_with_mock_session(dynamic_context,tmp_path,monkeypatch):
    """Exercises discovery/schema guard/call receipt using the real Gateway, no network."""
    import langchain_mcp_adapters.client as client_module
    import langchain_mcp_adapters.tools as tool_module
    ctx=dynamic_context;data,path=seller_manifest(ctx,tmp_path)
    server=data['mcp_servers'][0]
    server.update(credential_env='AGENT_MCP_TEST_SELLER',credential_header='secret-key')
    path.write_text(json.dumps(data),encoding='utf8')
    monkeypatch.setenv('AGENT_MCP_TEST_SELLER','isolated-test-only')
    schema=server['tools'][0]['input_schema'];calls=[]
    class Session:
        async def list_tools(self):return SimpleNamespace(tools=[SimpleNamespace(name='asin.detail',inputSchema=schema)])
        async def call_tool(self,name,args):
            calls.append((name,args));return SimpleNamespace(isError=False,structuredContent={'chargedUnits':1,'data':{'asin':args['asin']}},content=[])
    class Client:
        def __init__(self,connections,**kwargs):
            assert connections['seller']['headers']=={'secret-key':'isolated-test-only'}
        @asynccontextmanager
        async def session(self,name):yield Session()
    async def load(*a,**k):return [SimpleNamespace(name='asin.detail',args_schema=schema)]
    monkeypatch.setattr(client_module,'MultiServerMCPClient',Client)
    monkeypatch.setattr(tool_module,'load_mcp_tools',load)
    reg=CapabilityRegistry(ctx['settings'],ctx['scope']);gateway=MCPGateway(reg);cap=reg.get('mcp.seller.asin.detail')
    discovered=await gateway.discover(reg.mcp['seller'])
    assert discovered==[{'name':'asin.detail','input_schema':schema}] and calls==[]
    result=await gateway.call(cap,{'asin':'B012345678'},calls_used=0,charge_confirmed=True)
    assert result['chargedUnits']==1 and result['trust']=='untrusted_external_data' and len(calls)==1
    schema={'type':'object','properties':{'different':{'type':'string'}}}
    with pytest.raises(AppError,match='协议已变化'):
        await gateway.call(cap,{'asin':'B012345678'},calls_used=1,charge_confirmed=True)
    assert len(calls)==1
    monkeypatch.delenv('AGENT_MCP_TEST_SELLER')
    with pytest.raises(AppError,match='未配置凭据'):gateway.connection(reg.mcp['seller'])


@pytest.mark.parametrize('receipt_units',[1,None])
async def test_research_feedback_to_plan_and_unknown_blocks(amazon_context,tmp_path,monkeypatch,receipt_units):
    ctx=amazon_context;seller_manifest(ctx,tmp_path);calls=[]
    async def mocked(self,cap,arguments,**kwargs):
        calls.append(arguments);return {'chargedUnits':receipt_units,'content':{'source':'mock seller','competitor_claim':'Not an own-product fact'}}
    monkeypatch.setattr(MCPGateway,'call',mocked)
    def planner(goal,selection,observations,**kwargs):
        if observations:
            assert observations[-1]['result']['content']['source']=='mock seller'
            return CapabilityDecision(summary='根据实际回执生成草稿，竞品性能不作为我方事实。',skills=['amazon-aplus-planner'],steps=[
                PlannedStep(capability_id='business.save_aplus_plan',arguments={'plan':sample_plan(ctx['garment']['id']).model_dump(mode='json')},reason='调研完成后才策划')])
        return CapabilityDecision(summary='需要一次ASIN资料查询',skills=['amazon-market-insight'],steps=[
            PlannedStep(capability_id='mcp.seller.asin.detail',arguments={'asin':'B012345678'},reason='用户要求竞品调研')])
    monkeypatch.setattr(Planner,'simulate',planner)
    first=await send(ctx,'亚马逊ASIN竞品研究与 A+ 运营策划',[ctx['attachment']['id']])
    assert first['status']=='awaiting_confirmation' and calls==[]
    next_step=await confirm(ctx,first)
    if receipt_units is None:
        async with ctx['session_factory']() as db:
            conv=await db.get(HermesConversation,ctx['chat']['id'])
            receipt=(await amazon_research.receipts(db,conv))[0]
            assert receipt['data_available'] and receipt['chargedUnits'] is None and receipt['status']=='needs_review'
    assert len(calls)==1 and next_step['status']=='awaiting_confirmation'
    assert next_step['plan']['actions'][0]['tool']=='save_aplus_plan' and next_step['jobs']==[]
    done=await confirm(ctx,next_step)
    assert done['status']=='completed' and done['result']['actions'][0]['result']['amazon_plan_id']
    await ctx['client'].get('/api/v1/agent/runs/'+done['id'],headers=ctx['headers'])
    assert len(calls)==1


async def test_research_cache_and_receipts_do_not_cross_users(dynamic_context,tmp_path,monkeypatch):
    from app.models.identity import User
    ctx=dynamic_context;data,path=seller_manifest(ctx,tmp_path)
    data['mcp_servers'][0].update(daily_unit_limit=10,calls_per_minute=10)
    path.write_text(json.dumps(data),encoding='utf8');calls=[]
    async def mocked(self,cap,arguments,**kwargs):
        calls.append(arguments);return {'chargedUnits':1,'content':{'source':'mock'}}
    monkeypatch.setattr(MCPGateway,'call',mocked)
    async with ctx['session_factory']() as db:
        original=await db.get(HermesConversation,ctx['chat']['id'])
        user=User(account='amazon-peer-test',password_hash='not-a-login-hash',display_name='Isolated peer')
        db.add(user);await db.flush()
        peer=HermesConversation(organization_id=original.organization_id,user_id=user.id,controller_type='agent_control',title='Isolated peer')
        db.add(peer);await db.commit()
        args=ResearchAction(capability_id='mcp.seller.asin.detail',arguments={'asin':'B012345678'},max_charge_units=2)
        await amazon_research.execute(db,ctx['settings'],original,ctx['scope'].permissions,args,'owner:run1')
        result=await amazon_research.execute(db,ctx['settings'],peer,ctx['scope'].permissions,args,'peer:run1')
        assert not result['cache_hit'] and len(calls)==2
        own_receipts=await amazon_research.receipts(db,original)
        peer_receipts=await amazon_research.receipts(db,peer)
        assert len(own_receipts)==len(peer_receipts)==1
        assert own_receipts[0]['id']!=peer_receipts[0]['id']


def test_preview_escapes_external_text_and_keeps_native_copy():
    from app.agents.amazon_export import preview_html
    p=sample_plan(str(uuid4())).model_dump(mode='json');p['modules'][0]['headline']='<script>alert(1)</script>'
    text=preview_html({'brief':{'plan':p},'outputs':[]})
    assert '<script>' not in text and '&lt;script&gt;' in text
    assert '@media(max-width:600px)' in text and 'white-space:pre-wrap' in text
