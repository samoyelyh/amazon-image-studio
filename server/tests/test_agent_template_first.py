"""Template/sample relation planning, existing B generation and no live API calls."""
from uuid import uuid4
import pytest
from sqlalchemy import select,func
from app.agents import production
from app.models.content import Asset
from app.models.hermes_agent import HermesConversation
from app.models.tasks import Job
from tests.test_agent_control import agent_context
from tests.test_agent_chat_v2 import chat_context,send
from tests.test_agent_second_round import second_context,finish
from tests.test_agent_autonomous import autonomous_context
from tests.test_agent_material_import import imported


async def inputs(ctx,templates,garments):
    ts=[await imported(ctx,f'template-{i}.png',f'templates/template-{i}.png','template') for i in range(templates)]
    gs=[await imported(ctx,f'NF{i:07}-front.png',f'garments/NF{i:07}-front.png','garment') for i in range(garments)]
    return ts,gs


async def test_14_known_inputs_plan_only_2_template_sample_relations(autonomous_context):
    ctx=autonomous_context;ts,gs=await inputs(ctx,2,12)
    ids=[a['id'] for a,_ in ts+gs]
    async with ctx['session_factory']() as db:
        conv=await db.get(HermesConversation,ctx['chat']['id'])
        args=production.AnalyzeAssets(asset_ids=ids)
        quote=await production.analyze_quote(db,conv,args,ctx['settings'])
        assert quote['analysis_count']==2 and quote['direct_reference_count']==12
        assert quote['classification_count']==0
        result=await production.analyze(db,ctx['settings'],conv,args,'template-first:'+str(uuid4()))
        assert len(result['job_ids'])==2
        for jid,(t,_) in zip(result['job_ids'],ts):
            job=await db.get(Job,jid)
            assert job.input_json['reference_asset_ids']==[t['id'],gs[0][0]['id']]
            assert '不得把任何样例服装的颜色' in job.input_json['system_prompt']
        await db.commit()
    for jid in result['job_ids']:await ctx['worker']._execute_job(jid)
    async with ctx['session_factory']() as db:
        conv=await db.get(HermesConversation,ctx['chat']['id'])
        plan=await production.collect_understanding(db,conv,result)
        assert len(plan['template_prompts'])==2 and len(plan['garment_rules'])==12
        assert all(not r['visual_facts'] for r in plan['garment_rules'].values())
        garment_assets=[await db.get(Asset,a['id']) for a,_ in gs]
        assert all(not (a.metadata_json or {}).get('agent_understanding') for a in garment_assets)
        cached=await production.analyze_quote(db,conv,args,ctx['settings'])
        assert cached['analysis_count']==0
        await db.commit()
    extra,_=await imported(ctx,'NF9999999-front.png','garments/NF9999999-front.png','garment')
    async with ctx['session_factory']() as db:
        conv=await db.get(HermesConversation,ctx['chat']['id'])
        cached=await production.analyze_quote(db,conv,production.AnalyzeAssets(asset_ids=[*ids,extra['id']]),ctx['settings'])
        assert cached['analysis_count']==0 and cached['direct_reference_count']==13


async def test_samples_then_production_reuse_original_templates_and_template_prompts(autonomous_context):
    ctx=autonomous_context;ts,gs=await inputs(ctx,2,2)
    run=await send(ctx,'批量换衣，把这些服装套到这些模板，每模板先做一张样图',[a['id'] for _,a in ts+gs])
    assert len(run['jobs'])==2 and '按模板规划' in run['plan']['summary'],run
    run=await finish(ctx,run)
    assert len([j for j in run['jobs'] if j['capability']=='image_edit'])==2,run
    ready=await finish(ctx,run)
    assert len(ready['outputs'])==2
    detail=(await ctx['client'].get('/api/v1/agent/conversations/'+ctx['chat']['id'],headers=ctx['headers'])).json()
    plan=detail['production_plans'][0]
    review={'plan_id':plan['id'],'expected_revision':plan['revision'],'expected_review_revision':plan['review_revision'],
        'decisions':[{'sample_number':s['sample_number'],'output_id':s['output_id'],'decision':'approve'} for s in plan['sample_catalog']]}
    approved=await send(ctx,'两张样图都通过',sample_review=review)
    assert approved['status']=='completed',approved
    batch=await send(ctx,'通过的模板处理全部服装',production_plan_id=plan['id'],production_revision=plan['revision'],production_stage='production')
    images=[j for j in batch['jobs'] if j['capability']=='image_edit']
    assert len(images)==4,batch
    async with ctx['session_factory']() as db:
        assert await db.scalar(select(func.count()).select_from(Job).where(Job.capability=='text_generation'))==2
        for info in images:
            job=await db.get(Job,info['id']);meta=job.input_json['metadata'];tid=meta['template_id']
            assert job.input_json['reference_asset_ids'][0] in {t['id'] for t,_ in ts}
            assert job.input_json['reference_asset_ids'][1] in {g['id'] for g,_ in gs}
            assert meta['template_reusable_prompt']==plan['template_prompts'][tid]
            assert meta['template_reusable_prompt'] in meta['effective_prompt_snapshot']
            assert meta['analysis_mode']=='template_first'
    done=await finish(ctx,batch)
    assert len(done['outputs'])==4


async def test_explicit_per_asset_mode_is_still_available(autonomous_context):
    ctx=autonomous_context;ts,gs=await inputs(ctx,1,2)
    async with ctx['session_factory']() as db:
        conv=await db.get(HermesConversation,ctx['chat']['id'])
        quote=await production.analyze_quote(db,conv,production.AnalyzeAssets(asset_ids=[a['id'] for a,_ in ts+gs],analysis_mode='per_asset'),ctx['settings'])
        assert quote['analysis_count']==3 and quote['analysis_mode']=='per_asset'


def test_template_planner_cannot_succeed_without_an_actual_reusable_prompt():
    from app.core.errors import AppError
    with pytest.raises(AppError) as caught:
        production._parse_understanding('{"role":"template","confidence":1}','template','template_first')
    assert caught.value.code=='agent.invalid_asset_analysis'
