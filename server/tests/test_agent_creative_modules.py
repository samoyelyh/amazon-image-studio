"""Professional context selection is persisted, scoped and independent of fixed tool workflows."""
import json
from uuid import uuid4
import pytest
from sqlalchemy import select
from app.agents import creative_modules,professional_prompts,production
from app.agents.capabilities.registry import CapabilityRegistry,ToolSelector
from app.models.tasks import Job
from app.models.agent_control import AgentRun
from tests.test_agent_control import agent_context
from tests.test_agent_chat_v2 import chat_context,send
from tests.test_agent_second_round import second_context,attach,finish
from tests.test_agent_autonomous import autonomous_context
from tests.test_agent_amazon import sample_plan
from app.agents.capabilities.contracts import ExecutionContext

def exec_context():
    return ExecutionContext('org','user','conversation',str(uuid4()),frozenset({'jobs.read','jobs.submit','assets.read','projects.read','projects.write','batch_tryon.review'}))


async def test_mode_persists_and_switch_only_affects_new_runs(autonomous_context):
    ctx=autonomous_context;ctx['settings'].agent_control_planner='existing_text'
    url='/api/v1/agent/conversations/'+ctx['chat']['id']
    changed=await ctx['client'].put(url+'/creative-context',headers=ctx['headers'],json={'module':'amazon_aplus','expected_revision':0})
    assert changed.status_code==200 and changed.json()['primary_skills']==['amazon-aplus-planner','amazon-visual-brief']
    run=await send(ctx,'按这些商品资料做一套内容，先给我看方案')
    async with ctx['session_factory']() as db:
        stored=await db.get(AgentRun,run['id'])
        assert stored.selection_json['_creative_context']['module']=='amazon_aplus'
        job=await db.get(Job,run['jobs'][0]['id'])
        context=json.loads(job.input_json['user_prompt'])['context']
        assert context['creative_context']['module']=='amazon_aplus'
        assert {s['id'] for s in context['skill_guidance']}=={'amazon-aplus-planner'}
        # Production guidance stays discoverable; its body is loaded after the
        # brief exists instead of entering every initial planning request.
        assert 'amazon-visual-brief' in {s['id'] for s in context['available_skills']}
        assert '接触阴影' in job.input_json['system_prompt']
    r=await ctx['client'].put(url+'/creative-context',headers=ctx['headers'],json={'module':'image_edit','expected_revision':1})
    assert r.status_code==200
    assert (await ctx['client'].put(url+'/creative-context',headers=ctx['headers'],json={'module':'auto','expected_revision':1})).status_code==409
    restored=(await ctx['client'].get(url,headers=ctx['headers'])).json()
    assert restored['creative_context']['module']=='image_edit'
    async with ctx['session_factory']() as db:assert (await db.get(AgentRun,run['id'])).selection_json['_creative_context']['module']=='amazon_aplus'
    next_run=await send(ctx,'按这些商品资料做一套内容，先给我看方案')
    assert next_run['id']!=run['id']  # Identical words after switching expertise are not the old task.
    async with ctx['session_factory']() as db:assert (await db.get(AgentRun,next_run['id'])).selection_json['_creative_context']['module']=='image_edit'


async def test_create_with_module_and_owner_permissions(autonomous_context):
    ctx=autonomous_context
    value=(await ctx['client'].post('/api/v1/agent/conversations',headers=ctx['headers'],json={'context_kind':'chat','creative_module':'listing_images'})).json()
    assert value['creative_context']['module']=='listing_images'
    viewer=(await ctx['client'].post('/api/v1/auth/login',json={'account':'first-viewer','password':'viewer-password'})).json()
    denied=await ctx['client'].put('/api/v1/agent/conversations/'+value['id']+'/creative-context',headers={'Authorization':'Bearer '+viewer['access_token']},json={'module':'amazon_aplus','expected_revision':1})
    assert denied.status_code in (403,404)
    invalid=await ctx['client'].put('/api/v1/agent/conversations/'+value['id']+'/creative-context',headers=ctx['headers'],json={'module':'arbitrary-unapproved-skill','expected_revision':1})
    assert invalid.status_code==422


@pytest.mark.parametrize('module,primary',[('amazon_aplus','amazon-aplus-planner'),('batch_tryon','batch-production'),('listing_images','amazon-aplus-planner'),('free_creation','image-creation'),('image_edit','image-creation')])
def test_module_core_skill_loads_without_user_spelling_it(module,primary):
    from app.core.config import Settings
    registry=CapabilityRegistry(Settings(_env_file=None),exec_context())
    result=ToolSelector.select(registry,'请处理这些素材',primary_skills=creative_modules.describe(module)['primary_skills'])
    assert result['skills'][0]['id']==primary
    assert len(result['skills'])<=5


def test_module_bias_does_not_forbid_dynamic_other_skills_or_tools():
    from app.core.config import Settings
    registry=CapabilityRegistry(Settings(_env_file=None),exec_context())
    r=ToolSelector.select(registry,'这些衣服批量套到模板上，先做样图',primary_skills=creative_modules.describe('amazon_aplus')['primary_skills'])
    assert 'batch-production' in {s['id'] for s in r['skills']}
    assert 'business.generate_tryon' in {t['id'] for t in r['tools']}


def test_aplus_recipe_contains_module_art_direction_not_generic_prose():
    p=sample_plan(str(uuid4()));m=p.modules[0]
    prompt=professional_prompts.aplus(p,m)
    assert m.composition in prompt and m.image_prompt in prompt and m.desktop_layout in prompt and m.mobile_layout in prompt
    assert 'contact shadows' in prompt and 'printed words' in prompt and 'typeset separately' in prompt
    assert 'Do not render headlines, body copy or typography.' not in prompt


def test_hoodie_to_short_sleeve_rebuilds_structure_without_deleting_headwear():
    template=production.AssetUnderstanding(role='template',confidence=1,template_type='stadium_scene',visual_facts=['三个人物穿连帽卫衣'])
    garment=production.AssetUnderstanding(role='garment',confidence=1,visual_facts=['酒红色短袖V领球衣'])
    prompt=professional_prompts.tryon(template,garment)
    assert '抽绳' in prompt and '长袖' in prompt and '帽饰' in prompt and '不更换人物身份' in prompt


async def test_aplus_native_job_uses_canonical_size_not_1024_default(autonomous_context):
    from datetime import datetime,timezone
    from app.agents import amazon
    from app.agents.amazon_contracts import ModuleApproval,GenerateAPlus
    from app.models.hermes_agent import HermesConversation
    from app.models.tasks import ProviderModel,ResourcePool,OperationResourcePool
    from app.models.quota import QuotaRule
    ctx=autonomous_context
    asset,_=await attach(ctx,'jersey.png')
    async with ctx['session_factory']() as db:
        model=await db.scalar(select(ProviderModel).where(ProviderModel.code=='workflow-image'))
        pool=await db.scalar(select(ResourcePool).where(ResourcePool.model_id==model.id))
        for capability in ('image_edit','multi_image_reference'):
            db.add(OperationResourcePool(operation_code='aplus.generate',resource_pool_id=pool.id,required_capability=capability))
        db.add(QuotaRule(organization_id=None,operation_code='aplus.generate',name='Mock A+ dimensions',base_cost=1,
            model_multipliers={},quality_multipliers={},resolution_multipliers={},effective_from=datetime(2020,1,1,tzinfo=timezone.utc)))
        await db.flush()
        conv=await db.get(HermesConversation,ctx['chat']['id'])
        result=await amazon.save(db,conv,sample_plan(asset['id']),'dimension-test')
        plan_id=result['amazon_plan_id']
        await amazon.approve(db,conv,plan_id,ModuleApproval(expected_revision=1,module_ids=['m3'],verified_evidence_ids=['fact1'],commercial_rights_confirmed=True))
        result=await amazon.generate(db,ctx['settings'],conv,GenerateAPlus(plan_id=plan_id,expected_revision=1,module_ids=['m3']),'dimension-test-generate')
        job=await db.get(Job,result['job_ids'][0])
        assert job.input_json['size']=='970x300'
        assert (job.input_json['requested_width'],job.input_json['requested_height'])==(970,300)
        assert job.input_json['aspect_ratio']=='97:30'
        assert job.input_json['quality']=='high'
