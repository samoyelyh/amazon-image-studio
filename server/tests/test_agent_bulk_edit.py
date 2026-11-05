"""Independent edits reuse one native batch; no paid provider calls."""
import pytest
from sqlalchemy import select
from app.models.tasks import Job,JobBatch
from app.agents.contracts import ChatImageAction
from app.agents.adapters import chat
from app.core.errors import AppError
from tests.test_agent_control import agent_context
from tests.test_agent_chat_v2 import chat_context,send
from tests.test_agent_second_round import second_context,attach,finish
from tests.test_agent_autonomous import autonomous_context


def decision(ids,independent=True):
    return {'summary':'只替换每张原图的背景','skills':['image-creation'],'steps':[{
        'capability_id':'business.create_images','reason':'图片编辑，不是服装互换或创意裂变',
        'arguments':{'instruction':'只将背景替换为写实足球场，原人物、服装、颜色、Logo和印花保持不变，不融合其他原图。',
            'edit':True,'independent_edits':independent,'reference_asset_ids':ids}}]}


async def test_ten_independent_edits_one_batch_source_mapping_partial_results_and_followup(autonomous_context):
    ctx=autonomous_context;ctx['settings'].agent_control_planner='existing_text'
    assets=[await attach(ctx,f'original-{i+1:02}.png') for i in range(10)]
    ids=[a['id'] for a,_ in assets]
    ctx['mock_decision']=decision(list(reversed(ids)))  # Model order must not scramble upload order.
    initial=await send(ctx,'先分析这些图片，再把这10张图片背景全部换成足球场，人物、衣服、颜色和图案保持不变',[a['id'] for _,a in assets],creative_module='image_edit')
    submitted=await finish(ctx,initial)
    assert submitted['plan']['workflow']=='edit' and submitted['plan']['image_count']==10,submitted
    images=[j for j in submitted['jobs'] if j['capability']!='text_generation']
    assert len(images)==10 and all(j['capability']=='image_edit' for j in images)
    async with ctx['session_factory']() as db:
        jobs=[await db.get(Job,j['id']) for j in images]
        assert len({j.batch_id for j in jobs})==1
        batch=await db.get(JobBatch,jobs[0].batch_id)
        assert batch.concurrency==10
        assert {tuple(j.input_json['reference_asset_ids']) for j in jobs}=={(aid,) for aid in ids}
        assert {j.input_json['metadata']['agent_image']['source_asset_id'] for j in jobs}==set(ids)
        assert all('只输出1张' in j.input_json['prompt'] for j in jobs)
        assert all(j.input_json['size']==f"{assets[i][0]['width']}x{assets[i][0]['height']}" for i,j in enumerate(sorted(jobs,key=lambda j:j.client_item_id)))
        last=next(j for j in jobs if j.input_json['metadata']['agent_image']['source_index']==10)
    await ctx['worker']._execute_job(last.id)
    partial=(await ctx['client'].get('/api/v1/agent/runs/'+submitted['id'],headers=ctx['headers'])).json()
    assert partial['status']=='waiting_jobs' and len(partial['outputs'])==1
    assert partial['outputs'][0]['source_asset_id']==ids[9] and partial['outputs'][0]['number']==10
    complete=await finish(ctx,submitted)
    assert len(complete['outputs'])==10
    for output in complete['outputs']:
        assert output['source_asset_id']==ids[output['source_index']-1]
        assert (await ctx['client'].get(output['download_url'],headers=ctx['headers'])).status_code==200
    second=next(o for o in complete['outputs'] if o['source_index']==2)
    ctx['mock_decision']={'summary':'仅修改第二张结果','skills':['image-creation'],'steps':[{
        'capability_id':'business.create_images','reason':'保留其他结果',
        'arguments':{'instruction':'只把第二张结果背景改为夜间足球场，人物衣服不变','edit':True,'reference_number':second['number']}}]}
    follow=await finish(ctx,await send(ctx,'第二张背景换成夜间球场'))
    follow_images=[j for j in follow['jobs'] if j['capability']=='image_edit']
    assert len(follow_images)==1
    async with ctx['session_factory']() as db:
        job=await db.get(Job,follow_images[0]['id'])
        assert job.input_json['reference_asset_ids']==[second['asset_id']]
    result=await finish(ctx,follow)
    assert result['outputs'][0]['version']==2 and result['outputs'][0]['parent_output_id']==second['id']
    assert result['outputs'][0]['source_asset_id']==ids[1] and result['outputs'][0]['source_index']==2


async def test_multi_reference_composite_keeps_existing_behavior(autonomous_context):
    ctx=autonomous_context;ctx['settings'].agent_control_planner='existing_text'
    assets=[await attach(ctx,f'reference-{i}.png') for i in range(2)]
    ids=[a['id'] for a,_ in assets];ctx['mock_decision']=decision(ids,False)
    run=await finish(ctx,await send(ctx,'将这两张图融合为一张海报',[a['id'] for _,a in assets],creative_module='free_creation'))
    images=[j for j in run['jobs'] if j['capability']!='text_generation']
    assert len(images)==1 and images[0]['capability']=='multi_image_reference',(run['error_code'],run.get('plan'),run['events'][-3:])
    async with ctx['session_factory']() as db:
        assert (await db.get(Job,images[0]['id'])).input_json['reference_asset_ids']==ids


async def test_invalid_independent_source_cardinality_cannot_submit(autonomous_context):
    from app.models.hermes_agent import HermesConversation
    ctx=autonomous_context
    async with ctx['session_factory']() as db:
        conv=await db.get(HermesConversation,ctx['chat']['id'])
        with pytest.raises(AppError) as caught:
            await chat.generate(db,ctx['settings'],conv,ChatImageAction(prompt='编辑',reference_asset_ids=['a','b'],count=1,model_code='test',capability='image_edit'),'no-submit')
        assert caught.value.code=='agent.edit_source_mismatch'


def test_each_provider_prompt_cannot_request_the_whole_batch():
    prompt=chat.independent_edit_prompt('对3张上传原图分别编辑；三张图片分别输出，保持衣服号码23。',0,3)
    assert '3张上传原图' not in prompt and '三张图片' not in prompt
    assert '号码23' in prompt and '只输出1张' in prompt and '没有人物时不得新增人物' in prompt


def test_only_clear_independent_background_edits_use_representative_planning_pixels():
    from app.agents.intent_router import representative_background_edit
    assert representative_background_edit('把10张图片背景全部换成足球场，人物衣服不变，不拼图不融合','image_edit')
    assert not representative_background_edit('把10张图片融合，背景全部换成足球场','image_edit')
    assert not representative_background_edit('请比较全部背景再决定如何修改','image_edit')
    assert not representative_background_edit('所有模板背景换成足球场','batch_tryon')
