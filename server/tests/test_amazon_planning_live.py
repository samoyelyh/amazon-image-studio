"""Real structured planning; original API/Jobs; image Jobs submitted but not executed."""
import builtins
import json
from time import monotonic
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from app.models.tasks import Job,ProviderModel,Provider,ApiKey,ResourcePool,ResourcePoolKey
from tests.test_agent_control import agent_context
from tests.test_agent_chat_v2 import chat_context,send
from tests.test_agent_second_round import second_context
from tests.test_agent_autonomous import autonomous_context
from tests.test_amazon_advisor import advisor

pytestmark=pytest.mark.skipif(not hasattr(builtins,'_planning_seed'),reason='Explicit real Amazon compact-planning validation')


@pytest.mark.parametrize('repeat,deliverable,count',[(1,'aplus',3),(1,'listing',6),(2,'aplus',3),(2,'listing',6)])
async def test_complete_compact_planning(advisor,monkeypatch,repeat,deliverable,count):
    if deliverable in builtins._planning_unknown:pytest.skip('Prior remote outcome unknown; do not resend this planning case')
    ctx=advisor;root=builtins._planning_output;report=builtins._planning_report
    def save():(root/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    seed=builtins._planning_seed;r=seed['operations']['listing.plan']
    ctx['settings'].api_key_encryption_key=SecretStr(seed['encryption_key'])
    ctx['settings'].agent_control_text_model='workflow-text';ctx['settings'].provider_request_timeout_seconds=480
    ctx['settings'].job_max_attempts=1;ctx['settings'].agent_auto_submissions_per_minute=30
    async with ctx['session_factory']() as db:
        model=await db.scalar(select(ProviderModel).where(ProviderModel.code=='workflow-text'))
        provider=Provider(code='isolated-compact',name='Isolated compact planning',provider_type=r['provider_type'],base_url=r['base_url'],config_json=r['provider_config'])
        db.add(provider);await db.flush();model.provider_id=provider.id;model.upstream_model=r['upstream_model'];model.config_json=r['model_config']
        key=ApiKey(provider_id=provider.id,label='Isolated planning',secret_ciphertext=r['secret_ciphertext'],fingerprint='isolated-compact',secret_suffix='hidden',max_concurrency=1,status='active')
        db.add(key);await db.flush();pool=await db.scalar(select(ResourcePool).where(ResourcePool.model_id==model.id))
        for link in (await db.scalars(select(ResourcePoolKey).where(ResourcePoolKey.resource_pool_id==pool.id))).all():link.enabled=False
        db.add(ResourcePoolKey(resource_pool_id=pool.id,api_key_id=key.id));await db.commit()
    entry={'deliverable':deliverable,'repeat':repeat,'expected_modules':count};report['cases'].append(entry);save()
    from app.providers.registry import get_provider_adapter
    class TextOnly:
        def __init__(self,t,s):self.adapter=get_provider_adapter(t,s)
        async def execute(self,**kwargs):
            if kwargs['capability']!='text_generation' or len(report['calls'])>=4:raise RuntimeError('At most four text calls, no image requests')
            effort=getattr(builtins,'_planning_effort',None)
            if effort:kwargs['payload']={**kwargs['payload'],'reasoning_effort':effort}
            call={'deliverable':deliverable,'repeat':repeat,'model':kwargs['upstream_model'],'reasoning_effort':effort or 'configured_default',
                'user_chars':len(kwargs['payload']['user_prompt']),'system_chars':len(kwargs['payload']['system_prompt'])}
            report['calls'].append(call);save();start=monotonic()
            try:
                result=await self.adapter.execute(**kwargs)
                call.update(status='returned',seconds=round(monotonic()-start,3),usage=result.metadata.get('usage'),transport=result.metadata.get('transport'),
                    output_chars=len(result.metadata['text']),finish_reason=result.metadata.get('finish_reason'))
                (root/f'{deliverable}-{repeat}-reply.json').write_text(result.metadata['text'],encoding='utf-8')
                return result
            except Exception as error:
                call.update(status='unknown_or_failed',seconds=round(monotonic()-start,3),error_code=getattr(error,'code',type(error).__name__),http_status=getattr(error,'http_status',None),transport=getattr(error,'diagnostics',None))
                builtins._planning_unknown.add(deliverable);raise
            finally:save()
    monkeypatch.setattr(ctx['worker'],'get_provider_adapter',lambda t,s:TextOnly(t,s))
    raw=builtins._planning_reference.read_bytes()
    asset=(await ctx['client'].post('/api/v1/assets',headers=ctx['headers'],data={'category':'product_reference','private_scope':'agent_chat'},files={'file':('authorized-black-orange-hoodie.png',raw,'image/png')})).json()
    attached=(await ctx['client'].post(f"/api/v1/agent/conversations/{ctx['chat']['id']}/attachments",headers=ctx['headers'],json={'asset_id':asset['id']})).json()
    request=('只给方案，先不要生图。为参考图的黑橙渐变连帽上衣做'+('3个美国Basic A+模块' if deliverable=='aplus' else '一整套6张独立美国亚马逊Listing附图')+
        '，围绕真实图案、礼品场景和日常穿着，构图各不相同，原生英文文案单独排版。已有完整商品图片，不查询竞品，不主张材质、性能、授权或未确认的定制服务。使用本轮brief简报，完整Prompt由程序编译。')
    start=monotonic();run=await send(ctx,request,[attached['id']],creative_module='amazon_aplus' if deliverable=='aplus' else 'listing_images')
    entry.update(run_id=run['id'],conversation_id=ctx['chat']['id'],first_api_response_seconds=round(monotonic()-start,3),reference_asset_id=asset['id']);save()
    assert len(run['jobs'])==1
    await ctx['worker']._execute_job(run['jobs'][0]['id'])
    run=(await ctx['client'].get('/api/v1/agent/runs/'+run['id'],headers=ctx['headers'])).json()
    entry.update(status=run['status'],error_code=run.get('error_code'),planning_seconds=round(monotonic()-start,3),jobs=run['jobs'],events=run['events']);save()
    if run['status'] in {'failed','remote_unknown'}:builtins._planning_unknown.add(deliverable)
    assert run['status']=='awaiting_review',run['status']
    history=(await ctx['client'].get('/api/v1/agent/conversations/'+ctx['chat']['id'],headers=ctx['headers'])).json()
    plan=history['amazon_plans'][0];entry.update(plan=plan,findings=plan['findings'],compiled=any(e['type']=='amazon_brief_compiled' for e in run['events']));save()
    assert entry['compiled'] and len(plan['plan']['modules'])==count and not plan['findings']
    # Normal user review, original native image submission; never execute these Jobs.
    submitted=await send(ctx,'可以')
    images=[j for j in submitted['jobs'] if j['capability']!='text_generation']
    entry.update(image_job_ids=[j['id'] for j in images],time_to_image_jobs_seconds=round(monotonic()-start,3),submission_status=submitted['status'])
    async with ctx['session_factory']() as db:
        rows=[await db.get(Job,j['id']) for j in images]
        entry['compiled_prompts']=[{'job_id':j.id,'chars':len(j.input_json['prompt']),'prompt':j.input_json['prompt'],'quality':j.input_json['quality']} for j in rows]
    save()
    assert len(images)==count and submitted['status']=='waiting_jobs'
    assert all(p['quality']=='high' for p in entry['compiled_prompts'])
