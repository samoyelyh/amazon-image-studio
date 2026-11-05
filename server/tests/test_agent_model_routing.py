"""Agent-only model pin, confirmation and native Job tests. No external requests."""
import pytest
from sqlalchemy import select,func
from app.models.tasks import ProviderModel,ModelCapability,ResourcePool,ResourcePoolKey,OperationResourcePool,Job
from app.services.resource_pool_service import resolve_operation_model_code
from app.core.errors import AppError
from tests.test_agent_control import agent_context,ticket
from tests.test_agent_chat_v2 import chat_context,send,confirm
from tests.test_agent_second_round import second_context,attach,finish


async def seed_sol(ctx):
    async with ctx['session_factory']() as db:
        old=await db.scalar(select(ProviderModel).where(ProviderModel.code=='workflow-text'))
        pool=await db.scalar(select(ResourcePool).where(ResourcePool.model_id==old.id))
        key=await db.scalar(select(ResourcePoolKey).where(ResourcePoolKey.resource_pool_id==pool.id))
        model=ProviderModel(provider_id=old.provider_id,code='gpt-6.1-sol',upstream_model='gpt-6.1-sol',name='Isolated Sol')
        db.add(model);await db.flush()
        for cap in ('text_generation','vision_input'):db.add(ModelCapability(model_id=model.id,capability=cap))
        target=ResourcePool(model_id=model.id,code='isolated-sol',name='Isolated Sol',priority=10000)
        db.add(target);await db.flush()
        db.add(ResourcePoolKey(resource_pool_id=target.id,api_key_id=key.api_key_id))
        db.add(OperationResourcePool(resource_pool_id=target.id,operation_code='listing.plan',required_capability='text_generation',priority=10000))
        await db.commit()


async def test_pin_selects_keyed_model_without_changing_other_workspace_defaults(second_context):
    ctx=second_context;await seed_sol(ctx)
    async with ctx['session_factory']() as db:
        args={'organization_id':ctx['first_org'],'operation_code':'listing.plan','capability':'text_generation'}
        assert await resolve_operation_model_code(db,**args)=='workflow-text'
        assert await resolve_operation_model_code(db,**args,preferred_model_code='gpt-6.1-sol',additional_capabilities={'vision_input'})=='gpt-6.1-sol'
        with pytest.raises(AppError):await resolve_operation_model_code(db,**args,preferred_model_code='missing-model')
        model=await db.scalar(select(ProviderModel).where(ProviderModel.code=='gpt-6.1-sol'))
        model.enabled=False;await db.flush()
        with pytest.raises(AppError):await resolve_operation_model_code(db,**args,preferred_model_code='gpt-6.1-sol')


async def test_real_mode_quotes_pinned_model_but_images_still_require_second_confirmation(second_context):
    ctx=second_context;await seed_sol(ctx)
    ctx['settings'].agent_control_planner='existing_text';ctx['settings'].agent_control_text_model='gpt-6.1-sol'
    image,a=await attach(ctx,'sol-reference.png')
    ctx['mock_decision']={'summary':'使用真实业务生图工具','skills':['image-creation'],
        'steps':[{'capability_id':'business.create_images','arguments':{'instruction':'生成穿这件球衣的模特展示图'},'reason':'根据单图需求选工具'}]}
    first=await send(ctx,'生成穿这件球衣的模特展示图',[a['id']])
    assert first['status']=='awaiting_confirmation' and first['jobs']==[]
    assert first['plan']['budget']['model_code']=='gpt-6.1-sol'
    assert first['plan']['actions'][0]['arguments']['model_code']=='gpt-6.1-sol'
    committed=await confirm(ctx,first)
    async with ctx['session_factory']() as db:
        job=await db.get(Job,committed['jobs'][0]['id'])
        assert job.model_code=='gpt-6.1-sol' and job.input_json['reference_asset_ids']==[image['id']]
        assert await db.scalar(select(func.count()).select_from(Job).where(Job.capability!='text_generation'))==0
    next_plan=await finish(ctx,committed)
    assert next_plan['status']=='awaiting_confirmation' and next_plan['plan']['image_count']==1
    assert next_plan['verification']['model_inference']=='mock'  # Forced test Provider, not claimed live inference.
    async with ctx['session_factory']() as db:
        assert await db.scalar(select(func.count()).select_from(Job).where(Job.capability!='text_generation'))==0
    status=(await ctx['client'].get('/api/v1/agent/status',headers=ctx['headers'])).json()
    assert status['models']['text']['model_code']=='gpt-6.1-sol'


async def test_old_model_quote_and_old_mock_plan_cannot_be_executed_after_switch(second_context):
    ctx=second_context;await seed_sol(ctx)
    ctx['settings'].agent_control_planner='existing_text'
    first=await send(ctx,'生成一张图片')
    ctx['settings'].agent_control_text_model='gpt-6.1-sol'
    blocked=await ctx['client'].post('/api/v1/agent/runs/'+first['id']+'/confirm',headers=ctx['headers'],json=ticket(first))
    assert blocked.status_code==409 and 'agent.text_model_changed' in blocked.text
    ctx['settings'].agent_control_planner='mock'
    old=await send(ctx,'生成一张图片')
    ctx['settings'].agent_control_planner='existing_text'
    blocked=await ctx['client'].post('/api/v1/agent/runs/'+old['id']+'/confirm',headers=ctx['headers'],json=ticket(old))
    assert blocked.status_code==409 and 'agent.planner_changed' in blocked.text
    async with ctx['session_factory']() as db:
        assert await db.scalar(select(func.count()).select_from(Job))==0
