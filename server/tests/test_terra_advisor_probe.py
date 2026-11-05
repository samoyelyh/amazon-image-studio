"""Explicit real text-only probe. No production writes or image requests."""
import builtins
import json
from math import ceil
from statistics import median,mean
from time import monotonic
from uuid import uuid4
import pytest
from sqlalchemy import select
from pydantic import SecretStr
from app.models.tasks import Job,JobAttempt,ProviderModel,Provider,ApiKey,ResourcePool,ResourcePoolKey
from app.models.hermes_agent import HermesConversation
from app.schemas.tasks import JobSubmitRequest
from app.services.task_service import submit_job
from tests.test_agent_control import agent_context
from tests.test_agent_chat_v2 import chat_context,send
from tests.test_agent_second_round import second_context
from tests.test_agent_autonomous import autonomous_context
from tests.test_amazon_advisor import advisor

pytestmark=pytest.mark.skipif(not hasattr(builtins,'_terra_seed'),reason='Explicit gpt-6.1-terra text-only probe')


async def test_terra_route_and_aplus(advisor,monkeypatch):
    ctx=advisor;root=builtins._terra_output;root.mkdir(parents=True,exist_ok=False)
    report={'model':'gpt-6.1-terra','protocol':'configured chat/completions','image_requests':0,'calls':[],'routing':[]}
    def save():(root/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    seed=builtins._terra_seed;resource=seed['operations']['listing.plan']
    ctx['settings'].api_key_encryption_key=SecretStr(seed['encryption_key'])
    ctx['settings'].agent_control_text_model='workflow-text';ctx['settings'].provider_request_timeout_seconds=180
    ctx['settings'].job_max_attempts=1
    async with ctx['session_factory']() as db:
        model=await db.scalar(select(ProviderModel).where(ProviderModel.code=='workflow-text'))
        provider=Provider(code='isolated-terra',name='Isolated Terra probe',provider_type=resource['provider_type'],base_url=resource['base_url'],config_json=resource['provider_config'])
        db.add(provider);await db.flush()
        model.provider_id=provider.id;model.upstream_model='gpt-6.1-terra';model.config_json=resource['model_config']
        key=ApiKey(provider_id=provider.id,label='Isolated Terra key',secret_ciphertext=resource['secret_ciphertext'],fingerprint='isolated-terra',secret_suffix='hidden',max_concurrency=1,status='active')
        db.add(key);await db.flush()
        pool=await db.scalar(select(ResourcePool).where(ResourcePool.model_id==model.id))
        for link in (await db.scalars(select(ResourcePoolKey).where(ResourcePoolKey.resource_pool_id==pool.id))).all():link.enabled=False
        db.add(ResourcePoolKey(resource_pool_id=pool.id,api_key_id=key.id));await db.commit()
    from app.providers.registry import get_provider_adapter
    class TextOnly:
        def __init__(self,typ,settings):self.adapter=get_provider_adapter(typ,settings)
        async def execute(self,**kwargs):
            if kwargs['capability']!='text_generation' or len(report['calls'])>=4:
                raise RuntimeError('Probe is text-only, maximum four distinct requests')
            entry={'number':len(report['calls'])+1,'status':'requested','input_characters':len(str(kwargs['payload'].get('user_prompt','')))}
            report['calls'].append(entry);save();start=monotonic()
            try:
                value=await self.adapter.execute(**kwargs)
                entry.update(status='returned',seconds=round(monotonic()-start,3),usage=(value.metadata or {}).get('usage'))
                return value
            except Exception as error:
                entry.update(status='failed_or_unknown',seconds=round(monotonic()-start,3),error_code=getattr(error,'code',type(error).__name__),http_status=getattr(error,'http_status',None))
                raise
            finally:save()
    monkeypatch.setattr(ctx['worker'],'get_provider_adapter',lambda typ,settings:TextOnly(typ,settings))
    cases=[
        {'id':'a','request':'为上传的定制球衣做一整套Amazon A+，已有完整商品资料，不需要调研','expected':'business.save_aplus_plan'},
        {'id':'b','request':'给这件衣服做一整套6张亚马逊Listing附图，不是A+，每张独立策划','expected':'business.save_aplus_plan'},
        {'id':'c','request':'10张原图分别换成足球场背景，人物衣服不变','expected':'business.create_images'},
        {'id':'d','request':'当前方案的第2和第4张修改，其他保持不变','expected':'business.revise_amazon_modules'},
        {'id':'e','request':'参考竞品B0716YP6VJ，先查市场再给我A+方案','expected':'mcp.ss_mcp.asin.detail'},
        {'id':'f','request':'跳过竞品研究，沿用上传商品和刚才的品牌风格做A+','expected':'business.save_aplus_plan'},
    ]
    instructions=('这是只选择能力、不执行的路由测验。只输出合法JSON {"results":[{"id":"a","skill":"...","tool":"...","research_needed":false,"deliverable":"aplus/listing/edit/revise/research"}]}。'
        '允许Skill: amazon-aplus-planner, amazon-market-insight, image-creation。'
        '允许Tool: business.save_aplus_plan（整套Listing或A+方案）, business.create_images（编辑原图）, business.revise_amazon_modules（指定现有模块）, mcp.ss_mcp.asin.detail（市场查询）。'
        '不编造结果，不请求费用确认，完整资料时不查市场，批量换背景不是换衣矩阵。')
    for repeat in range(3):
        async with ctx['session_factory']() as db:
            conv=await db.get(HermesConversation,ctx['chat']['id'])
            job,_=await submit_job(db,ctx['settings'],organization_id=ctx['first_org'],user_id=conv.user_id,
                payload=JobSubmitRequest(operation_code='listing.plan',workspace_type='listing',queue_name='planning_queue',capability='text_generation',model_code='workflow-text',
                    idempotency_key=f'terra-route-{repeat}-{uuid4()}',input={'system_prompt':instructions,'user_prompt':json.dumps({'cases':[{k:v for k,v in c.items() if k!='expected'} for c in cases],'wording_variant':repeat},ensure_ascii=False)}))
            jid=job.id;await db.commit()
        await ctx['worker']._execute_job(jid)
        async with ctx['session_factory']() as db:
            job=await db.get(Job,jid);attempt=await db.scalar(select(JobAttempt).where(JobAttempt.job_id==jid).order_by(JobAttempt.attempt_number.desc()).limit(1))
            entry={'job_id':jid,'status':job.status,'http_status':getattr(attempt,'http_status',None),'error_code':getattr(attempt,'error_code',None)}
            report['routing'].append(entry);save()
            if job.status!='succeeded':pytest.fail('Terra upstream failed; no retry or image request: '+str(entry['error_code']))
            response=json.loads(job.result_json['metadata']['text']);entry['response']=response
            choices={r['id']:r for r in response.get('results',[])}
            entry['correct']=sum(choices.get(c['id'],{}).get('tool')==c['expected'] for c in cases);save()
            entry['schema_valid']=set(choices)=={c['id'] for c in cases}
            save()
            assert entry['schema_valid'],'Structured JSON failed; no production configuration change'
    latency=[c['seconds'] for c in report['calls']]
    report['routing_statistics']={'n':len(latency),'mean':mean(latency),'p50':median(latency),'p95_nearest_rank':sorted(latency)[ceil(.95*len(latency))-1],'sample_warning':'n=3, not a stable production P95'};save()
    raw=builtins._terra_reference.read_bytes()
    uploaded=(await ctx['client'].post('/api/v1/assets',headers=ctx['headers'],data={'category':'product_reference','private_scope':'agent_chat'},files={'file':('authorized-custom-hoodie.png',raw,'image/png')})).json()
    attachment=(await ctx['client'].post(f"/api/v1/agent/conversations/{ctx['chat']['id']}/attachments",headers=ctx['headers'],json={'asset_id':uploaded['id']})).json()
    ctx['settings'].agent_auto_submissions_per_minute=30
    run=await send(ctx,'只给我看方案，先不要生图。给参考图的黑橙渐变连帽上衣做3个美国Basic A+模块，围绕真实图案、礼品和日常穿着。只使用可见商品事实，不主张材质、认证、球队授权或未确认的定制服务。已有产品资料，不需要查询竞品。', [attachment['id']],creative_module='amazon_aplus')
    jid=run['jobs'][0]['id'];await ctx['worker']._execute_job(jid)
    run=(await ctx['client'].get('/api/v1/agent/runs/'+run['id'],headers=ctx['headers'])).json()
    report['aplus']={'run_id':run['id'],'status':run['status'],'error_code':run.get('error_code'),'jobs':run['jobs'],'events':run['events']};save()
    assert run['status']=='awaiting_review',run['status']
    assert not any(j['capability']!='text_generation' for j in run['jobs'])
    history=(await ctx['client'].get('/api/v1/agent/conversations/'+ctx['chat']['id'],headers=ctx['headers'])).json()
    report['aplus']['plans']=history['amazon_plans'];save()
