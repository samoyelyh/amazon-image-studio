"""No external providers: regression for the browser probe Redis contract."""
from types import SimpleNamespace

from app.core.config import Settings
from app.services.resource_pool_service import renew_resource_lease, release_resource
from tests.conftest import FakeRedis
import asyncio
import json
import os
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone, timedelta
from uuid import uuid4
import pytest
from app.core.errors import AppError
from app.cli.agent_mcp_probe import probe
from app.agents.capabilities.mcp_gateway import MCPGateway
from tests.test_agent_control import agent_context
from tests.test_agent_chat_v2 import chat_context, send, confirm
from tests.test_agent_second_round import second_context
from tests.test_agent_capabilities import local_mcp_server


async def test_browser_probe_redis_supports_existing_lease_heartbeat():
    redis = FakeRedis()
    key = 'resource:key:isolated-heartbeat:inflight'
    lease = SimpleNamespace(key_id='isolated-heartbeat')
    await redis.set(key, 1, ex=30)
    await renew_resource_lease(redis, Settings(_env_file=None), lease)
    assert await redis.exists(key)
    assert redis.expirations[key] == Settings(_env_file=None).resource_lease_ttl_seconds
    await release_resource(redis, lease)
    await renew_resource_lease(redis, Settings(_env_file=None), lease)
    assert not await redis.exists(key)  # Never resurrect a released lease.


async def test_mcp_probe_is_metadata_only_and_requires_website_auth(tmp_path, monkeypatch):
    settings=Settings(_env_file=None)
    with pytest.raises(AppError) as missing:
        await probe(settings,'seller','org','user')
    assert missing.value.code=='agent.registry_missing'
    schema={'type':'object','properties':{'asin':{'type':'string'}},'required':['asin']}
    server={'id':'seller','version':'test','enabled':False,'approved_by':'isolated-admin',
        'organizations':['org'],'users':['user'],'url':'https://metadata.test/mcp','profile':'sellersprite',
        'credential_env':'AGENT_MCP_PREPROD_TEST','credential_header':'secret-key',
        'tools':[{'name':'asin.detail','description':'test metadata only','input_schema':schema,'max_charge_units':1}]}
    file=tmp_path/'manifest.json';file.write_text(json.dumps({'mcp_servers':[server]}),encoding='utf8')
    settings.agent_capability_manifest=str(file)
    calls=[]
    async def discover(self, configured):
        assert self.connection(configured)['headers']=={'secret-key':'isolated-only'}
        calls.append('tools/list')
        return [{'name':'asin.detail','input_schema':schema},{'name':'unexpected.name','input_schema':{}}]
    monkeypatch.setattr(MCPGateway,'discover',discover)
    with pytest.raises(AppError) as no_auth:await probe(settings,'seller','org','user')
    assert no_auth.value.code=='agent.mcp_auth_missing' and not calls
    monkeypatch.setenv('AGENT_MCP_PREPROD_TEST','isolated-only')
    for org,user in [('other','user'),('org','other')]:
        with pytest.raises(AppError) as denied:await probe(settings,'seller',org,user)
        assert denied.value.code=='agent.mcp_not_authorized' and not calls
    result=await probe(settings,'seller','org','user')
    assert calls==['tools/list'] and result['tools_call_count']==0 and not result['enabled']
    assert next(c for c in result['candidates'] if c['candidate']=='asin.detail')['schema_matches']
    assert len([c for c in result['candidates'] if not c['discovered']])==5
    assert result['other_discovered_names']==['unexpected.name']
    assert 'isolated-only' not in json.dumps(result)


@pytest.mark.parametrize('repeat_cursor', [False, True])
async def test_mcp_discovery_reads_pages_but_never_calls_tools(monkeypatch, repeat_cursor):
    import langchain_mcp_adapters.client as client_module
    pages=[]
    class Session:
        async def list_tools(self, cursor=None):
            pages.append(cursor)
            return SimpleNamespace(tools=[SimpleNamespace(name='page'+str(len(pages)),inputSchema={})],
                nextCursor='next' if cursor is None or repeat_cursor else None)
        async def call_tool(self,*a,**k):raise AssertionError('paid call forbidden')
    class Client:
        def __init__(self,*a,**k):pass
        @asynccontextmanager
        async def session(self,*a):yield Session()
    monkeypatch.setattr(client_module,'MultiServerMCPClient',Client)
    monkeypatch.setattr(MCPGateway,'connection',lambda *a:{})
    server=SimpleNamespace(id='seller',timeout_seconds=1)
    if repeat_cursor:
        with pytest.raises(AppError) as error:await MCPGateway(None).discover(server)
        assert error.value.code=='agent.mcp_catalog_invalid'
    else:
        assert len(await MCPGateway(None).discover(server))==2
    assert pages==[None,'next']


async def test_probe_real_http_discovery_does_not_assume_seller_names(tmp_path, monkeypatch, local_mcp_server):
    local_mcp_server['policy']['auth_required']=True
    server={'id':'seller','version':'test','enabled':False,'approved_by':'isolated-admin',
        'organizations':['org'],'url':local_mcp_server['url'],'allow_local_http':True,'profile':'sellersprite',
        'credential_env':'AGENT_MCP_PREPROD_TEST','credential_header':'Authorization',
        'tools':[]}
    file=tmp_path/'manifest.json';file.write_text(json.dumps({'mcp_servers':[server]}),encoding='utf8')
    settings=Settings(_env_file=None,agent_capability_manifest=str(file))
    monkeypatch.setenv('AGENT_MCP_PREPROD_TEST','invalid-test-key')
    with pytest.raises(AppError) as error:await probe(settings,'seller','org','user')
    assert error.value.code=='agent.mcp_auth_failed'
    monkeypatch.setenv('AGENT_MCP_PREPROD_TEST','mock-only-not-a-real-key')
    result=await probe(settings,'seller','org','user')
    assert result['tools_list_succeeded'] and result['other_discovered_names']==['search']
    assert not any(c['discovered'] for c in result['candidates'])
    assert local_mcp_server['calls']==[]


def test_discovery_only_configuration_cannot_be_enabled_without_schemas():
    from pydantic import ValidationError
    from app.agents.capabilities.contracts import MCPApproval
    config={'id':'seller','version':'test','approved_by':'admin','organizations':['org'],
        'url':'https://metadata.test/mcp','profile':'sellersprite','tools':[]}
    assert not MCPApproval.model_validate(config).enabled
    with pytest.raises(ValidationError):MCPApproval.model_validate({**config,'enabled':True})


def test_official_delivery_rules_do_not_claim_mobile_or_account_approval():
    from app.agents import amazon
    from app.agents.amazon_export import pixel_checks
    from tests.test_agent_amazon import sample_plan
    cfg=amazon.rules();spec=cfg['modules']['premium_full_image']
    assert not cfg['account_entitlement_verified'] and 'not implemented' in cfg['content_types']['brand_story']
    assert spec['native_text_fields']['body']=='footer.textList'
    checks=pixel_checks(2928,1200,spec)
    assert checks=={'dimensions_match':False,'minimum_pixels_met':True,'mobile_asset_verified':False}
    assert pixel_checks(970,300,cfg['modules']['basic_image_text_overlay'])['minimum_pixels_met'] is None
    plan=sample_plan(str(uuid4()));plan.aplus_type='premium'
    for module in plan.modules:module.spec_id='premium_full_image'
    plan.modules[0].body='a\nb\nc\nd\ne'
    assert any('4行' in e for e in amazon.findings(plan))
    plan.modules[0].body='a'*301
    assert any('300字符' in e for e in amazon.findings(plan))
    plan.modules[0].body='a\nb\nc\nd'
    assert not amazon.findings(plan)


@pytest.mark.companydb
@pytest.mark.skipif(not os.environ.get('AGENT_COMPANY_TEST_DATABASE_URL'),reason='Isolated MySQL/Redis required')
async def test_real_job_heartbeat_renews_db_and_redis_without_provider(second_context, caplog):
    from app.models.tasks import Job
    from app.models.quota import QuotaReservation
    from app.workers.tasks.jobs import _job_heartbeat_loop
    ctx=second_context
    planned=await send(ctx,'生成一张图片')
    submitted=await confirm(ctx,planned)
    jid=submitted['jobs'][0]['id'];old=datetime.now(timezone.utc)-timedelta(minutes=5)
    async with ctx['session_factory']() as db:
        job=await db.get(Job,jid);job.status='running';job.heartbeat_at=old
        rid=job.quota_reservation_id
        reservation=await db.get(QuotaReservation,rid);reservation.expires_at=old
        await db.commit()
    lease=SimpleNamespace(key_id='test-heartbeat-'+str(uuid4()))
    key=f'resource:key:{lease.key_id}:inflight'
    await ctx['redis'].set(key,1,ex=20)
    task=asyncio.create_task(_job_heartbeat_loop(ctx['session_factory'],ctx['redis'],ctx['settings'],
        job_id=jid,reservation_id=rid,lease=lease))
    try:
        for _ in range(50):
            if await ctx['redis'].ttl(key)>20:break
            await asyncio.sleep(.1)
        assert await ctx['redis'].ttl(key)>20
        async with ctx['session_factory']() as db:
            job=await db.get(Job,jid);reservation=await db.get(QuotaReservation,rid)
            assert job.heartbeat_at.replace(tzinfo=timezone.utc)>old
            assert reservation.expires_at.replace(tzinfo=timezone.utc)>datetime.now(timezone.utc)
        assert 'job_heartbeat_failed' not in caplog.text
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):await task
        await release_resource(ctx['redis'],lease)
    assert not await ctx['redis'].exists(key)
    assert ctx.get('provider_active',0)==0
