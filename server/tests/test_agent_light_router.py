import json
import pytest
from sqlalchemy import select
from app.models.tasks import Job,ProviderModel,ModelCapability,ResourcePool,ResourcePoolKey,OperationResourcePool
from tests.test_agent_control import agent_context
from tests.test_agent_chat_v2 import chat_context,send
from tests.test_agent_second_round import second_context,finish
from tests.test_agent_autonomous import autonomous_context
from tests.test_amazon_advisor import advisor,suite,model_step


@pytest.fixture
async def routed(advisor):
    ctx=advisor;ctx['settings'].agent_control_decision_enabled=True;ctx['settings'].agent_control_decision_model='workflow-decision'
    async with ctx['session_factory']() as db:
        model=await db.scalar(select(ProviderModel).where(ProviderModel.code=='workflow-text'))
        old=await db.scalar(select(ResourcePool).where(ResourcePool.model_id==model.id))
        key=await db.scalar(select(ResourcePoolKey).where(ResourcePoolKey.resource_pool_id==old.id))
        decision=ProviderModel(provider_id=model.provider_id,code='workflow-decision',upstream_model='mock-decision',name='Isolated decision',config_json={})
        db.add(decision);await db.flush();db.add(ModelCapability(model_id=decision.id,capability='text_generation'))
        pool=ResourcePool(model_id=decision.id,code='mock-decision',name='Decision');db.add(pool);await db.flush()
        db.add(ResourcePoolKey(resource_pool_id=pool.id,api_key_id=key.api_key_id))
        db.add(OperationResourcePool(resource_pool_id=pool.id,operation_code='listing.plan',required_capability='text_generation'))
        await db.commit()
    return ctx


def route():return {'summary':'整套Listing交给专业策划','operation':'new_suite','skills':['amazon-aplus-planner'],'tools':['business.save_aplus_plan'],'needs_mcp':False}


async def test_decision_then_professional_preserves_roles_and_auto_submits(routed):
    ctx=routed;ctx['mock_decision']=route()
    first=await send(ctx,'给这款衣服生成整套Listing附图',[ctx['product_attachment']['id']])
    async with ctx['session_factory']() as db:
        j=await db.get(Job,first['jobs'][0]['id']);assert j.model_code=='workflow-decision' and not j.input_json['reference_asset_ids']
        assert j.input_json['metadata']['role']=='decision'
        payload=json.loads(j.input_json['user_prompt'])['context']
        assert 'skill_guidance' not in payload and 'capability_catalog' not in payload
    professional=await finish(ctx,first)
    assert len(professional['jobs'])==2 and professional['result']['light_routing']['status']=='selected'
    async with ctx['session_factory']() as db:
        j=await db.get(Job,next(j['id'] for j in professional['jobs'] if j['id']!=first['jobs'][0]['id']))
        assert j.model_code=='workflow-text' and j.input_json['reference_asset_ids']
    ctx['mock_decision']=model_step('business.save_aplus_plan',{'plan':suite(ctx).model_dump(mode='json')})
    images=await finish(ctx,professional)
    assert len([j for j in images['jobs'] if j['capability']!='text_generation'])==4
    assert len([j for j in images['jobs'] if j['capability']=='text_generation'])==2


async def test_invalid_route_falls_back_without_executing_unapproved_tool(routed):
    ctx=routed;ctx['mock_decision']={**route(),'tools':['mcp.unapproved.delete_all']}
    first=await send(ctx,'给这款衣服生成整套Listing附图',[ctx['product_attachment']['id']])
    second=await finish(ctx,first)
    assert second['result']['light_routing']['status']=='fallback'
    async with ctx['session_factory']() as db:
        model=await db.get(Job,next(j['id'] for j in second['jobs'] if j['id']!=first['jobs'][0]['id']));assert model.model_code=='workflow-text'
    assert not any(e['type']=='capability_call_started' for e in second['events'])


async def test_unknown_decision_does_not_resend_and_new_runs_use_sol(routed):
    ctx=routed
    first=await send(ctx,'给这款衣服生成整套Listing附图',[ctx['product_attachment']['id']])
    async with ctx['session_factory']() as db:
        j=await db.get(Job,first['jobs'][0]['id']);j.status='failed';j.error_code='provider.timeout';await db.commit()
    unknown=(await ctx['client'].get('/api/v1/agent/runs/'+first['id'],headers=ctx['headers'])).json()
    assert unknown['status']=='remote_unknown' and len(unknown['jobs'])==1
    later=await send(ctx,'另外做一套美国A+，使用现有素材',[ctx['product_attachment']['id']])
    async with ctx['session_factory']() as db:
        j=await db.get(Job,later['jobs'][0]['id']);assert j.model_code=='workflow-text'


async def test_known_homepage_module_does_not_repeat_intent_classification(routed):
    ctx=routed
    first=await send(ctx,'生成一套A+',[ctx['product_attachment']['id']],creative_module='amazon_aplus')
    async with ctx['session_factory']() as db:
        j=await db.get(Job,first['jobs'][0]['id']);assert j.model_code=='workflow-text'
