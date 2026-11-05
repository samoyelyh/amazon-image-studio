"""Fast editing creates native image Jobs without any text model call."""
import pytest
from sqlalchemy import select

from app.agents.fast_edit import uniform_edit_kind, fast_edit_request
from app.models.tasks import Job, JobBatch
from tests.test_agent_control import agent_context
from tests.test_agent_chat_v2 import chat_context, send
from tests.test_agent_second_round import second_context, attach, finish
from tests.test_agent_autonomous import autonomous_context


@pytest.mark.parametrize('text,kind', [
    ('把这10张图片的背景全部换成足球场，人物、衣服、颜色和图案保持不变，不拼图，不融合。', 'background'),
    ('批量统一白底，商品保持不变', 'background'),
    ('所有图片提亮20%，不要过曝，保持球衣颜色和图案', 'brightness'),
    ('把这三张照片统一压暗一点', 'brightness'),
    ('全部换成海边背景，人物保持不变', 'background'),
    ('先分析图片，再把所有图片背景换成足球场', None),
    ('背景换成足球场还是篮球场？', None),
    ('背景换成足球场，第一张提亮，第二张压暗', None),
    ('全部换背景', None),
    ('背景换成新的背景', None),
    ('请把所有模板换衣，背景改成足球场', None),
    ('背景换成足球场，参考图C的风格', None),
    ('将背景换成足球场，局部涂抹号码', None),
    ('将多张融合，背景换成足球场', None),
    ('不要提亮，只告诉我建议', None),
    ('背景换成足球场，以后记住这个偏好', None),
    ('背景换成足球场，衣服换成红色', None),
    ('背景换成足球场，添加一个人', None),
    ('背景换成足球场，不要添加其他人物', 'background'),
    ('帮我写个提示词，背景全部换成足球场', None),
    ('背景全部换成足球场要多少钱？', None),
])
def test_conservative_uniform_edit_classification(text, kind):
    assert uniform_edit_kind(text) == kind


def test_fast_edit_never_guesses_sources_or_overrides_current_module():
    assets = [{'id': str(i), 'attachment_id': 'a'+str(i)} for i in range(3)]
    context = {'assets': assets}
    selection = {'chat_mode': True, 'content': '背景全部换成足球场', 'attachment_ids': ['a2', 'a1']}
    assert fast_edit_request(selection, context, is_autonomous=True)['source_ids'] == ['2', '1']
    assert fast_edit_request(selection, context, is_autonomous=False) is None
    for extra in ({'parent_output_id': 'prior'}, {'reply_to_run_id': 'prior'},
                  {'review_before_generation': True}, {'request_mode': 'suggest'},
                  {'_creative_context': {'module': 'batch_tryon'}}, {'attachment_ids': ['other']},
                  {'attachment_ids': ['a1', 'a1']}, {'attachment_ids': []}, {'use_batch_inputs': True},
                  {'content': '把这3张图片背景全部换成足球场'}, {'content': '背景全部换成足球场，每张生成两张'}):
        assert fast_edit_request({**selection, **extra}, context, is_autonomous=True) is None


@pytest.mark.parametrize('count', [3, 10])
async def test_fast_edit_submits_all_jobs_without_planning_and_preserves_mapping(autonomous_context, monkeypatch, count):
    from app.agents import planner
    async def no_planning(*args, **kwargs):
        raise AssertionError('Fast edit must not submit a text planning Job')
    monkeypatch.setattr(planner, 'submit_intent_job', no_planning)
    ctx = autonomous_context
    ctx['settings'].agent_control_planner = 'existing_text'
    assets = [await attach(ctx, f'fast-source-{i+1:02}.png') for i in range(count)]
    text = f'把这{count}张图片的背景全部换成足球场，人物、衣服、颜色和图案保持不变。'
    request_id = 'fast-edit-replay-'+str(count)
    run = await send(ctx, text, [a['id'] for _, a in assets], creative_module='image_edit', client_request_id=request_id)
    assert run['status'] == 'waiting_jobs', run
    assert len(run['jobs']) == count and all(j['capability'] == 'image_edit' for j in run['jobs'])
    assert run['plan']['capability_context']['pipeline'] == 'fast_edit_pipeline'
    assert any(e['type'] == 'fast_edit_routed' for e in run['events'])
    assert not any(e['type'] == 'awaiting_confirmation' for e in run['events'])
    replay = await send(ctx, text, [a['id'] for _, a in assets], creative_module='image_edit', client_request_id=request_id)
    assert replay['id'] == run['id'] and {j['id'] for j in replay['jobs']} == {j['id'] for j in run['jobs']}
    async with ctx['session_factory']() as db:
        jobs = [await db.get(Job, j['id']) for j in run['jobs']]
        assert len({j.batch_id for j in jobs}) == 1
        assert (await db.get(JobBatch, jobs[0].batch_id)).concurrency == count
        for job in jobs:
            source = job.input_json['metadata']['agent_image']
            index = source['source_index'] - 1
            assert job.input_json['reference_asset_ids'] == [assets[index][0]['id']]
            assert source['source_asset_id'] == assets[index][0]['id']
            assert '保留原图现有标题' in job.input_json['prompt']
        last = next(j for j in jobs if j.input_json['metadata']['agent_image']['source_index'] == count)
    # Refresh and repeated client submission cannot add tasks or change source order.
    history = (await ctx['client'].get('/api/v1/agent/conversations/'+ctx['chat']['id'], headers=ctx['headers'])).json()
    restored = next(r for r in history['runs'] if r['id'] == run['id'])
    assert {j['id'] for j in restored['jobs']} == {j['id'] for j in run['jobs']}
    await ctx['worker']._execute_job(last.id)
    partial = (await ctx['client'].get('/api/v1/agent/runs/'+run['id'], headers=ctx['headers'])).json()
    assert len(partial['outputs']) == 1 and partial['outputs'][0]['source_index'] == count
    complete = await finish(ctx, partial)
    assert complete['status'] == 'completed' and len(complete['outputs']) == count
    for output in complete['outputs']:
        assert output['source_asset_id'] == assets[output['source_index']-1][0]['id']
        assert (await ctx['client'].get(output['download_url'], headers=ctx['headers'])).status_code == 200


async def test_ambiguous_or_reviewed_edit_keeps_the_planned_pipeline(autonomous_context):
    ctx = autonomous_context
    ctx['settings'].agent_control_planner = 'existing_text'
    _, a = await attach(ctx, 'complex-source.png')
    run = await send(ctx, '背景换成足球场还是篮球场，先给我看看方案', [a['id']], creative_module='image_edit')
    assert run['status'] == 'waiting_jobs' and len(run['jobs']) == 1
    assert run['jobs'][0]['capability'] == 'text_generation'
    assert not any(e['type'] == 'fast_edit_routed' for e in run['events'])


async def test_explicit_historical_output_still_uses_model_planning(autonomous_context):
    ctx = autonomous_context
    ctx['settings'].agent_control_planner = 'existing_text'
    _, a = await attach(ctx, 'base.png')
    fast = await send(ctx, '背景换成足球场', [a['id']], creative_module='image_edit')
    base = await finish(ctx, fast)
    edit = await send(ctx, '上一张背景换成篮球场', parent_output_id=base['outputs'][0]['id'])
    assert len(edit['jobs']) == 1 and edit['jobs'][0]['capability'] == 'text_generation'
    assert not any(e['type'] == 'fast_edit_routed' for e in edit['events'])


async def test_fast_edit_cannot_bypass_disabled_execution(autonomous_context):
    ctx = autonomous_context
    ctx['settings'].agent_control_planner = 'existing_text'
    ctx['settings'].agent_control_model_calls_enabled = False
    _, a = await attach(ctx, 'disabled-source.png')
    run = await send(ctx, '背景换成足球场', [a['id']], creative_module='image_edit')
    assert run['status'] == 'failed' and run['error_code'] == 'agent.execution_disabled'
    assert not run['jobs']
