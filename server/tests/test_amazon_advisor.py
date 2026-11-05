"""Whole-suite chat flow over isolated DB, original Worker and Mock Provider."""
import io
import json
from datetime import datetime, timezone
from zipfile import ZipFile

import pytest
from sqlalchemy import select, func
from app.agents import amazon
from app.models.tasks import Job, JobBatch, ProviderModel, ResourcePool, OperationResourcePool
from app.models.quota import QuotaRule
from tests.test_agent_control import agent_context
from tests.test_agent_chat_v2 import chat_context, send
from tests.test_agent_second_round import second_context, attach, finish
from tests.test_agent_autonomous import autonomous_context
from tests.test_agent_amazon import sample_plan


@pytest.fixture
async def advisor(autonomous_context):
    ctx=autonomous_context
    ctx['settings'].agent_control_planner='existing_text'
    async with ctx['session_factory']() as db:
        model=await db.scalar(select(ProviderModel).where(ProviderModel.code=='workflow-image'))
        pool=await db.scalar(select(ResourcePool).where(ResourcePool.model_id==model.id))
        for cap in ('image_edit','multi_image_reference'):
            db.add(OperationResourcePool(operation_code='aplus.generate',resource_pool_id=pool.id,required_capability=cap))
        db.add(QuotaRule(organization_id=None,operation_code='aplus.generate',name='Mock advisor',base_cost=1,
            model_multipliers={},quality_multipliers={},resolution_multipliers={},effective_from=datetime(2020,1,1,tzinfo=timezone.utc)))
        await db.commit()
    asset,attachment=await attach(ctx,'custom-jersey-reference.png')
    ctx['product']=asset;ctx['product_attachment']=attachment
    return ctx


def suite(ctx, deliverable='listing'):
    p=sample_plan(ctx['product']['id'])
    p.deliverable=deliverable
    p.insight.evidence[0].statement='用户确认：酒红色球衣，可定制姓名号码；未提供材质、性能与授权事实。'
    p.modules=[p.modules[0].model_copy(update={'id':f'm{i}','title':title,'design_direction':direction,
        'spec_id':'listing_square' if deliverable=='listing' else 'basic_image_text_overlay',
        'requested_width':768 if deliverable=='listing' else None,'requested_height':768 if deliverable=='listing' else None,
        'composition':f'{title}独立构图，商品为主，不编造商品功能。'})
        for i,(title,direction) in enumerate([('真实外观','white'),('定制流程','custom'),('日常穿着','casual'),('礼品场景','gift')],1)]
    return p


def model_step(tool, args):
    return {'summary':'整套独立图片方案，未进行市场调研。','skills':['amazon-aplus-planner'],
        'steps':[{'capability_id':tool,'arguments':args,'reason':'已有商品资料和专业规则足够'}]}


async def planned(ctx,p,content='先看方案，给这款球衣设计一整套亚马逊附图，突出定制、礼品和日常穿着'):
    ctx['mock_decision']=model_step('business.save_aplus_plan',{'plan':p.model_dump(mode='json')})
    run=await send(ctx,content,[ctx['product_attachment']['id']],creative_module='listing_images' if p.deliverable=='listing' else 'amazon_aplus')
    return await finish(ctx,run)


async def test_suite_one_confirmation_concurrent_jobs_selective_edit_and_zip(advisor):
    ctx=advisor;p=suite(ctx)
    plan=await planned(ctx,p)
    assert plan['status']=='awaiting_review',plan
    assert len(plan['jobs'])==1 and plan['jobs'][0]['capability']=='text_generation'
    assert plan['plan']['image_count']==4
    # No second planning inference and no per-module confirmation.
    running=await send(ctx,'可以')
    assert running['id']==plan['id'] and running['status']=='waiting_jobs',running
    images=[j for j in running['jobs'] if j['capability']!='text_generation']
    assert len(images)==4
    async with ctx['session_factory']() as db:
        rows=[await db.get(Job,j['id']) for j in images]
        assert len({j.batch_id for j in rows})==1
        batch=await db.get(JobBatch,rows[0].batch_id)
        assert batch.concurrency==4
        assert {j.input_json['metadata']['amazon_module']['module_id'] for j in rows}=={'m1','m2','m3','m4'}
        assert len({j.input_json['prompt'] for j in rows})==4
        assert all(j.operation_code=='listing.generate' for j in rows)
    done=await finish(ctx,running)
    assert done['status']=='completed' and len(done['outputs'])==4,done
    bymodule={o['amazon_module']['module_id']:o for o in done['outputs']}
    pid=bymodule['m1']['amazon_module']['plan_id']
    changed=[p.modules[i].model_copy(update={'composition':'少量文案' if i==1 else '圣诞礼品场景',
        'image_prompt':'Simplified copy space' if i==1 else 'Christmas gift scene, preserve the jersey'}) for i in (1,3)]
    ctx['mock_decision']=model_step('business.revise_amazon_modules',{'plan_id':pid,'expected_revision':1,
        'modules':[m.model_dump(mode='json') for m in changed]})
    editing=await finish(ctx,await send(ctx,'第2张文案太多，第4张换成圣诞礼品场景，其他不变'))
    assert editing['status']=='waiting_jobs',editing
    assert len([j for j in editing['jobs'] if j['capability']!='text_generation'])==2
    revised=await finish(ctx,editing)
    assert {o['amazon_module']['module_id'] for o in revised['outputs']}=={'m2','m4'}
    assert all(o['version']==2 and o['parent_output_id']==bymodule[o['amazon_module']['module_id']]['id'] for o in revised['outputs'])
    history=(await ctx['client'].get(f"/api/v1/agent/conversations/{ctx['chat']['id']}",headers=ctx['headers'])).json()
    record=next(x for x in history['amazon_plans'] if x['id']==pid)
    assert record['plan']['modules'][0]==p.modules[0].model_dump(mode='json')
    assert record['plan']['modules'][2]==p.modules[2].model_dump(mode='json')
    packed=await ctx['client'].get(f"/api/v1/agent/conversations/{ctx['chat']['id']}/amazon-plans/{pid}/archive",headers=ctx['headers'])
    assert packed.status_code==200,packed.text
    with ZipFile(io.BytesIO(packed.content)) as z:
        assert z.testzip() is None
        manifest=json.loads(z.read('manifest.json'))
        assert not manifest['modules_without_output'] and len(manifest['outputs'])==6
        assert len(set(z.namelist()))==9
    # New request ID does not bypass module-signature deduplication.
    ctx['redis'].values.clear()  # Separate simulated minute, not a production rate-policy change.
    repeated=await send(ctx,'直接生成',amazon_plan_id=pid,amazon_revision=2,amazon_module_ids=['m2','m4'])
    assert repeated['jobs']==[] and repeated['outputs']==[]
    reused=next(a['result'] for a in repeated['result']['actions'] if a['tool']=='generate_aplus')
    assert reused['reused'] and set(reused['job_ids'])=={j['id'] for j in editing['jobs'] if j['capability']!='text_generation'}
    async with ctx['session_factory']() as db:
        assert await db.scalar(select(func.count()).select_from(Job).where(Job.capability!='text_generation'))==6


async def test_direct_aplus_suite_bypasses_only_plan_review(advisor):
    ctx=advisor;p=suite(ctx,'aplus')
    running=await planned(ctx,p,'再帮我做一套Amazon A+，直接生成不用确认，保持商品和品牌风格一致')
    assert running['status']=='waiting_jobs',running
    assert len([j for j in running['jobs'] if j['capability']!='text_generation'])==4
    done=await finish(ctx,running)
    assert len(done['outputs'])==4
    assert all((o['width'],o['height'])==(970,300) for o in done['outputs'])


def test_six_directions_and_reference_contract():
    rules=amazon.visual_rules()
    assert set(rules['directions'])=={'white','custom','watch','gift','detail','casual'}
    assert '0/00' in rules['customization']
    assert not amazon.direct_generation_requested('先给我看方案，不用确认费用')
    assert not amazon.direct_generation_requested('不要直接生成，先给方案')
    assert not amazon.direct_generation_requested('帮我设计一套图，无需确认费用')
    assert amazon.direct_generation_requested('直接生成不用确认')


def test_legacy_signature_and_specific_module_mapping():
    from app.agents.capabilities.registry import digest
    from app.core.errors import AppError
    p=sample_plan('00000000-0000-0000-0000-000000000001');m=p.modules[0]
    module=m.model_dump(mode='json')
    for key in ('design_direction','requested_width','requested_height','design_principles','art_direction','image_slots'):module.pop(key)
    legacy=digest({'module':module,'identity':p.product_identity_lock,'style':p.campaign_style_lock,
        'rules':p.rules_version,'marketplace':p.marketplace,
        'evidence':[e.model_dump(mode='json') for e in p.insight.evidence if e.id in m.evidence_ids]})
    assert amazon.module_signature(p,m)==legacy
    assert amazon.requested_revision_ids('第2张和第三个模块修改',p)=={'m2','m3'}
    with pytest.raises(AppError):amazon.requested_revision_ids('第9张换背景',p)


async def test_running_and_unknown_module_cannot_be_resubmitted_after_prompt_change(advisor):
    from app.agents.amazon_contracts import ModuleRevisions, GenerateAPlus
    from app.models.hermes_agent import HermesConversation
    from app.core.errors import AppError
    ctx=advisor;p=suite(ctx)
    pending=await planned(ctx,p)
    running=await send(ctx,'可以')
    pid=running['plan']['actions'][0]['arguments']['plan_id']
    jid=next(j['id'] for j in running['jobs'] if j['capability']!='text_generation')
    async with ctx['session_factory']() as db:
        conv=await db.get(HermesConversation,ctx['chat']['id'])
        job=await db.get(Job,jid)
        mid=job.input_json['metadata']['amazon_module']['module_id']
        change=next(m for m in p.modules if m.id==mid).model_copy(update={'composition':'新构图'})
        await amazon.revise_many(db,conv,ModuleRevisions(plan_id=pid,expected_revision=1,modules=[change]))
        args=GenerateAPlus(plan_id=pid,expected_revision=2,module_ids=[mid])
        await amazon.authorize_review(db,conv,args,source='isolated_test_review')
        with pytest.raises(AppError,match='仍在生成'):await amazon.generate(db,ctx['settings'],conv,args,'do-not-duplicate-running')
        job.status='failed';job.error_code='provider.timeout';await db.flush()
        with pytest.raises(AppError,match='结果未知'):await amazon.generate(db,ctx['settings'],conv,args,'do-not-duplicate-unknown')
