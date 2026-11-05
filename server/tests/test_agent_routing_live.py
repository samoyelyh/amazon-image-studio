"""Opt-in real text inference, maximum seven calls, no images/research/production writes."""
import builtins
import json
from statistics import mean
from time import monotonic
from uuid import uuid4
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from app.models.tasks import Job,JobAttempt,ProviderModel,Provider,ApiKey,ResourcePool,ResourcePoolKey
from app.models.hermes_agent import HermesConversation
from app.schemas.tasks import JobSubmitRequest
from app.services.task_service import submit_job
from tests.test_agent_control import agent_context
from tests.test_agent_chat_v2 import chat_context,send
from tests.test_agent_second_round import second_context
from tests.test_agent_autonomous import autonomous_context
from tests.test_amazon_advisor import advisor

pytestmark=pytest.mark.skipif(not hasattr(builtins,'_routing_seed'),reason='Explicit bounded real text comparison')


async def test_real_context_and_routing(advisor,monkeypatch):
    ctx=advisor;root=builtins._routing_output;root.mkdir(parents=True,exist_ok=False)
    seed=builtins._routing_seed;resource=seed['operations']['listing.plan']
    report={'calls':[],'routing':[],'full_plans':[],'image_calls':0,'mcp_calls':0,'production_writes':0}
    def save():(root/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    ctx['settings'].api_key_encryption_key=SecretStr(seed['encryption_key'])
    ctx['settings'].agent_control_text_model='workflow-text';ctx['settings'].provider_request_timeout_seconds=180
    ctx['settings'].job_max_attempts=1;ctx['settings'].agent_auto_submissions_per_minute=30
    async with ctx['session_factory']() as db:
        model=await db.scalar(select(ProviderModel).where(ProviderModel.code=='workflow-text'))
        provider=Provider(code='isolated-routing',name='Isolated routing probe',provider_type=resource['provider_type'],base_url=resource['base_url'],config_json=resource['provider_config'])
        db.add(provider);await db.flush();model.provider_id=provider.id
        key=ApiKey(provider_id=provider.id,label='Isolated test key',secret_ciphertext=resource['secret_ciphertext'],fingerprint='isolated-routing',secret_suffix='hidden',max_concurrency=1,status='active')
        db.add(key);await db.flush()
        pool=await db.scalar(select(ResourcePool).where(ResourcePool.model_id==model.id))
        for link in (await db.scalars(select(ResourcePoolKey).where(ResourcePoolKey.resource_pool_id==pool.id))).all():link.enabled=False
        db.add(ResourcePoolKey(resource_pool_id=pool.id,api_key_id=key.id));await db.commit()
    active={'model':None,'purpose':None}
    async def use_model(name):
        candidate=seed['candidates'].get(name,{'upstream_model':name,'model_config':resource['model_config']})
        async with ctx['session_factory']() as db:
            model=await db.scalar(select(ProviderModel).where(ProviderModel.code=='workflow-text'))
            model.upstream_model=candidate['upstream_model'];model.config_json=candidate['model_config'];await db.commit()
        active['model']=name
    from app.providers.registry import get_provider_adapter
    class TextOnly:
        def __init__(self,typ,settings):self.adapter=get_provider_adapter(typ,settings)
        async def execute(self,**kwargs):
            if kwargs['capability']!='text_generation' or len(report['calls'])>=7:raise RuntimeError('Text-only seven-call boundary')
            entry={**active,'input_chars':len(str(kwargs['payload'].get('user_prompt',''))),'system_chars':len(str(kwargs['payload'].get('system_prompt','')))}
            report['calls'].append(entry);save();start=monotonic()
            try:
                result=await self.adapter.execute(**kwargs)
                entry.update(status='returned',seconds=round(monotonic()-start,3),usage=result.metadata.get('usage'));return result
            except Exception as error:
                entry.update(status='failed_or_unknown',seconds=round(monotonic()-start,3),error_code=getattr(error,'code',type(error).__name__),http_status=getattr(error,'http_status',None));raise
            finally:save()
    monkeypatch.setattr(ctx['worker'],'get_provider_adapter',lambda typ,settings:TextOnly(typ,settings))
    cases=[
        {'id':'a','module':'amazon_aplus','request':'为上传的定制球衣做一整套Amazon A+，已有完整商品资料，不需要调研','expected':'business.save_aplus_plan'},
        {'id':'b','module':'listing_images','request':'给这件衣服做一整套6张亚马逊Listing附图，不是A+，每张独立策划','expected':'business.save_aplus_plan'},
        {'id':'c','module':'image_edit','request':'10张原图分别换成足球场背景，人物衣服不变','expected':'business.create_images'},
        {'id':'d','module':'listing_images','request':'当前方案的第2和第4张修改，其他保持不变','expected':'business.revise_amazon_modules'},
        {'id':'e','module':'amazon_aplus','request':'参考竞品B0716YP6VJ，先查市场再给我A+方案','expected':'mcp.ss_mcp.asin.detail'},
        {'id':'f','module':'amazon_aplus','request':'跳过竞品研究，沿用上传商品和刚才的品牌风格做A+','expected':'business.save_aplus_plan'},
    ]
    instructions=('这是仅选择能力不执行的路由测验。只输出JSON {"results":[{"id":"a","skill":"...","tool":"...","research_needed":false,"deliverable":"aplus/listing/edit/revise/research"}]}。'
        '模块是用户已知意图，不必重新判断；整套Listing与A+都必须business.save_aplus_plan，不能用通用create_images(count=N)替代独立模块策划。'
        '允许Skill: amazon-aplus-planner, amazon-market-insight, image-creation。允许Tool: business.save_aplus_plan（整套Listing或A+方案）, business.create_images（单张生成或批量独立编辑）, business.revise_amazon_modules（指定现有模块）, mcp.ss_mcp.asin.detail（获准市场查询）。'
        '不伪造执行，不询问费用，完整资料不查市场。')
    listing_only=getattr(builtins,'_routing_listing_only',False)
    for name in ([] if listing_only else ['gpt-5.6-luna','gpt-6.1-sol','gpt-6.1-terra','gpt-5.6-luna','gpt-6.1-sol']):
        await use_model(name);active['purpose']='six_case_tool_selection_only'
        async with ctx['session_factory']() as db:
            conv=await db.get(HermesConversation,ctx['chat']['id'])
            job,_=await submit_job(db,ctx['settings'],organization_id=ctx['first_org'],user_id=conv.user_id,
                payload=JobSubmitRequest(operation_code='listing.plan',workspace_type='listing',queue_name='planning_queue',capability='text_generation',model_code='workflow-text',idempotency_key=str(uuid4()),
                    input={'system_prompt':instructions,'user_prompt':json.dumps({'cases':[{k:v for k,v in c.items() if k!='expected'} for c in cases]},ensure_ascii=False)}))
            jid=job.id;await db.commit()
        await ctx['worker']._execute_job(jid)
        async with ctx['session_factory']() as db:
            job=await db.get(Job,jid)
            entry={'model':name,'job_id':jid,'status':job.status,'correct':0,'total':6};report['routing'].append(entry)
            if job.status=='succeeded':
                try:
                    result=json.loads(job.result_json['metadata']['text']);entry['response']=result
                    choices={r['id']:r for r in result.get('results',[])}
                    entry['correct']=sum(choices.get(c['id'],{}).get('tool')==c['expected'] for c in cases)
                except (ValueError,KeyError,TypeError):entry['parse_error']=True
            save()
    await use_model('gpt-6.1-sol')
    raw=builtins._routing_reference.read_bytes()
    uploaded=(await ctx['client'].post('/api/v1/assets',headers=ctx['headers'],data={'category':'product_reference','private_scope':'agent_chat'},files={'file':('authorized-reference.png',raw,'image/png')})).json()
    attachment=(await ctx['client'].post(f"/api/v1/agent/conversations/{ctx['chat']['id']}/attachments",headers=ctx['headers'],json={'asset_id':uploaded['id']})).json()
    for module,request in [
        ('amazon_aplus','只给方案，先不要生图。为参考图黑橙渐变连帽上衣做3个美国Basic A+模块，围绕可见图案、礼品场景和日常穿着。已有完整图片资料，不查询竞品，不主张材质、性能、授权或未确认的定制服务。'),
        ('listing_images','只给方案，先不要生图。为参考图衣服做一整套6张独立亚马逊Listing附图，每张独立策划，按公司六类方向结合可见商品事实，不编造定制能力、材质、认证或授权；已有资料不查市场。'),
    ]:
        if listing_only and module!='listing_images':continue
        active['purpose']='full_'+module
        start=monotonic();run=await send(ctx,request,[attachment['id']],creative_module=module)
        entry={'module':module,'run_id':run['id'],'api_first_response_seconds':round(monotonic()-start,3)};report['full_plans'].append(entry);save()
        for job in run['jobs']:
            if job['capability']=='text_generation':await ctx['worker']._execute_job(job['id'])
        run=(await ctx['client'].get('/api/v1/agent/runs/'+run['id'],headers=ctx['headers'])).json()
        entry.update(seconds=round(monotonic()-start,3),status=run['status'],error_code=run.get('error_code'),jobs=run['jobs'],events=run['events'])
        history=(await ctx['client'].get('/api/v1/agent/conversations/'+ctx['chat']['id'],headers=ctx['headers'])).json()
        entry['plan_module_counts']=[len(p['plan']['modules']) for p in history.get('amazon_plans',[])];save()
        # A queued further planning Job is reported, not blindly retried.
        assert all(j['capability']=='text_generation' for j in run['jobs'])
    report['route_means']={name:mean(c['seconds'] for c in report['calls'] if c['model']==name and c['purpose']=='six_case_tool_selection_only') for name in ['gpt-5.6-luna','gpt-6.1-sol','gpt-6.1-terra'] if any(c['model']==name and c['purpose']=='six_case_tool_selection_only' for c in report['calls'])}
    save()
