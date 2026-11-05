"""V2 chat acceptance against isolated services; no live model or production data."""
from uuid import uuid4
from datetime import datetime, timezone
import json

import pytest
from sqlalchemy import select, func
from app.models.tasks import Job, ProviderModel, ModelCapability, ResourcePool, OperationResourcePool
from app.models.content import Asset, GeneratedOutput, Project, ProjectAsset
from app.models.quota import QuotaRule, QuotaAccount
from app.agents.intent_router import IntentRouter
from tests.test_agent_control import agent_context, ticket
from tests.test_batch_tryon_workflow import upload, PNG


@pytest.fixture
async def chat_context(agent_context):
    ctx = agent_context
    async with ctx['session_factory']() as db:
        model = await db.scalar(select(ProviderModel).where(ProviderModel.code == 'workflow-image'))
        pool = await db.scalar(select(ResourcePool).where(ResourcePool.model_id == model.id))
        for cap in ('image_generation', 'multi_image_reference'):
            db.add(ModelCapability(model_id=model.id, capability=cap))
        for cap in ('image_generation', 'image_edit', 'multi_image_reference'):
            db.add(OperationResourcePool(operation_code='listing.generate', resource_pool_id=pool.id, required_capability=cap))
        text_model = await db.scalar(select(ProviderModel).where(ProviderModel.code == 'workflow-text'))
        text_pool = await db.scalar(select(ResourcePool).where(ResourcePool.model_id == text_model.id))
        db.add(OperationResourcePool(operation_code='listing.plan', resource_pool_id=text_pool.id, required_capability='text_generation'))
        db.add(QuotaRule(organization_id=None, operation_code='listing.plan', name='Mock text planning', base_cost=1,
            model_multipliers={}, quality_multipliers={}, resolution_multipliers={}, resource_pool_multipliers={},
            effective_from=datetime(2020,1,1,tzinfo=timezone.utc)))
        await db.commit()
    ctx['settings'].agent_control_writes_enabled = ctx['settings'].agent_control_model_calls_enabled = True
    created = await ctx['client'].post('/api/v1/agent/conversations', headers=ctx['headers'], json={'context_kind':'chat'})
    assert created.status_code == 201, created.text
    assert created.json()['project_id'] is None
    ctx['chat'] = created.json()
    yield ctx


async def send(ctx, content, attachments=None, **extras):
    result = await ctx['client'].post(f"/api/v1/agent/conversations/{ctx['chat']['id']}/messages", headers=ctx['headers'],
        json={'chat_mode':True,'content':content,'attachment_ids':attachments or [],'client_request_id':str(uuid4()),**extras})
    assert result.status_code == 200, result.text
    return result.json()


async def confirm(ctx, run):
    response = await ctx['client'].post(f"/api/v1/agent/runs/{run['id']}/confirm", headers=ctx['headers'], json=ticket(run))
    assert response.status_code == 200, response.text
    return response.json()


async def complete(ctx, monkeypatch, job_id):
    from app.workers.tasks import jobs as worker
    from app.providers.base import ProviderOutput, ProviderResult
    class MockProvider:
        async def execute(self, **kwargs):
            if ctx.get('_browser_echo_reference'):
                refs=kwargs['payload'].get('reference_images') or []
                if refs:
                    ref=refs[0]
                    if isinstance(ref,dict) and isinstance(ref.get('content'),bytes):
                        return ProviderResult([ProviderOutput(ref['content'],ref['mime_type'],'mock-echo.png')],
                            provider_request_id='mock-echo-no-ai',metadata={'mock_provider':True})
            return ProviderResult([ProviderOutput(PNG,'image/png','mock-chat.png')],provider_request_id='no-live-call')
    for name, value in [('get_settings',lambda:ctx['settings']),('get_engine',lambda:ctx['engine']),
            ('get_redis_client',lambda:ctx['redis']),('get_storage_service',lambda:ctx['storage'])]:
        monkeypatch.setattr(worker,name,value)
    monkeypatch.setattr(worker,'get_provider_adapter',lambda *args:MockProvider())
    await worker._execute_job(job_id)


async def test_upload_fast_result_and_continuous_edit_use_original_worker(chat_context, monkeypatch):
    ctx = chat_context
    picture = await upload(ctx['client'],ctx['headers'],'product_reference','product.png')
    attached = await ctx['client'].post(f"/api/v1/agent/conversations/{ctx['chat']['id']}/attachments",headers=ctx['headers'],json={'asset_id':picture['id']})
    assert attached.status_code == 201, attached.text
    first = await send(ctx,'生成一张城市街道背景的模特展示图',[attached.json()['id']])
    assert first['plan']['workflow'] == 'fast' and first['plan']['budget']['estimated_cost'] == 10
    assert first['plan']['actions'][0]['tool'] == 'generate_chat_images'
    sent = await confirm(ctx,first)
    assert len(sent['jobs']) == 1
    await complete(ctx,monkeypatch,sent['jobs'][0]['id'])
    ready = (await ctx['client'].get(f"/api/v1/agent/runs/{first['id']}",headers=ctx['headers'])).json()
    assert ready['status'] == 'completed' and len(ready['outputs']) == 1
    base = ready['outputs'][0]
    assert base['number'] == 1 and base['version'] == 1
    downloaded = await ctx['client'].get(base['download_url'],headers=ctx['headers'])
    assert downloaded.status_code == 200 and downloaded.content.startswith(b'\x89PNG')
    follow = await send(ctx,'第一张的背景换成球场，其他地方保持不变')
    assert follow['plan']['workflow'] == 'edit'
    action = follow['plan']['actions'][0]['arguments']
    assert action['parent_output_id'] == base['id'] and action['reference_asset_ids'][0] == base['asset_id']
    second = await confirm(ctx,follow)
    replay = await confirm(ctx,follow)
    assert second['result'] == replay['result']
    await complete(ctx,monkeypatch,second['jobs'][0]['id'])
    edited = (await ctx['client'].get(f"/api/v1/agent/runs/{follow['id']}",headers=ctx['headers'])).json()['outputs'][0]
    assert edited['version'] == 2 and edited['parent_output_id'] == base['id'] and edited['root_output_id'] == base['id']
    assert edited['number'] == 2 and edited['asset_id'] != base['asset_id']
    restored = (await ctx['client'].get(f"/api/v1/agent/conversations/{ctx['chat']['id']}",headers=ctx['headers'])).json()
    assert restored['attachments'][0]['submitted'] is True
    assert any(m['metadata'].get('attachments') for m in restored['messages'] if m['role']=='user')
    async with ctx['session_factory']() as db:
        assert await db.scalar(select(func.count(GeneratedOutput.id))) == 2
        assert await db.scalar(select(func.count(Job.id))) == 2


async def test_fast_text_only_and_numbered_multiple_outputs(chat_context, monkeypatch):
    ctx = chat_context
    planned = await send(ctx,'生成三张写实酒红色球衣产品图')
    assert planned['plan']['image_count'] == 3 and planned['plan']['budget']['estimated_cost'] == 30
    created = await confirm(ctx,planned)
    # Complete slot 3 first: it must not become "picture 1".
    await complete(ctx,monkeypatch,created['jobs'][2]['id'])
    partial = (await ctx['client'].get(f"/api/v1/agent/runs/{planned['id']}",headers=ctx['headers'])).json()
    assert len(partial['outputs']) == 1 and partial['outputs'][0]['number'] == 3
    assert partial['status'] == 'waiting_jobs'


@pytest.mark.parametrize('message,workflow',[('生成一张模特图','fast'),('第二张领口修一下','edit'),
    ('把32件衣服套到6个模板上','production'),('做A+市场调研和设计','research'),('查看全员队列','query')])
def test_complexity_router_mock_not_all_production(message,workflow):
    assert IntentRouter.simulate(message).workflow == workflow


async def test_roles_and_research_requirements_never_fake_completion(chat_context):
    ctx = chat_context
    roles = await send(ctx,'将32件衣服套到6个模板上')
    assert roles['status'] == 'needs_input' and roles['plan']['needs_input'] == ['asset_roles']
    research = await send(ctx,'做A+市场调研并生成详情图')
    assert research['status'] == 'blocked' and research['plan']['workflow'] == 'research'
    assert research['jobs'] == [] and '未接入' in research['plan']['summary']


async def test_bulk_6x32_logical_plan_reuses_projects(chat_context):
    ctx = chat_context
    ids=[]
    for role,count in [('template',6),('garment',32)]:
        for i in range(count):
            image=await upload(ctx['client'],ctx['headers'],'product_reference',f'{role}-{i}.png')
            attached=await ctx['client'].post(f"/api/v1/agent/conversations/{ctx['chat']['id']}/attachments",headers=ctx['headers'],json={'asset_id':image['id'],'role':role})
            assert attached.status_code == 201
            ids.append(attached.json()['id'])
    plan=await send(ctx,'将32件衣服套到6个模板上',ids)
    assert plan['plan']['workflow']=='production' and plan['plan']['image_count']==192
    sent=await confirm(ctx,plan)
    assert sent['jobs']==[]
    async with ctx['session_factory']() as db:
        assert await db.scalar(select(func.count(ProjectAsset.id)).where(ProjectAsset.project_id==sent['result']['actions'][0]['result']['project_id'])) == 38


async def test_unowned_attachment_and_parent_are_denied(chat_context):
    ctx=chat_context
    response=await ctx['client'].post(f"/api/v1/agent/conversations/{ctx['chat']['id']}/attachments",headers=ctx['headers'],json={'asset_id':str(uuid4())})
    assert response.status_code==404
    response=await ctx['client'].post(f"/api/v1/agent/conversations/{ctx['chat']['id']}/messages",headers=ctx['headers'],json={'chat_mode':True,'content':'修改图片','client_request_id':str(uuid4()),'parent_output_id':str(uuid4())})
    assert response.status_code==404


async def test_budget_change_cannot_bypass_confirmation(chat_context):
    ctx=chat_context
    plan=await send(ctx,'生成一张产品图')
    async with ctx['session_factory']() as db:
        rule=await db.scalar(select(QuotaRule).where(QuotaRule.operation_code=='listing.generate'))
        rule.base_cost=100
        await db.commit()
    response=await ctx['client'].post(f"/api/v1/agent/runs/{plan['id']}/confirm",headers=ctx['headers'],json=ticket(plan))
    assert response.status_code==409 and response.json()['error']['code']=='agent.price_changed'


async def test_chat_upload_output_project_and_download_are_private(chat_context, monkeypatch):
    ctx=chat_context
    image=(await ctx['client'].post('/api/v1/assets',headers=ctx['headers'],data={'category':'product_reference','private_scope':'agent_chat'},
        files={'file':('private.png',PNG,'image/png')})).json()
    attached=(await ctx['client'].post(f"/api/v1/agent/conversations/{ctx['chat']['id']}/attachments",headers=ctx['headers'],json={'asset_id':image['id']})).json()
    plan=await send(ctx,'生成一张模特图',[attached['id']]);submitted=await confirm(ctx,plan)
    await complete(ctx,monkeypatch,submitted['jobs'][0]['id'])
    ready=(await ctx['client'].get(f"/api/v1/agent/runs/{plan['id']}",headers=ctx['headers'])).json()
    output=ready['outputs'][0]
    project_id=submitted['result']['actions'][0]['result']['project_id']
    login=(await ctx['client'].post('/api/v1/auth/login',json={'account':'first-viewer','password':'viewer-password'})).json()
    other={'Authorization':f"Bearer {login['access_token']}"}
    for path in [f"/api/v1/agent/conversations/{ctx['chat']['id']}",f"/api/v1/agent/runs/{plan['id']}",
            f"/api/v1/projects/{project_id}",f"/api/v1/jobs/{submitted['jobs'][0]['id']}"]:
        assert (await ctx['client'].get(path,headers=other)).status_code==404, path
    for aid in [image['id'],output['asset_id']]:
        for suffix in ['', '/content','/download','/url']:
            assert (await ctx['client'].get(f'/api/v1/assets/{aid}{suffix}',headers=other)).status_code==404
    library=(await ctx['client'].get('/api/v1/assets',headers=other)).json()
    assert output['asset_id'] not in {a['id'] for a in library['items']}
    projects=(await ctx['client'].get('/api/v1/projects',headers=other)).json()
    assert project_id not in {p['id'] for p in projects['items']}


async def test_pending_attachment_delete_preserves_original_and_submitted_reference(chat_context):
    ctx=chat_context
    image=await upload(ctx['client'],ctx['headers'],'product_reference','remove.png')
    url=f"/api/v1/agent/conversations/{ctx['chat']['id']}/attachments"
    a=(await ctx['client'].post(url,headers=ctx['headers'],json={'asset_id':image['id']})).json()
    assert (await ctx['client'].delete(url+'/'+a['id'],headers=ctx['headers'])).status_code==204
    assert (await ctx['client'].get(f"/api/v1/assets/{image['id']}/content",headers=ctx['headers'])).status_code==200
    a=(await ctx['client'].post(url,headers=ctx['headers'],json={'asset_id':image['id']})).json()
    await send(ctx,'生成一张图',[a['id']])
    assert (await ctx['client'].delete(url+'/'+a['id'],headers=ctx['headers'])).status_code==409
    assert (await ctx['client'].delete(f"/api/v1/assets/{image['id']}",headers=ctx['headers'])).status_code==409


async def test_missing_model_is_explicitly_blocked_without_a_job(chat_context):
    ctx=chat_context
    async with ctx['session_factory']() as db:
        bindings=list((await db.scalars(select(OperationResourcePool).where(OperationResourcePool.operation_code=='listing.generate'))).all())
        for binding in bindings:binding.enabled=False
        await db.commit()
    planned=await send(ctx,'生成一张图片')
    assert planned['status']=='blocked' and planned['plan']['blocked_reason']=='resource_pool.operation_not_bound'
    assert planned['jobs']==[]


async def test_live_router_adapter_is_confirmed_mock_job_with_vision(chat_context):
    ctx=chat_context
    ctx['settings'].agent_control_planner='existing_text'
    image=await upload(ctx['client'],ctx['headers'],'product_reference','vision.png')
    attached=(await ctx['client'].post(f"/api/v1/agent/conversations/{ctx['chat']['id']}/attachments",headers=ctx['headers'],json={'asset_id':image['id']})).json()
    first=await send(ctx,'生成一张模特图',[attached['id']])
    assert first['plan']['actions'][0]['tool']=='plan_intent'
    created=await confirm(ctx,first)
    async with ctx['session_factory']() as db:
        job=await db.get(Job,created['jobs'][0]['id'])
        assert job.operation_code=='listing.plan' and job.input_json['reference_asset_ids']==[image['id']]
        assert 'workflow' in job.input_json['system_prompt']
        job.status='succeeded';job.result_json={'metadata':{'text':json.dumps({'intent':'generate','summary':'创建图片','workflow':'fast'})}}
        await db.commit()
    ready=(await ctx['client'].get(f"/api/v1/agent/runs/{first['id']}",headers=ctx['headers'])).json()
    assert ready['status']=='awaiting_confirmation' and ready['plan']['workflow']=='fast'
    assert len(ready['jobs'])==1 # Only the earlier text job, no automatic paid image job.


@pytest.mark.skipif(__import__('os').environ.get('AGENT_BROWSER_PROBE')!='1', reason='Explicit isolated browser probe only')
@pytest.mark.companydb
async def test_browser_probe(chat_context, monkeypatch):
    """Serve the actual React build + actual isolated API; never bind production resources."""
    import asyncio
    from pathlib import Path
    import uvicorn
    from fastapi.responses import FileResponse
    ctx=chat_context
    company=bool(ctx['company_database_url'])
    if company:
        from pydantic import SecretStr
        from app.agents.runtime import checkpoint_store
        from app.infrastructure.redis import get_redis_client
        from app.services.storage_service import get_storage_service
        from tests.company_agent_support import isolated_minio_storage
        import redis.asyncio as redis
        ctx['settings'].agent_checkpoint_url=SecretStr(ctx['company_database_url'].replace('mysql+asyncmy://','mysql://',1))
        async with checkpoint_store(ctx['settings'],setup=True):pass
        ctx['redis']=redis.Redis.from_url('redis://127.0.0.1:16387/0',decode_responses=True)
        ctx['app'].dependency_overrides[get_redis_client]=lambda:ctx['redis']
        ctx['storage']=isolated_minio_storage()
        ctx['app'].dependency_overrides[get_storage_service]=lambda:ctx['storage']
        ctx['provider_release']=asyncio.Event()
    if __import__('os').environ.get('AGENT_DYNAMIC_BROWSER_PROBE')=='1':
        ctx['settings'].agent_dynamic_capabilities_enabled=True
    # SQLite StaticPool shares a single connection: serialize this test harness,
    # not the production scheduler or image concurrency.
    gate=asyncio.Lock()
    class SerialProbe:
        def __init__(self,app):self.app=app
        async def __call__(self,scope,receive,send):
            if scope['type']=='http':
                async with gate:await self.app(scope,receive,send)
            else:await self.app(scope,receive,send)
    ctx['_browser_echo_reference']=True
    second_round=__import__('os').environ.get('AGENT_SECOND_ROUND_BROWSER_PROBE')=='1'
    if second_round:
        from tests.company_agent_support import install_mock_worker
        second_worker=install_mock_worker(ctx,monkeypatch)
    stop=asyncio.Event()
    @ctx['app'].post('/_probe/stop')
    async def stop_probe():
        if company:ctx['provider_release'].set()
        stop.set()
        return {'ok':True}
    @ctx['app'].post('/_probe/release')
    async def release_probe():
        if company:ctx['provider_release'].set()
        return {'mock_provider_active':ctx.get('provider_active',0),'mock_max_active':ctx.get('provider_max_active',0)}
    dist=Path(__file__).resolve().parents[2]/'dist'
    @ctx['app'].get('/{path:path}',include_in_schema=False)
    async def frontend(path:str):
        target=(dist/path).resolve()
        if not target.is_relative_to(dist.resolve()):
            return FileResponse(dist/'index.html')
        return FileResponse(target if target.is_file() else dist/'index.html')
    server=uvicorn.Server(uvicorn.Config(ctx['app'] if company else SerialProbe(ctx['app']),host='127.0.0.1',port=18480,log_level='warning'))
    active_jobs={}
    async def process():
        while not stop.is_set():
            async with gate:
                async with ctx['session_factory']() as db:
                    query=select(Job.id).where(Job.status=='queued')
                    if not second_round:query=query.where(Job.capability!='text_generation')
                    ids=list((await db.scalars(query)).all())
                for job_id in ids:
                    if company and second_round:
                        if job_id not in active_jobs:active_jobs[job_id]=asyncio.create_task(second_worker._execute_job(job_id))
                    elif second_round:await second_worker._execute_job(job_id)
                    else:await complete(ctx,monkeypatch,job_id)
            await asyncio.sleep(.5)
    serving=asyncio.create_task(server.serve()); worker=asyncio.create_task(process())
    print('ISOLATED_BROWSER_PROBE http://127.0.0.1:18480',flush=True)
    try:
        await asyncio.wait_for(stop.wait(),timeout=1800)
    finally:
        stop.set();server.should_exit=True
        if company:ctx['provider_release'].set()
        await worker;await serving
        if active_jobs:await asyncio.gather(*active_jobs.values())
