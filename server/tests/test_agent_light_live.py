import builtins,json
from time import monotonic
from uuid import uuid4
import pytest
from pydantic import SecretStr,Field
from sqlalchemy import select
from app.agents.contracts import StrictModel
from app.agents.light_router import LightDecision,system_prompt
from app.models.tasks import Job,ProviderModel,Provider,ApiKey,ResourcePool,ResourcePoolKey
from app.models.hermes_agent import HermesConversation
from app.schemas.tasks import JobSubmitRequest
from app.services.task_service import submit_job
from tests.test_agent_control import agent_context
from tests.test_agent_chat_v2 import chat_context
from tests.test_agent_second_round import second_context
from tests.test_agent_autonomous import autonomous_context
from tests.test_amazon_advisor import advisor
from tests.test_agent_light_router import routed

pytestmark=pytest.mark.skipif(not hasattr(builtins,'_decision_seed'),reason='Explicit bounded real decision probe')
class Row(StrictModel):
    id:str
    decision:LightDecision
class Probe(StrictModel):
    decisions:list[Row]=Field(min_length=6,max_length=6)


async def test_terra_and_sol_light_decisions(routed,monkeypatch):
    ctx=routed;root=builtins._decision_output;seed=builtins._decision_seed;r=seed['operations']['listing.plan']
    report={'calls':[],'cases':[],'image_calls':0,'mcp_calls':0,'production_writes':0}
    def save():(root/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    ctx['settings'].api_key_encryption_key=SecretStr(seed['encryption_key']);ctx['settings'].job_max_attempts=1
    async with ctx['session_factory']() as db:
        provider=Provider(code='isolated-light-live',name='Isolated routing',provider_type=r['provider_type'],base_url=r['base_url'],config_json=r['provider_config'])
        db.add(provider);await db.flush()
        key=ApiKey(provider_id=provider.id,label='Isolated routing',secret_ciphertext=r['secret_ciphertext'],fingerprint='isolated-light',secret_suffix='hidden',max_concurrency=1,status='active')
        db.add(key);await db.flush()
        for code,upstream in [('workflow-text',r['upstream_model']),('workflow-decision','gpt-6.1-terra')]:
            m=await db.scalar(select(ProviderModel).where(ProviderModel.code==code));m.provider_id=provider.id;m.upstream_model=upstream;m.config_json=r['model_config']
            pool=await db.scalar(select(ResourcePool).where(ResourcePool.model_id==m.id))
            for link in (await db.scalars(select(ResourcePoolKey).where(ResourcePoolKey.resource_pool_id==pool.id))).all():link.enabled=False
            db.add(ResourcePoolKey(resource_pool_id=pool.id,api_key_id=key.id))
        await db.commit()
    from app.providers.registry import get_provider_adapter
    class TextOnly:
        def __init__(self,t,s):self.adapter=get_provider_adapter(t,s)
        async def execute(self,**kwargs):
            if kwargs['capability']!='text_generation' or len(report['calls'])>=4:raise RuntimeError('Text-only four-request ceiling')
            call={'model':kwargs['upstream_model'],'context_chars':len(kwargs['payload']['user_prompt'])};report['calls'].append(call);save();start=monotonic()
            try:
                value=await self.adapter.execute(**kwargs);call.update(status='returned',seconds=round(monotonic()-start,3),transport=value.metadata.get('transport'),usage=value.metadata.get('usage'));return value
            except Exception as e:
                call.update(status='unknown_or_failed',seconds=round(monotonic()-start,3),code=getattr(e,'code',type(e).__name__));raise
            finally:save()
    monkeypatch.setattr(ctx['worker'],'get_provider_adapter',lambda t,s:TextOnly(t,s))
    directory=[{'id':x,'description':d} for x,d in [
        ('business.save_aplus_plan','完整Listing/A+独立模块策划'),('business.revise_amazon_modules','修改指定现有模块'),
        ('business.create_images','单张生图或批量独立编辑'),('business.current_jobs','当前会话进度，不重复生成'),
        ('mcp.ss_mcp.asin.detail','获准卖家精灵商品详情'),('mcp.ss_mcp.keyword.asin.list','获准关键词'),('mcp.ss_mcp.asin.review.list','获准评论')]]
    cases=[('a','给商品生成一整套Amazon A+，资料齐全，不用研究','business.save_aplus_plan'),
        ('b','生成一整套6张Listing附图，每张独立构图','business.save_aplus_plan'),
        ('c','第2和第4张改一下，其他保持不变','business.revise_amazon_modules'),
        ('d','继续看原任务进度，不要重新生成','business.current_jobs'),
        ('e','查B0716YP6VJ的竞品关键词评论，再给建议','mcp'),
        ('f','将10张原图分别换成足球场背景，衣服人物不变','business.create_images')]
    prompt=system_prompt().replace(json.dumps(LightDecision.model_json_schema(),ensure_ascii=False,separators=(',',':')),json.dumps(Probe.model_json_schema(),ensure_ascii=False,separators=(',',':')))
    prompt+='本次是六条独立测试，逐条放在decisions数组中，id严格对应输入。只选能力，不实际调用MCP或生成图片。'
    payload={'tools':directory,'skills':[{'id':x} for x in ['amazon-aplus-planner','amazon-market-insight','image-creation','queue-inspection']],
        'plans':[{'id':'plan-existing','modules':[{'id':f'm{i}','title':f'图片{i}'} for i in range(1,7)]}],
        'cases':[{'id':i,'request':q} for i,q,_ in cases]}
    for repeat,code in [(1,'workflow-decision'),(1,'workflow-text'),(2,'workflow-decision'),(2,'workflow-text')]:
        async with ctx['session_factory']() as db:
            conv=await db.get(HermesConversation,ctx['chat']['id'])
            job,_=await submit_job(db,ctx['settings'],organization_id=ctx['first_org'],user_id=conv.user_id,payload=JobSubmitRequest(operation_code='listing.plan',workspace_type='listing',queue_name='planning_queue',capability='text_generation',model_code=code,idempotency_key=str(uuid4()),
                input={'system_prompt':prompt,'user_prompt':json.dumps(payload,ensure_ascii=False),'stream':True,'reasoning_effort':'low'}))
            jid=job.id;await db.commit()
        await ctx['worker']._execute_job(jid)
        async with ctx['session_factory']() as db:
            job=await db.get(Job,jid)
            entry={'repeat':repeat,'model_code':code,'job_id':jid,'status':job.status,'correct':0};report['cases'].append(entry)
            if job.status!='succeeded':save();pytest.fail('Upstream outcome unknown/failed; no automatic retry')
            reply=Probe.model_validate_json(job.result_json['metadata']['text']);entry['reply']=reply.model_dump()
            choices={row.id:row.decision for row in reply.decisions}
            entry['correct']=sum((expected in choices[i].tools if expected!='mcp' else choices[i].needs_mcp and any(t.startswith('mcp.ss_mcp.') for t in choices[i].tools)) for i,_,expected in cases)
            entry['module_target_correct']=set(choices['c'].module_ids)=={'m2','m4'}
            save()
