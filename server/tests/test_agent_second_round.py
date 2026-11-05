import asyncio
import json
import os
from uuid import uuid4
from datetime import datetime,timezone

import pytest
from pydantic import SecretStr
from sqlalchemy import select,func
from app.models.tasks import Job
from app.models.content import GeneratedOutput,Asset
from app.models.identity import User,OrganizationMember
from app.models.hermes_agent import HermesConversation
from app.core.config import get_settings
from app.services.storage_service import get_storage_service
from tests.test_agent_control import agent_context,ticket
from tests.test_agent_chat_v2 import chat_context,send,confirm
from tests.test_batch_tryon_workflow import upload
from tests.company_agent_support import DiskTestStorage,install_mock_worker
from tests.test_agent_capabilities import local_mcp_server


@pytest.fixture
async def second_context(chat_context,tmp_path,monkeypatch):
    ctx=chat_context;ctx['settings'].agent_dynamic_capabilities_enabled=True
    ctx['storage']=DiskTestStorage(tmp_path/'objects')
    ctx['app'].dependency_overrides[get_storage_service]=lambda:ctx['storage']
    if ctx['company_database_url']:
        from app.agents.runtime import checkpoint_store
        ctx['settings'].agent_checkpoint_url=SecretStr(ctx['company_database_url'].replace('mysql+asyncmy://','mysql://',1))
        async with checkpoint_store(ctx['settings'],setup=True):pass
        import redis.asyncio as redis
        from app.infrastructure.redis import get_redis_client
        ctx['redis']=redis.Redis.from_url('redis://127.0.0.1:16387/0',decode_responses=True)
        ctx['app'].dependency_overrides[get_redis_client]=lambda:ctx['redis']
        from tests.company_agent_support import isolated_minio_storage
        ctx['storage']=isolated_minio_storage()
    from app.models.quota import QuotaAccount
    async with ctx['session_factory']() as db:
        account=await db.scalar(select(QuotaAccount).where(QuotaAccount.organization_id==ctx['first_org']))
        account.balance=10000
        await db.commit()
    ctx['worker']=install_mock_worker(ctx,monkeypatch)
    return ctx


async def attach(ctx,filename,category='product_reference'):
    picture=await upload(ctx['client'],ctx['headers'],category,filename)
    a=(await ctx['client'].post(f"/api/v1/agent/conversations/{ctx['chat']['id']}/attachments",headers=ctx['headers'],json={'asset_id':picture['id']})).json()
    return picture,a


async def finish(ctx,run):
    for job in run['jobs']:
        if job['status'] not in {'succeeded','failed','cancelled'}:await ctx['worker']._execute_job(job['id'])
    response=await ctx['client'].get('/api/v1/agent/runs/'+run['id'],headers=ctx['headers'])
    assert response.status_code==200,response.text
    return response.json()


async def test_case_a_b_outputs_and_chat_while_image_is_running(second_context):
    ctx=second_context
    _,a=await attach(ctx,'garment-a.png')
    first=await send(ctx,'生成穿这件球衣的模特展示图',[a['id']]);created=await confirm(ctx,first)
    assert created['jobs'][0]['status']=='queued'
    # Original image Job is still queued while a separate chat turn completes.
    independent=await send(ctx,'查看任务进度')
    assert independent['status']=='completed'
    ready=await finish(ctx,created)
    assert ready['status']=='completed' and len(ready['outputs'])==1
    assert ready['verification']['stored_output_count']==1 and ready['verification']['mock_image_response_count']==1
    output=ready['outputs'][0]
    second=await send(ctx,'背景换成球场，衣服保持不变',parent_output_id=output['id'])
    assert second['plan']['actions'][0]['arguments']['parent_output_id']==output['id']
    edited=await finish(ctx,await confirm(ctx,second))
    assert edited['outputs'][0]['version']==2 and edited['outputs'][0]['parent_output_id']==output['id']
    history=(await ctx['client'].get('/api/v1/agent/conversations/'+ctx['chat']['id'],headers=ctx['headers'])).json()
    assert len([o for r in history['runs'] for o in r['outputs']])==2
    for o in [output,edited['outputs'][0]]:assert (await ctx['client'].get(o['download_url'],headers=ctx['headers'])).status_code==200


@pytest.mark.companydb
async def test_same_chat_independent_plans_survive_upload_and_reverse_completion(second_context):
    ctx=second_context
    image_a,a=await attach(ctx,'garment-parallel-a.png')
    first=await send(ctx,'生成穿这件球衣的模特展示图',[a['id']])
    image_b,b=await attach(ctx,'garment-parallel-b.png')
    second=await send(ctx,'单独生成第二件球衣的模特展示图',[b['id']])
    if ctx['company_database_url']:
        submitted_a,submitted_b=await asyncio.gather(confirm(ctx,first),confirm(ctx,second))
    else:
        submitted_a=await confirm(ctx,first)
        submitted_b=await confirm(ctx,second)
    assert submitted_a['jobs'][0]['status']=='queued'
    assert submitted_b['jobs'][0]['id']!=submitted_a['jobs'][0]['id']
    async with ctx['session_factory']() as db:
        jobs=[await db.get(Job,r['jobs'][0]['id']) for r in (submitted_a,submitted_b)]
        assert jobs[0].input_json['reference_asset_ids']==[image_a['id']]
        assert jobs[1].input_json['reference_asset_ids']==[image_b['id']]
        assert jobs[0].project_id==jobs[1].project_id
    # Second completes first. Neither original message nor image numbering changes.
    ready_b=await finish(ctx,submitted_b)
    number_b=ready_b['outputs'][0]['number']
    ready_a=await finish(ctx,submitted_a)
    assert {ready_a['outputs'][0]['number'],number_b}=={1,2}
    detail=(await ctx['client'].get('/api/v1/agent/conversations/'+ctx['chat']['id'],headers=ctx['headers'])).json()
    by_run={r['id']:r for r in detail['runs']}
    assert [m['role'] for m in detail['messages']]==['user','assistant','user','assistant']
    for ready in (ready_a,ready_b):
        assert by_run[ready['id']]['outputs']==ready['outputs']
        assert any(m.get('metadata',{}).get('run_id')==ready['id'] for m in detail['messages'])
    assert len((await confirm(ctx,first))['jobs'])==1


async def test_referenced_asset_change_still_invalidates_chat_confirmation(second_context):
    ctx=second_context
    image,a=await attach(ctx,'garment-mutable.png')
    planned=await send(ctx,'生成模特展示图',[a['id']])
    async with ctx['session_factory']() as db:
        asset=await db.get(Asset,image['id']);asset.sha256='f'*64;await db.commit()
    response=await ctx['client'].post('/api/v1/agent/runs/'+planned['id']+'/confirm',headers=ctx['headers'],json=ticket(planned))
    assert response.status_code==409 and 'agent.plan_stale' in response.text


async def test_case_c_6_by_32_understanding_samples_and_mock_b_batch(second_context):
    ctx=second_context;attachments=[]
    for i in range(6):attachments.append((await attach(ctx,f'template-{i}.png'))[1]['id'])
    for i in range(32):attachments.append((await attach(ctx,f'garment-{i}.png'))[1]['id'])
    run=await send(ctx,'把32件服装套到6个模板，先识别素材和批量套图规则',attachments)
    assert run['plan']['budget']['analysis_count']==38 and not run['jobs']
    understood=await finish(ctx,await confirm(ctx,run))
    assert understood['status']=='completed',understood
    history=(await ctx['client'].get('/api/v1/agent/conversations/'+ctx['chat']['id'],headers=ctx['headers'])).json()
    plan=history['production_plans'][0]
    assert plan['combination_count']==192 and len(plan['template_rules'])==6 and len(plan['garment_rules'])==32
    base=f"/api/v1/agent/conversations/{ctx['chat']['id']}/production-plans/{plan['id']}"
    confirmed=(await ctx['client'].post(base+'/confirm',headers=ctx['headers'],json={'expected_revision':plan['revision']})).json()
    early=await ctx['client'].post(f"/api/v1/agent/conversations/{ctx['chat']['id']}/messages",headers=ctx['headers'],json={
        'chat_mode':True,'content':'正式批量套图','client_request_id':str(uuid4()),'production_plan_id':plan['id'],
        'production_revision':confirmed['revision'],'production_stage':'production'})
    assert early.status_code==409 and 'agent.samples_not_approved' in early.text
    sample=await send(ctx,'生成样图验证',production_plan_id=plan['id'],production_revision=confirmed['revision'],production_stage='validation')
    assert sample['plan']['image_count']==6
    sampled=await finish(ctx,await confirm(ctx,sample))
    assert len(sampled['outputs'])==6
    for output in sampled['outputs']:
        approved=await ctx['client'].post(base+'/approve-sample',headers=ctx['headers'],json={
            'output_id':output['id'],'expected_revision':confirmed['revision']})
        assert approved.status_code==200,approved.text
    production=await send(ctx,'正式批量套图',production_plan_id=plan['id'],production_revision=confirmed['revision'],production_stage='production')
    assert production['plan']['image_count']==192
    generated=await confirm(ctx,production)
    assert len(generated['jobs'])==192
    assert len((await confirm(ctx,production))['jobs'])==192
    async with ctx['session_factory']() as db:
        jobs=list((await db.scalars(select(Job).where(Job.id.in_([j['id'] for j in generated['jobs']])))).all())
        assert len({j.client_item_id for j in jobs})==192
        for job in jobs:
            meta=job.input_json['metadata'];assert meta['garment_rules']['visual_facts']==['仅测试素材 '+meta['garment_filename']]
            assert len(job.input_json['reference_asset_ids'])==2
        assert all(j.operation_code=='batch_tryon.generate' for j in jobs)
    # Complete the entire batch with the original Worker and Mock Provider, not 192 real paid requests.
    result=await finish(ctx,generated)
    assert result['status']=='completed' and len(result['outputs'])==192
    # Cached understanding does not create another 38 text Jobs.
    cached=await send(ctx,'批量套图识别',attachments)
    assert cached['plan']['budget']['analysis_count']==0


async def test_rules_revision_and_other_users_cannot_approve_or_submit(second_context):
    ctx=second_context
    ids=[(await attach(ctx,'template.png'))[1]['id'],(await attach(ctx,'garment.png'))[1]['id']]
    completed=await finish(ctx,await confirm(ctx,await send(ctx,'批量套图',ids)))
    assert completed['status']=='completed'
    detail=(await ctx['client'].get('/api/v1/agent/conversations/'+ctx['chat']['id'],headers=ctx['headers'])).json()
    p=detail['production_plans'][0];base=f"/api/v1/agent/conversations/{ctx['chat']['id']}/production-plans/{p['id']}"
    login=(await ctx['client'].post('/api/v1/auth/login',json={'account':'first-viewer','password':'viewer-password'})).json()
    denied=await ctx['client'].post(base+'/confirm',headers={'Authorization':'Bearer '+login['access_token']},json={'expected_revision':1})
    assert denied.status_code in (403,404)
    stale=await ctx['client'].post(base+'/confirm',headers=ctx['headers'],json={'expected_revision':100})
    assert stale.status_code==409


async def test_actual_text_job_protocol_roles_and_dynamic_selection_without_real_model_fee(second_context):
    ctx=second_context;ctx['settings'].agent_control_planner='existing_text'
    image,a=await attach(ctx,'garment-model-protocol.png')
    ctx['mock_decision']={'summary':'使用当前服装参考创建模特展示图','skills':['image-creation'],
        'asset_roles':[{'asset_id':image['id'],'role':'garment','confidence':.98,'reason':'测试模型响应：单件球衣参考'}],
        'steps':[{'capability_id':'business.create_images','arguments':{'instruction':'生成穿这件球衣的模特展示图'},'reason':'单图请求使用原生图工具'}]}
    text_plan=await send(ctx,'生成穿这件球衣的模特展示图',[a['id']])
    assert text_plan['plan']['actions'][0]['tool']=='plan_intent'
    image_plan=await finish(ctx,await confirm(ctx,text_plan))
    assert image_plan['status']=='awaiting_confirmation' and image_plan['verification']['model_inference']=='mock'
    assert any(e['type']=='asset_roles_inferred' for e in image_plan['events'])
    result=await finish(ctx,await confirm(ctx,image_plan))
    assert result['status']=='completed' and result['verification']['stored_output_count']==1
    assert result['verification']['mock_image_response_count']==1
    history=(await ctx['client'].get('/api/v1/agent/conversations/'+ctx['chat']['id'],headers=ctx['headers'])).json()
    assert history['attachments'][0]['role']=='garment'


async def test_replanner_confirmation_has_distinct_idempotency_scope(second_context):
    ctx=second_context;ctx['settings'].agent_control_planner='existing_text'
    ctx['mock_decision']={'summary':'读取当前素材','steps':[{'capability_id':'business.current_context','arguments':{},'reason':'先查实际数据'}]}
    first=await send(ctx,'查看当前素材')
    feedback=await finish(ctx,await confirm(ctx,first))
    assert feedback['status']=='awaiting_confirmation'
    ctx['mock_decision']={'summary':'读取已完成','steps':[],'done':True}
    second=await confirm(ctx,feedback)
    assert len({j['id'] for j in second['jobs']})==2
    finished=await finish(ctx,second)
    assert finished['status']=='completed' and not finished['outputs']


@pytest.mark.companydb
@pytest.mark.skipif(not os.environ.get('AGENT_COMPANY_TEST_DATABASE_URL'),reason='Explicit isolated MySQL required')
async def test_company_5_users_15_parallel_sessions_and_cross_process_restart(second_context,tmp_path,local_mcp_server,monkeypatch):
    ctx=second_context
    from app.security.passwords import hash_password
    async with ctx['session_factory']() as db:
        original=await db.get(OrganizationMember,ctx['first_admin_membership'])
        for i in range(5):
            user=User(account=f'company-user-{i}',display_name=f'Employee {i}',password_hash=hash_password('employee-test-pass'))
            db.add(user);await db.flush();db.add(OrganizationMember(organization_id=ctx['first_org'],user_id=user.id,role_id=original.role_id))
        await db.commit()
    approvals={'schema_version':1,'skills':[],'mcp_servers':[{'id':'company_public','version':'1','enabled':True,
        'approved_by':'isolated-test-admin','organizations':[ctx['first_org']],'url':local_mcp_server['url'],'allow_local_http':True,
        'timeout_seconds':10,'max_calls_per_run':2,'tools':[{'name':'search','description':'读取公开测试资料','input_schema':local_mcp_server['schema'],
            'permissions':['jobs.read'],'risk':'read_only','may_charge':False,'keywords':['research']}]}]}
    manifest=tmp_path/'approved.json';manifest.write_text(json.dumps(approvals),encoding='utf-8')
    ctx['settings'].agent_capability_manifest=str(manifest)
    identities=[]
    for i in range(5):
        login=(await ctx['client'].post('/api/v1/auth/login',json={'account':f'company-user-{i}','password':'employee-test-pass'})).json()
        identities.append({'Authorization':'Bearer '+login['access_token']})
    start=asyncio.Event()
    async def scenario(user,session_index):
        headers=identities[user];client=ctx['client']
        conv=(await client.post('/api/v1/agent/conversations',headers=headers,json={'context_kind':'chat'})).json()
        image=await upload(client,headers,'product_reference',f'employee-{user}-session-{session_index}.png')
        attached=(await client.post(f"/api/v1/agent/conversations/{conv['id']}/attachments",headers=headers,json={'asset_id':image['id']})).json()
        await start.wait()
        response=await client.post(f"/api/v1/agent/conversations/{conv['id']}/messages",headers=headers,json={'chat_mode':True,
            'content':'生成穿这件球衣的模特展示图','attachment_ids':[attached['id']],'client_request_id':str(uuid4())})
        assert response.status_code==200,response.text
        plan=response.json()
        confirmed=await client.post('/api/v1/agent/runs/'+plan['id']+'/confirm',headers=headers,json=ticket(plan))
        assert confirmed.status_code==200,confirmed.text
        again=await client.post('/api/v1/agent/runs/'+plan['id']+'/confirm',headers=headers,json=ticket(plan))
        assert again.json()['jobs']==confirmed.json()['jobs']
        for content in ['查看任务进度',f'research public sample employee{user}session{session_index}']:
            message=await client.post(f"/api/v1/agent/conversations/{conv['id']}/messages",headers=headers,json={'chat_mode':True,'content':content,'client_request_id':str(uuid4())})
            assert message.status_code==200,message.text
            assert message.json()['status']=='completed',message.text
        return {'headers':headers,'conversation_id':conv['id'],'run':confirmed.json(),'user':user}
    pending=[asyncio.create_task(scenario(u,s)) for u in range(5) for s in range(3)]
    start.set();outcomes=await asyncio.gather(*pending,return_exceptions=True)
    failures=[r for r in outcomes if isinstance(r,BaseException)]
    assert not failures,[(type(r).__name__,str(r)[:500]) for r in failures]
    results=outcomes
    assert len({r['conversation_id'] for r in results})==15
    assert len(local_mcp_server['calls'])==15
    all_ids={j['id'] for r in results for j in r['run']['jobs']};assert len(all_ids)==15
    for _ in range(8):
        ctx['provider_delay']=.2
        async with ctx['session_factory']() as db:
            jobs=list((await db.scalars(select(Job).where(Job.id.in_(all_ids)))).all())
        waiting=[j.id for j in jobs if j.status not in {'succeeded','failed','cancelled'}]
        if not waiting:break
        await asyncio.gather(*(ctx['worker']._execute_job(j) for j in waiting))
        await asyncio.sleep(.1)
    for r in results:
        ready=(await ctx['client'].get('/api/v1/agent/runs/'+r['run']['id'],headers=r['headers'])).json()
        assert ready['status']=='completed' and len(ready['outputs'])==1
        other=identities[(r['user']+1)%5]
        for path in ['/api/v1/agent/runs/'+ready['id'],ready['outputs'][0]['download_url']]:
            assert (await ctx['client'].get(path,headers=other)).status_code==404
    # A brand-new OS process reloads a pending confirmation, executes original Worker, then reloads again.
    image,a=await attach(ctx,'restart-reference.png')
    planned=await send(ctx,'生成一张图片',[a['id']])
    artifact=tmp_path/'restart.json';artifact.write_text(json.dumps({'headers':ctx['headers'],'run_id':planned['id'],
        'conversation_id':ctx['chat']['id'],'ticket':ticket(planned),'storage_root':None,'isolated_minio':True,
        'manifest':str(manifest)}),encoding='utf-8')
    import subprocess,sys
    env={**os.environ,'AGENT_COMPANY_TEST_JWT':ctx['settings'].jwt_secret.get_secret_value()}
    async def probe(phase):
        proc=await asyncio.to_thread(subprocess.run,[sys.executable,'-m','tests.company_agent_restart_probe',phase,str(artifact)],
            capture_output=True,text=True,encoding='utf-8',env=env,timeout=90)
        assert proc.returncode==0,f'isolated restart phase {phase} failed: {proc.stderr[-1800:]}'
        return json.loads(proc.stdout.splitlines()[-1])
    before=await probe('read');assert before['status']=='awaiting_confirmation'
    committed=await probe('confirm');assert len(committed['jobs'])==1
    finished=await probe('complete');assert finished['status']=='completed' and len(finished['outputs'])==1
    restored=await probe('read');assert restored==finished
    replay=await probe('replay');assert replay['jobs']==finished['jobs'] and replay['outputs']==finished['outputs']
    assert restored['attachments']==1 and restored['downloads_ok'] and restored['events']>0
    # Actual Celery publish/consume across an OS process; still mandatory Mock Provider.
    from celery import Celery
    from app.services.task_service import dispatch_jobs
    from app.workers.celery_app import celery_app
    broker=Celery('isolated-company-producer',broker='redis://127.0.0.1:16387/6',backend='redis://127.0.0.1:16387/7')
    import redis.asyncio as test_redis
    ready_client=test_redis.Redis.from_url('redis://127.0.0.1:16387/6',decode_responses=True)
    ready_key='company-worker-ready:'+str(uuid4())
    proc=subprocess.Popen([sys.executable,'-m','tests.company_agent_celery_probe',str(artifact)],
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',
        env={**env,'AGENT_COMPANY_TEST_WORKER_READY':ready_key})
    try:
        for _ in range(150):
            if await ready_client.get(ready_key):break
            assert proc.poll() is None,'isolated Celery process exited before ready'
            await asyncio.sleep(.2)
        else:raise AssertionError('isolated Celery process did not become ready')
        queued=await confirm(ctx,await send(ctx,'生成一张图片'))
        async with ctx['session_factory']() as db:
            job=await db.get(Job,queued['jobs'][0]['id']);job.queue_name='agent_company_probe'
            with monkeypatch.context() as publish_patch:
                publish_patch.setattr(celery_app,'send_task',broker.send_task)
                assert await dispatch_jobs(db,[job])==1
        for _ in range(240):
            actual=(await ctx['client'].get('/api/v1/agent/runs/'+queued['id'],headers=ctx['headers'])).json()
            if actual['status']=='completed':break
            assert actual['status'] not in {'failed','remote_unknown'},actual.get('error_code')
            await asyncio.sleep(.25)
        assert actual['status']=='completed' and len(actual['outputs'])==1
        assert actual['verification']['mock_image_response_count']==1
    finally:
        broker.control.shutdown(destination=['agent-company-probe@localhost'])
        try:await asyncio.to_thread(proc.wait,timeout=10)
        except subprocess.TimeoutExpired:
            proc.terminate();await asyncio.to_thread(proc.wait,timeout=10)
        if proc.stdout:proc.stdout.close()
        broker.close();await ready_client.aclose()
    ctx['acceptance']={'users':5,'sessions':15,'mcp_calls':len(local_mcp_server['calls']),'image_jobs':15,
        'provider_max_active':ctx.get('provider_max_active'),'restart_processes':5,'celery_process_image_jobs':1}
    print('COMPANY_ACCEPTANCE '+json.dumps(ctx['acceptance']),flush=True)
