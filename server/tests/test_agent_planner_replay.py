"""Opt-in replay of the exact already-returned response, no real model request."""
import builtins,json
from types import SimpleNamespace
import pytest
from app.agents.planner import parse_intent_result_with_diagnostics
from app.agents.amazon_brief import normalize_arguments
from app.agents.amazon_contracts import SavePlan
from app.models.tasks import Job
from tests.test_agent_control import agent_context
from tests.test_agent_chat_v2 import chat_context,send
from tests.test_agent_second_round import second_context,finish
from tests.test_agent_autonomous import autonomous_context
from tests.test_amazon_advisor import advisor

pytestmark=pytest.mark.skipif(not hasattr(builtins,'AGENT_PLANNER_REPLAY'),reason='Explicit owned stored-response replay')


def test_exact_original_invalid_json_recovers_complete_aplus_brief():
    source=builtins.AGENT_PLANNER_REPLAY
    with pytest.raises(json.JSONDecodeError):json.loads(source['text'])
    d,audit=parse_intent_result_with_diagnostics(SimpleNamespace(input_json={},result_json={'metadata':source}))
    assert audit['normalizations']==['single_redundant_delimiter']
    steps=d.capability_plan['steps'];assert len(steps)==1 and steps[0]['capability_id']=='business.save_aplus_plan'
    plan=SavePlan.model_validate(normalize_arguments(steps[0]['arguments'])).plan
    assert len(plan.modules)>=1 and all(m.image_prompt for m in plan.modules)


async def test_original_shape_reconciles_into_native_mock_jobs_without_new_model(advisor):
    ctx=advisor;source=builtins.AGENT_PLANNER_REPLAY
    parsed,_=parse_intent_result_with_diagnostics(SimpleNamespace(input_json={},result_json={'metadata':source}))
    refs=parsed.capability_plan['steps'][0]['arguments']['brief']['reference_asset_ids']
    raw=source['text']
    for ref in refs:raw=raw.replace(ref,ctx['product']['id'])
    first=await send(ctx,'按上传商品直接生成一套A+图片，不用先审核方案',[ctx['product_attachment']['id']],creative_module='amazon_aplus')
    async with ctx['session_factory']() as db:
        j=await db.get(Job,first['jobs'][0]['id']);j.status='succeeded';j.result_json={'metadata':{**source,'text':raw}};await db.commit()
    response=await ctx['client'].get('/api/v1/agent/runs/'+first['id'],headers=ctx['headers'])
    running=response.json();assert running['status']=='waiting_jobs',running
    assert len([j for j in running['jobs'] if j['capability']=='text_generation'])==1
    count=len(parsed.capability_plan['steps'][0]['arguments']['brief']['modules'])
    assert len([j for j in running['jobs'] if j['capability']!='text_generation'])==count
    assert any(e['type']=='planner_result_normalized' for e in running['events'])
    done=await finish(ctx,running)
    assert done['status']=='completed' and len(done['outputs'])==count
