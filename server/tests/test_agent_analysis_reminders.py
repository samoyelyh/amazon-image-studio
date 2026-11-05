"""Regression for Run 47e0236a's high-confidence Luna reminders.

Product facts/IDs are anonymized. The real failure shape is preserved: a gift
template, front/back garment, optional clean front, and ordinary material/font
uncertainties. All assets, Jobs and outputs here are isolated Mock fixtures.
"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.agents import batch_manifest, production
from app.core.errors import AppError
from app.models.content import GeneratedOutput
from app.models.hermes_agent import HermesConversation, HermesMessage
from app.models.tasks import Job
from tests.test_agent_control import agent_context
from tests.test_agent_chat_v2 import chat_context, send
from tests.test_agent_second_round import second_context
from tests.test_agent_autonomous import autonomous_context
from tests.test_agent_material_import import imported


TEMPLATE_NOTES = ['标题及标签的具体字体名称无法确认。', '卫衣面料成分、克重和功能性能不可由画面确认。']
GARMENT_NOTES = ['无法仅凭图片确定面料成分、克重或保暖性能。', '袖口和下摆的具体工艺无法完全确认。']


async def warning_batch(ctx, *, clean=True, template_view='front', garment_view='front_back', unknown=False, confidence=.98):
    template, _ = await imported(ctx, 'template-gift.png', 'templates/template-gift.png', 'template')
    garment, _ = await imported(ctx, 'NF0000532.png', 'garments/NF0000532.png', 'garment')
    front = None
    if clean:
        front, _ = await imported(ctx, 'NF0000532-front.png', 'garments/NF0000532-front.png', 'garment')
    extra = None
    if unknown:
        extra, _ = await imported(ctx, 'unclassified-ad.png', 'unclassified-ad.png', 'auto')
    tr = production.AssetUnderstanding(role='template', confidence=.99, view=template_view,
        template_type='gift_scene', protected_elements=['保留人物、背景和广告版式'], visual_facts=['人物正面礼品展示'],
        uncertainties=TEMPLATE_NOTES)
    gr = production.AssetUnderstanding(role='garment', confidence=confidence, view=garment_view,
        visual_facts=['连帽长袖结构', '服装颜色及正背面图案可辨认'], uncertainties=GARMENT_NOTES)
    analyses = {template['id']: tr.model_dump(mode='json'), garment['id']: gr.model_dump(mode='json')}
    if front:
        analyses[front['id']] = gr.model_copy(update={'role': 'front', 'view': 'front'}).model_dump(mode='json')
    async with ctx['session_factory']() as db:
        conv = await db.get(HermesConversation, ctx['chat']['id'])
        manifest = await batch_manifest.sync(db, conv, analyses)
        gid = manifest['garments'][0]['id']
        rules = production.ProductionRules(common_prompt='保留模板，只替换当前服装。',
            template_rules={template['id']: tr}, garment_rules={gid: gr}, input_manifest=manifest,
            unresolved_asset_ids=list(manifest['unresolved_asset_ids']))
        row = HermesMessage(conversation_id=conv.id, organization_id=conv.organization_id, user_id=conv.user_id,
            role='production_plan', content='隔离普通提醒回归', metadata_json=rules.model_dump(mode='json'),
            created_at=datetime.now(timezone.utc))
        db.add(row); await db.flush(); pid = row.id; await db.commit()
    return {'plan_id': pid, 'rules': rules, 'template': template['id'], 'garment': garment['id'],
            'front': front['id'] if front else None, 'unknown': extra['id'] if extra else None}


async def test_high_confidence_ordinary_reminders_allow_next_stage(autonomous_context):
    ctx = autonomous_context; case = await warning_batch(ctx)
    async with ctx['session_factory']() as db:
        conv = await db.get(HermesConversation, ctx['chat']['id'])
        args = production.PlanAction(plan_id=case['plan_id'], expected_revision=1)
        quote = await production.image_quote(db, conv, args, autonomous=True)
        assert quote['quantity'] == 1 and quote['sufficient']
        result = await production.generate(db, ctx['settings'], conv, args, 'ordinary-notes:' + str(uuid4()), autonomous=True)
        await db.commit()
    assert len(result['job_ids']) == 1
    jid = result['job_ids'][0]
    await ctx['worker']._execute_job(jid)
    async with ctx['session_factory']() as db:
        job = await db.get(Job, jid)
        assert job.status == 'succeeded'
        assert job.input_json['reference_asset_ids'] == [case['template'], case['front']]
        assert job.input_json['metadata']['template_rules']['uncertainties'] == TEMPLATE_NOTES
        assert job.input_json['metadata']['garment_rules']['uncertainties'] == GARMENT_NOTES
        assert await db.scalar(select(GeneratedOutput.id).where(GeneratedOutput.job_id == jid))
        stored = await db.get(HermesMessage, case['plan_id'])
        assert stored.metadata_json['template_rules'][case['template']]['uncertainties'] == TEMPLATE_NOTES


async def test_uncropped_mixed_original_is_usable_even_for_exact_front(autonomous_context):
    ctx = autonomous_context; case = await warning_batch(ctx, clean=False)
    async with ctx['session_factory']() as db:
        conv = await db.get(HermesConversation, ctx['chat']['id'])
        # Historical plans merged crop recommendations into unresolved IDs.
        row=await db.get(HermesMessage,case['plan_id'])
        row.metadata_json={**row.metadata_json,'unresolved_asset_ids':[case['garment']],
            'input_manifest':{**row.metadata_json['input_manifest'],'crop_required_asset_ids':[case['garment']]}}
        await db.flush()
        args=production.PlanAction(plan_id=case['plan_id'],expected_revision=1,instruction='必须精确还原正面图案')
        quote=await production.image_quote(db,conv,args,autonomous=True)
        assert quote['quantity']==1 and not quote['deferred_combinations']
        assert list(quote['reference_selections'].values())==[[case['garment']]]
        assert any('可按需裁剪' in note for note in quote['input_warnings'])
        assert not any('未参与生成' in note for note in quote['input_warnings'])
        result=await production.generate(db,ctx['settings'],conv,args,'uncropped:'+str(uuid4()),autonomous=True)
        job=await db.get(Job,result['job_ids'][0])
        assert job.input_json['reference_asset_ids']==[case['template'],case['garment']]


async def test_unassigned_extra_does_not_block_known_targets(autonomous_context):
    ctx = autonomous_context; case = await warning_batch(ctx, unknown=True)
    async with ctx['session_factory']() as db:
        conv = await db.get(HermesConversation, ctx['chat']['id'])
        quote=await production.image_quote(db,conv,production.PlanAction(plan_id=case['plan_id'],expected_revision=1),autonomous=True)
        assert quote['quantity']==1
        assert any('unclassified-ad.png' in n and '未参与生成' in n for n in quote['input_warnings'])
        assert all(case['unknown'] not in ids for ids in quote['reference_selections'].values())


@pytest.mark.parametrize('kind', ['template', 'garment'])
async def test_missing_required_role_remains_blocked(autonomous_context, kind):
    ctx = autonomous_context; case = await warning_batch(ctx)
    async with ctx['session_factory']() as db:
        row = await db.get(HermesMessage, case['plan_id'])
        row.metadata_json = {**row.metadata_json, kind + '_rules': {}}
        await db.commit()
        conv = await db.get(HermesConversation, ctx['chat']['id'])
        with pytest.raises(AppError) as caught:
            await production.image_quote(db, conv, production.PlanAction(plan_id=case['plan_id'], expected_revision=1), autonomous=True)
        assert caught.value.code == 'agent.roles_unconfirmed'
        assert ('模板图' if kind == 'template' else '服装参考') in caught.value.message
        assert caught.value.details['missing_roles'] == [kind]


async def test_low_confidence_is_advisory_when_target_roles_are_known(autonomous_context):
    ctx = autonomous_context; case = await warning_batch(ctx, confidence=.84)
    async with ctx['session_factory']() as db:
        conv = await db.get(HermesConversation, ctx['chat']['id'])
        quote=await production.image_quote(db,conv,production.PlanAction(plan_id=case['plan_id'],expected_revision=1),autonomous=True)
        assert quote['quantity']==1 and any('置信度' in n for n in quote['input_warnings'])


@pytest.mark.parametrize('template_view',['back','detail','front_back'])
async def test_incomplete_views_are_advisory_for_ordinary_generation(autonomous_context,template_view):
    ctx = autonomous_context; case = await warning_batch(ctx, clean=False, template_view=template_view, garment_view='front')
    async with ctx['session_factory']() as db:
        conv = await db.get(HermesConversation, ctx['chat']['id'])
        quote=await production.image_quote(db,conv,production.PlanAction(plan_id=case['plan_id'],expected_revision=1),autonomous=True)
        assert quote['quantity']==1 and quote['input_warnings']
        assert list(quote['reference_selections'].values())==[[case['garment']]]


async def test_uncropped_original_continues_through_existing_agent_tool(autonomous_context):
    ctx = autonomous_context; case = await warning_batch(ctx, clean=False)
    run = await send(ctx, '按当前规则准备样图', production_plan_id=case['plan_id'],
        production_revision=1, production_stage='validation')
    assert run['status']=='waiting_jobs' and not run['error_code'],run
    assert len(run['jobs'])==1 and not run['plan']['needs_input']
    assert any('可按需裁剪' in n for n in run['plan']['risks'])


async def test_ordinary_reminders_do_not_stop_existing_agent_tool_submission(autonomous_context):
    ctx = autonomous_context; case = await warning_batch(ctx)
    run = await send(ctx, '按当前规则准备样图', production_plan_id=case['plan_id'],
        production_revision=1, production_stage='validation')
    assert run['status'] == 'waiting_jobs' and not run['error_code'], run
    assert len(run['jobs']) == 1 and run['jobs'][0]['capability'] == 'image_edit'


async def test_indeterminate_target_still_names_affected_input(autonomous_context):
    ctx=autonomous_context;case=await warning_batch(ctx)
    async with ctx['session_factory']() as db:
        row=await db.get(HermesMessage,case['plan_id'])
        rules=production.ProductionRules.model_validate(row.metadata_json)
        gid=next(iter(rules.garment_rules))
        rules.garment_rules[gid].role='reference'
        row.metadata_json=rules.model_dump(mode='json');await db.commit()
        conv=await db.get(HermesConversation,ctx['chat']['id'])
        with pytest.raises(AppError) as caught:
            await production.image_quote(db,conv,production.PlanAction(plan_id=row.id,expected_revision=1),autonomous=True)
        assert caught.value.code=='agent.roles_unconfirmed'
        assert '无法确定' in caught.value.message and 'NF0000532.png' in caught.value.message


@pytest.mark.parametrize('stage',['validation','production'])
async def test_exact_missing_back_defers_only_bad_pair_and_submits_good_pair(autonomous_context,stage):
    ctx=autonomous_context;case=await warning_batch(ctx,clean=False,template_view='back',garment_view='front')
    back,_=await imported(ctx,'NF0000533-back.png','garments/NF0000533-back.png','garment')
    async with ctx['session_factory']() as db:
        conv=await db.get(HermesConversation,ctx['chat']['id'])
        br=production.AssetUnderstanding(role='back',confidence=.99,view='back',visual_facts=['背面图案清晰'])
        manifest=await batch_manifest.sync(db,conv,{back['id']:br.model_dump(mode='json')})
        row=await db.get(HermesMessage,case['plan_id'])
        rules=production.ProductionRules.model_validate(row.metadata_json)
        gid=next(g['id'] for g in manifest['garments'] if g['primary_asset_id']==back['id'])
        rules.garment_rules[gid]=br
        rules.input_manifest=manifest
        row.metadata_json=rules.model_dump(mode='json');await db.commit()
        args=production.PlanAction(plan_id=row.id,expected_revision=1,stage=stage,instruction='必须精确还原背面设计，不允许推测')
        quote=await production.image_quote(db,conv,args,autonomous=True)
        assert quote['quantity']==1 and quote['executable_pairs']==[(case['template'],gid)]
        assert len(quote['deferred_combinations'])==1
        assert 'NF0000532.png' in quote['deferred_combinations'][0]['reason']
        assert '背面' in quote['deferred_combinations'][0]['reason']
        result=await production.generate(db,ctx['settings'],conv,args,'partial:'+str(uuid4()),autonomous=True)
        await db.commit()
    assert len(result['job_ids'])==1 and len(result['deferred_combinations'])==1
    await ctx['worker']._execute_job(result['job_ids'][0])
    async with ctx['session_factory']() as db:
        job=await db.get(Job,result['job_ids'][0])
        assert job.status=='succeeded'
        assert job.input_json['reference_asset_ids']==[case['template'],back['id']]
        assert job.input_json['metadata']['garment_id']==gid
        assert await db.scalar(select(GeneratedOutput.id).where(GeneratedOutput.job_id==job.id))
        stored=await db.get(HermesMessage,case['plan_id'])
        if stage=='production':
            assert list(stored.metadata_json['submitted_combinations'])==[f"{case['template']}:{gid}"]
            assert stored.metadata_json['production_batches'][0]['deferred_combinations']==result['deferred_combinations']


def test_builtin_preservation_or_soft_goals_do_not_require_separate_views():
    tid,gid='t','g'
    rules=production.ProductionRules(common_prompt=production.DEFAULT_RULE,template_rules={},garment_rules={})
    args=production.PlanAction(plan_id=str(uuid4()),expected_revision=1)
    assert not production._requires_exact_reference(rules,args,tid,gid)
    for text in ('尽量精确还原','不要求精确还原背面','无需精准还原','生成样图，缺少背面时先试试看'):
        rules.common_prompt=production.DEFAULT_RULE+'\n本次用户要求：'+text
        assert not production._requires_exact_reference(rules,args,tid,gid)
    rules.common_prompt=production.DEFAULT_RULE+'\n本次用户要求：必须精确还原背面号码，不允许推测'
    assert production._requires_exact_reference(rules,args,tid,gid)


def test_specific_error_keeps_all_inputs_but_bounds_chat_summary_length():
    entries = [{'asset_id': f'a{i}', 'filename': 'nested/' * 100 + f'NF{i:07}.png'} for i in range(31)]
    rules = production.ProductionRules(common_prompt='测试', template_rules={}, garment_rules={},
        input_manifest={'entries': entries})
    error = production._input_problem(rules, [e['asset_id'] for e in entries], '请先裁剪正背面')
    assert len(error.message) < 1000 and '等31张素材' in error.message
    assert len(error.details['assets']) == 31
    assert error.details['assets'][0]['name'] == entries[0]['filename']
