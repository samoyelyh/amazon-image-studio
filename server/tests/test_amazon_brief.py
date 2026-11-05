"""Compact professional decisions, original plan/Composer and native isolated Jobs."""
import json
from datetime import datetime,timezone
from copy import deepcopy
import pytest
from pydantic import ValidationError
from sqlalchemy import select
from app.agents import amazon,professional_prompts
from app.agents.amazon_brief import DesignBrief,expand,normalize_arguments,SaveDesignBrief
from app.agents.capabilities.planning_context import compact_payload
from app.models.tasks import Job
from tests.test_agent_control import agent_context
from tests.test_agent_chat_v2 import chat_context,send
from tests.test_agent_second_round import second_context,finish
from tests.test_agent_autonomous import autonomous_context
from tests.test_amazon_advisor import advisor,model_step


def brief(asset,deliverable='aplus',count=3):
    return {'deliverable':deliverable,'marketplace':'US',
        'product_identity_lock':'黑橙渐变连帽上衣，保留Baltimore印花、领口、抽绳和原图版型。',
        'campaign_style_lock':'自然左侧柔光，黑橙品牌配色，商品优先，简洁留白。',
        'reference_asset_ids':[asset],'evidence':[{'id':'p1','statement':'原图上衣为黑橙渐变，胸前有Baltimore印花。'}],
        'risks':['未确认材质、授权和定制服务，不做性能承诺。'],
        'modules':[{'id':f'm{i}','title':f'视觉模块{i}','spec_id':'listing_square' if deliverable=='listing' else 'basic_image_text_overlay',
            'main_point':'展示真实上衣外观','composition':f'视角{i}：产品位于左侧，球场看台虚化，左侧柔光，胸前图案清晰，右侧干净留白。',
            'evidence_ids':['p1'],'design_direction':'watch','copy_space':'right','headline':'Game Day Style'} for i in range(1,count+1)]}


@pytest.mark.parametrize('deliverable,count',[('aplus',3),('listing',6)])
def test_complete_decisions_compile_independent_prompts_and_preserve_locks(deliverable,count):
    b=DesignBrief.model_validate(brief('asset',deliverable,count))
    p=expand(b,collected_at=datetime(2026,11,5,tzinfo=timezone.utc))
    assert len(p.modules)==count and not amazon.findings(p)
    prompts=[professional_prompts.aplus(p,m) for m in p.modules]
    assert len(set(prompts))==count
    assert all(prompt.count(p.product_identity_lock)==1 and prompt.count(p.campaign_style_lock)==1 for prompt in prompts)
    assert all('contact shadows' in prompt and 'Typeset' in prompt for prompt in prompts)
    assert all(m.reference_asset_ids==['asset'] and m.desktop_layout and m.mobile_layout for m in p.modules)
    assert len(json.dumps(b.model_dump()))<len(json.dumps(p.model_dump(mode='json')))


def test_invalid_facts_duplicates_and_extra_prompt_rejected():
    base=brief('asset')
    for modify in ('missing_fact','duplicate','extra_prompt'):
        b=deepcopy(base)
        if modify=='missing_fact':b['modules'][0]['evidence_ids']=['invented']
        if modify=='duplicate':b['modules'][1]['id']='m1'
        if modify=='extra_prompt':b['modules'][0]['image_prompt']='huge repeated output'
        with pytest.raises(ValidationError):DesignBrief.model_validate(b)
    p=expand(DesignBrief.model_validate(base)).model_dump(mode='json')
    assert normalize_arguments({'plan':p})=={'plan':p}  # legacy clients unchanged


def test_longer_multilingual_design_is_not_silently_truncated():
    value=brief('asset');composition='Model-authored view, garment placement, light and background. '*10
    value['modules'][0]['composition']=composition
    p=expand(DesignBrief.model_validate(value))
    assert p.modules[0].composition==composition
    assert composition in professional_prompts.aplus(p,p.modules[0])


@pytest.mark.parametrize('deliverable',['aplus','listing'])
def test_unique_approved_spec_is_derived_not_repeated_by_model(deliverable):
    value=brief('asset',deliverable)
    for m in value['modules']:m.pop('spec_id')
    p=expand(DesignBrief.model_validate(value))
    assert not amazon.findings(p)
    assert all(m.spec_id==('listing_square' if deliverable=='listing' else 'basic_image_text_overlay') for m in p.modules)


def test_compact_schema_and_duplicate_read_receipt_do_not_duplicate_facts():
    payload={'capability_catalog':[{'id':'business.save_aplus_plan','description':'save','input_schema':{'type':'object'}}],
        'skill_guidance':[],'creative_context':{'module':'amazon_aplus'},'amazon_rules':amazon.rules(),
        'amazon_plans':[],'assets':[{'id':'asset'}],'amazon_research':[{'id':'r1','request_key':'key','content':{'reviews':['sample']},'chargedUnits':None}],
        'observations':[{'capability_id':'business.amazon_context','status':'succeeded','result':{'rules':amazon.rules(),'assets':[{'id':'asset'}]}},
            {'capability_id':'mcp.ss_mcp.asin.detail','status':'succeeded','result':{'request_key':'key','content':{'reviews':['sample']},'chargedUnits':None}}]}
    original=deepcopy(payload);out=compact_payload(payload)
    assert payload==original
    assert 'brief' in out['capability_catalog'][0]['input_schema']['properties']
    assert len(out['amazon_rules']['modules'])==len(amazon.rules()['modules'])
    assert 'content' not in out['observations'][1]['result'] and out['amazon_research'][0]['chargedUnits'] is None


@pytest.mark.parametrize('deliverable,count',[('aplus',3),('listing',6)])
async def test_native_chat_save_review_and_whole_batch_submission(advisor,deliverable,count):
    ctx=advisor;ctx['mock_decision']=model_step('business.save_aplus_plan',{'brief':brief(ctx['product']['id'],deliverable,count)})
    pending=await send(ctx,'先看方案，为参考商品做一整套图片',[ctx['product_attachment']['id']],creative_module='amazon_aplus' if deliverable=='aplus' else 'listing_images')
    planned=await finish(ctx,pending)
    assert planned['status']=='awaiting_review',planned
    assert len(planned['jobs'])==1 and any(e['type']=='amazon_brief_compiled' for e in planned['events'])
    submitted=await send(ctx,'可以')
    images=[j for j in submitted['jobs'] if j['capability']!='text_generation']
    assert len(images)==count and submitted['status']=='waiting_jobs'
    async with ctx['session_factory']() as db:
        jobs=[await db.get(Job,j['id']) for j in images]
        assert len({j.batch_id for j in jobs})==1
        assert all(j.input_json['quality']=='high' and 'PRODUCT IDENTITY LOCK:' in j.input_json['prompt'] for j in jobs)
    # Complete only through the original Mock Provider, not a paid image API.
    completed=await finish(ctx,submitted)
    assert completed['status']=='completed' and len(completed['outputs'])==count


async def test_compact_brief_cannot_reference_an_unobserved_asset(advisor):
    ctx=advisor;data=brief('00000000-0000-0000-0000-000000000001')
    ctx['mock_decision']=model_step('business.save_aplus_plan',{'brief':data})
    run=await finish(ctx,await send(ctx,'先看方案，做一套A+',[ctx['product_attachment']['id']],creative_module='amazon_aplus'))
    assert run['status']=='failed' and run['error_code']=='agent.context_mismatch'
    assert all(j['capability']=='text_generation' for j in run['jobs'])


@pytest.mark.parametrize('code,compact,expected',[
    ('gpt-6.1-sol',True,'low'),('gpt-6.1-sol',False,None),('different-model',True,None),
])
async def test_reasoning_parameter_scoped_to_validated_sol_brief(monkeypatch,code,compact,expected):
    from types import SimpleNamespace
    from app.agents import planner
    from app.core.config import Settings
    captured={}
    async def resolve(*a,**k):return code
    async def submit(*a,**k):captured.update(k['payload'].input);return SimpleNamespace(id='isolated'),False
    monkeypatch.setattr(planner,'resolve_operation_model_code',resolve)
    monkeypatch.setattr(planner,'submit_job',submit)
    ctx={'amazon_brief_contract':'amazon-design-decisions-v1'} if compact else {}
    await planner.submit_intent_job(None,Settings(_env_file=None,agent_control_model_calls_enabled=True),'org','user',None,'design','test:planning',chat_mode=True,context_summary=ctx)
    assert captured.get('reasoning_effort')==expected
    assert captured.get('stream',False)==compact
