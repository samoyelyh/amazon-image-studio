"""Scoped planner contexts, native isolated Jobs, no upstream calls."""
import json
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator
from app.agents.capabilities import planning_context as pc
from app.agents.capabilities.registry import CapabilityRegistry, ToolSelector
from app.agents.capabilities.contracts import ExecutionContext
from app.agents.creative_modules import describe
from app.core.config import Settings
from app.core.errors import AppError
from app.agents.planner import parse_intent_result
from app.agents.amazon_contracts import SavePlan
from tests.test_agent_control import agent_context
from tests.test_agent_chat_v2 import chat_context, send
from tests.test_agent_second_round import second_context, finish
from tests.test_agent_autonomous import autonomous_context
from tests.test_amazon_advisor import advisor, suite, model_step


def registry():
    return CapabilityRegistry(Settings(_env_file=None),ExecutionContext('org','user','conv','run',
        frozenset({'jobs.read','jobs.submit','projects.read','projects.write','assets.read','batch_tryon.review'})))


def test_schema_projection_keeps_named_title_property_and_all_validation():
    schema=SavePlan.model_json_schema();compact=pc.schema_for_model(schema)
    assert 'title' in compact['$defs']['APlusModule']['properties']
    assert len(json.dumps(compact))<len(json.dumps(schema))
    # Replacing descriptive titles never changes validation results.
    for value in ({},{'plan':{}},{'plan':{'modules':[]}}):
        assert sorted(e.message for e in Draft202012Validator(schema).iter_errors(value))==sorted(e.message for e in Draft202012Validator(compact).iter_errors(value))


@pytest.mark.parametrize('module,skills,tools',[
    ('listing_images',{'amazon-aplus-planner'},{'business.save_aplus_plan'}),
    ('amazon_aplus',{'amazon-aplus-planner'},{'business.save_aplus_plan'}),
    ('image_edit',{'image-creation'},{'business.create_images'}),
])
def test_known_module_uses_core_guidance_and_only_relevant_full_schemas(module,skills,tools):
    reg=registry();meta=describe(module)
    selected=ToolSelector.select(reg,'生成图片',primary_skills=meta['primary_skills'])
    value=pc.initial_selection(reg,selected,meta,{}, {'content':'生成图片'})
    assert {s['id'] for s in value['skills']}==skills
    assert {t['id'] for t in value['tools']}==tools
    assert any(c['id']=='business.create_images' for c in pc.directory(reg)['available_capabilities'])


def test_dynamic_discovery_still_enforces_registry_scope():
    reg=registry();meta=describe('listing_images');base=ToolSelector.select(reg,'Listing')
    expanded=pc.initial_selection(reg,base,meta,{}, {'content':'根据我的素材策划'},['business.search_my_assets'],['asset-search'])
    assert {s['id'] for s in expanded['skills']}=={'amazon-aplus-planner','asset-search'}
    assert {t['id'] for t in expanded['tools']}=={'business.save_aplus_plan','business.search_my_assets'}
    with pytest.raises(AppError):pc.initial_selection(reg,base,meta,{}, {'content':'Listing'},['unapproved.remote'])


def test_discovery_only_response_parsed_and_snapshot_facts_preserved():
    d=parse_intent_result(SimpleNamespace(result_json={'metadata':{'text':json.dumps({'summary':'需要搜索的完整参数','discover':['business.search_my_assets']})}}))
    assert d.capability_plan['discover']==['business.search_my_assets']
    payload={'capability_catalog':[],'skill_guidance':[],'history':[{'content':str(i)} for i in range(12)],
        'amazon_plans':[{'id':str(i),'plan':{'modules':[]}} for i in range(4)],'creative_context':describe('amazon_aplus')}
    compact=pc.compact_payload(payload)
    assert compact['history']==payload['history'] and compact['amazon_plans']==payload['amazon_plans']
    assert 'context_version' not in payload


async def test_listing_first_plan_one_model_job_and_reduced_context(advisor):
    ctx=advisor;p=suite(ctx)
    ctx['mock_decision']=model_step('business.save_aplus_plan',{'plan':p.model_dump(mode='json')})
    first=await send(ctx,'先看方案，给这款衣服做一整套Listing附图',[ctx['product_attachment']['id']],creative_module='listing_images')
    event=next(e['payload'] for e in first['events'] if e['type']=='planning_context_ready')
    assert event['skill_bodies']==1 and event['full_tool_schemas']==1
    assert event['characters']<event['before_characters']
    run=await finish(ctx,first)
    assert run['status']=='awaiting_review' and len(run['jobs'])==1
    assert all(j['capability']=='text_generation' for j in run['jobs'])


async def test_wrong_listing_tool_replanned_once_without_image_job(advisor):
    ctx=advisor
    ctx['mock_decision']=model_step('business.create_images',{'instruction':'生成六张图片','count':6})
    first=await send(ctx,'先看方案，生成一整套Listing附图',[ctx['product_attachment']['id']],creative_module='listing_images')
    replan=await finish(ctx,first)
    assert len(replan['jobs'])==2 and all(j['capability']=='text_generation' for j in replan['jobs'])
    assert not any(e['type']=='capability_schema_loaded' for e in replan['events'])
    p=suite(ctx);ctx['mock_decision']=model_step('business.save_aplus_plan',{'plan':p.model_dump(mode='json')})
    result=await finish(ctx,replan)
    assert result['status']=='awaiting_review',result
    assert len(result['jobs'])==2
    assert any(e['type']=='capability_choice_rejected' and e['payload']['code']=='agent.listing_suite_contract' for e in result['events'])


async def test_model_can_discover_extra_tool_before_execution(advisor):
    ctx=advisor
    ctx['mock_decision']={'summary':'需要检索本人素材','skills':['asset-search'],'discover':['business.search_my_assets']}
    first=await send(ctx,'先查找我以前的白底素材，再策划Listing',creative_module='listing_images')
    loaded=await finish(ctx,first)
    assert len(loaded['jobs'])==2
    assert any(e['type']=='capability_schema_loaded' for e in loaded['events'])
    assert not any(e['type']=='capability_call_started' for e in loaded['events'])
    # A request for a forbidden capability cannot be smuggled in as discovery.
    ctx['mock_decision']={'summary':'请求无权限能力','discover':['mcp.unapproved.secret']}
    failed=await finish(ctx,loaded)
    assert failed['status']=='failed' and failed['error_code']=='agent.capability_not_allowed'
    assert all(j['capability']=='text_generation' for j in failed['jobs'])


async def test_repeated_wrong_listing_choice_stops_after_one_replan(advisor):
    ctx=advisor;ctx['mock_decision']=model_step('business.create_images',{'instruction':'六张相同图','count':6})
    first=await send(ctx,'生成一整套Listing附图',[ctx['product_attachment']['id']],creative_module='listing_images')
    run=await finish(ctx,await finish(ctx,first))
    assert run['status']=='failed' and run['error_code']=='agent.listing_suite_contract'
    assert len(run['jobs'])==2 and all(j['capability']=='text_generation' for j in run['jobs'])
