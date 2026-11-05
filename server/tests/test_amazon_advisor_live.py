"""Opt-in real Provider, isolated business DB/storage, max 3 text+4 image requests."""
import asyncio
import builtins
import json
from pathlib import Path
import time
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from app.models.tasks import Job, Provider, ProviderModel, ApiKey, ResourcePool, ResourcePoolKey
from tests.test_agent_control import agent_context
from tests.test_agent_chat_v2 import chat_context, send
from tests.test_agent_second_round import second_context
from tests.test_agent_autonomous import autonomous_context
from tests.test_amazon_advisor import advisor

pytestmark=pytest.mark.skipif(not hasattr(builtins,'_advisor_live_seed'),reason='Explicit bounded --real acceptance only')


async def test_real_advisor_suite(advisor,monkeypatch):
    ctx=advisor;seed=builtins._advisor_live_seed;root=builtins._advisor_live_output
    root.mkdir(parents=True,exist_ok=False)
    report={'scope':'isolated DB + original Job/Worker + real Provider; no production mutation','calls':[], 'stages':[]}
    def save():
        (root/'evidence.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    save()
    ctx['settings'].api_key_encryption_key=SecretStr(seed['encryption_key'])
    ctx['settings'].agent_control_text_model='workflow-text'
    ctx['settings'].provider_request_timeout_seconds=600
    ctx['settings'].job_max_attempts=1
    async with ctx['session_factory']() as db:
        for operation,code in [('listing.plan','workflow-text'),('listing.generate','workflow-image')]:
            resource=seed['operations'][operation]
            model=await db.scalar(select(ProviderModel).where(ProviderModel.code==code))
            provider=Provider(code='live-'+code,name='Authorized isolated Provider',provider_type=resource['provider_type'],
                base_url=resource['base_url'],config_json=resource['provider_config'])
            db.add(provider);await db.flush()
            model.provider_id=provider.id;model.upstream_model=resource['upstream_model'];model.config_json=resource['model_config']
            key=ApiKey(provider_id=provider.id,label='Isolated acceptance key',secret_ciphertext=resource['secret_ciphertext'],
                fingerprint='isolated-live-'+code,secret_suffix='hidden',max_concurrency=resource['max_concurrency'],enabled=True,status='active')
            db.add(key);await db.flush()
            pool=await db.scalar(select(ResourcePool).where(ResourcePool.model_id==model.id))
            for link in (await db.scalars(select(ResourcePoolKey).where(ResourcePoolKey.resource_pool_id==pool.id))).all():link.enabled=False
            db.add(ResourcePoolKey(resource_pool_id=pool.id,api_key_id=key.id))
        await db.commit()
    from app.providers.registry import get_provider_adapter
    class BoundedProvider:
        def __init__(self,typ,settings):self.actual=get_provider_adapter(typ,settings)
        async def execute(self,**kwargs):
            kind='text' if kwargs['capability']=='text_generation' else 'image'
            used=sum(c['kind']==kind for c in report['calls'])
            if used>=(3 if kind=='text' else 4):raise RuntimeError('Bounded acceptance request ceiling reached')
            receipt={'kind':kind,'model':kwargs['upstream_model'],'started':time.time(),'status':'requested'}
            report['calls'].append(receipt);save()
            try:
                value=await self.actual.execute(**kwargs)
                receipt.update(status='returned',seconds=round(time.time()-receipt['started'],2),outputs=len(value.outputs))
                return value
            except Exception as error:
                receipt.update(status='unknown_or_failed',error_code=getattr(error,'code',type(error).__name__),http_status=getattr(error,'http_status',None))
                raise
            finally:save()
    monkeypatch.setattr(ctx['worker'],'get_provider_adapter',lambda typ,settings:BoundedProvider(typ,settings))
    raw=builtins._advisor_live_reference.read_bytes()
    uploaded=(await ctx['client'].post('/api/v1/assets',headers=ctx['headers'],data={'category':'product_reference','private_scope':'agent_chat'},
        files={'file':('authorized-custom-hoodie.png',raw,'image/png')})).json()
    attached=(await ctx['client'].post(f"/api/v1/agent/conversations/{ctx['chat']['id']}/attachments",headers=ctx['headers'],json={'asset_id':uploaded['id']})).json()
    report.update(conversation_id=ctx['chat']['id'],reference_asset_id=uploaded['id']);save()
    async def settle(run):
        for _ in range(4):
            pending=[j for j in run['jobs'] if j['status'] not in {'succeeded','failed','cancelled'}]
            if not pending:return run
            # SQLite test writes share one connection: short claim/store phases
            # are serialized by this harness; real HTTP overlap is Mock-tested separately.
            for job in pending:await ctx['worker']._execute_job(job['id'])
            run=(await ctx['client'].get('/api/v1/agent/runs/'+run['id'],headers=ctx['headers'])).json()
            report['stages'].append({'run_id':run['id'],'status':run['status'],'error_code':run.get('error_code'),
                'jobs':run['jobs'],'outputs':run['outputs'],'plan':run.get('plan')});save()
            for output in run.get('outputs',[]):
                response=await ctx['client'].get(output['download_url'],headers=ctx['headers'])
                assert response.status_code==200
                (root/(output['id']+'.png')).write_bytes(response.content)
            if run['status'] in {'failed','remote_unknown','blocked','awaiting_clarification'}:
                pytest.fail('Real request stopped safely: '+str(run.get('error_code') or run['status']))
        return run
    content=('给参考中的黑橙渐变连帽上衣设计一套美国亚马逊Listing附图。本次小样只要2张：礼品场景、日常穿着，各一张独立图片。'
        '仅确认参考中可见款式颜色、Baltimore图案与原印字；不主张材质性能、球队授权、配送或定制服务。以用户商品原图为事实证据。'
        '保留图案和原文字，整套暖调自然摄影。图中文字仅为商品图案，不继承顶部GAME DAY广告。可以自由设计不同构图，原生营销文案单独输出。'
        '已有研究见上一轮父体20条历史评论：有送妻子作礼物及尺码/定制结果问题；不是我方性能事实。本次无需新市场查询。'
        '输出deliverable=listing完整方案，先让我看方案。')
    run=await settle(await send(ctx,content,[attached['id']],creative_module='listing_images'))
    assert run['status']=='awaiting_review',run['status']
    result=await settle(await send(ctx,'可以'))
    assert result['status']=='completed' and len(result['outputs'])==2
    pid=result['outputs'][0]['amazon_module']['plan_id']
    packed=await ctx['client'].get(f"/api/v1/agent/conversations/{ctx['chat']['id']}/amazon-plans/{pid}/archive",headers=ctx['headers'])
    assert packed.status_code==200
    (root/'listing.zip').write_bytes(packed.content)
    aplus=await settle(await send(ctx,'再帮我做一套Amazon Basic A+，本次只要1个产品主视觉模块，保持上述商品和品牌风格一致。直接生成不用确认，不进行新市场调研。',creative_module='amazon_aplus'))
    assert aplus['status']=='completed' and len(aplus['outputs'])==1
    # Switch back to Listing; explicitly select its plan, not the last global image number.
    edited=await settle(await send(ctx,'修改刚才Listing方案的第2张：换成圣诞礼品场景，其他保持不变。直接生成。',creative_module='listing_images'))
    assert edited['status']=='completed' and len(edited['outputs'])==1
    assert edited['outputs'][0]['amazon_module']['plan_id']==pid
    assert edited['outputs'][0]['version']==2
    report['complete']=True;save()
