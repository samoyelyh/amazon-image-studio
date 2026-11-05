"""Upload-guide handoff through the real Agent services, with Mock text/Worker only."""
from sqlalchemy import func, select
import pytest

from app.core.errors import AppError
from app.models.agent_control import AgentRun
from app.models.tasks import Job
from tests.test_agent_control import agent_context
from tests.test_agent_chat_v2 import chat_context, send
from tests.test_agent_second_round import second_context, finish
from tests.test_agent_autonomous import autonomous_context


REQUEST = '开始批量换衣，请引导我上传模板图和服装主图。'
GUIDE = {
    'summary': '准备批量换衣上传入口', 'skills': ['batch-production'],
    'steps': [{'capability_id': 'business.guide_batch_inputs', 'arguments': {},
               'reason': '用户需要导入模板和服装，尚未提供素材'}],
}


def guide_cards(run):
    return [card for action in run['result'].get('actions', [])
            for card in action.get('result', {}).get('cards', [])
            if card.get('type') == 'batch_upload_guide']


async def test_successful_upload_guide_stops_without_second_model_job(autonomous_context):
    ctx = autonomous_context
    ctx['settings'].agent_control_planner = 'existing_text'
    ctx['mock_decision'] = GUIDE
    initial = await send(ctx, REQUEST)
    assert initial['status'] == 'waiting_jobs'
    ready = await finish(ctx, initial)
    assert ready['status'] == 'completed', ready
    assert not ready['error_code'] and not ready['outputs']
    assert len(ready['jobs']) == 1
    assert ready['jobs'][0]['capability'] == 'text_generation'
    assert len(guide_cards(ready)) == 1
    assert any(a['tool'] == 'show_message' and a['result']['readonly_complete']
               for a in ready['result']['actions'])
    assert '上传' in ready['plan']['summary']
    finished = [e['payload'] for e in ready['events'] if e['type'] == 'capability_call_finished']
    assert [(o['capability_id'], o['status']) for o in finished] == [
        ('business.guide_batch_inputs', 'succeeded')]
    for _ in range(2):
        refreshed = (await ctx['client'].get('/api/v1/agent/runs/' + ready['id'], headers=ctx['headers'])).json()
        assert refreshed['status'] == 'completed' and len(guide_cards(refreshed)) == 1
    async with ctx['session_factory']() as db:
        assert await db.scalar(select(func.count()).select_from(Job)) == 1
        stored = await db.get(AgentRun, ready['id'])
        assert stored.result_json['autonomy']['observations'][-1]['status'] == 'succeeded'


async def test_empty_model_plan_without_verified_guide_still_fails(autonomous_context):
    ctx = autonomous_context
    ctx['settings'].agent_control_planner = 'existing_text'
    ctx['mock_decision'] = {'summary': '没有步骤', 'steps': [], 'done': False}
    result = await finish(ctx, await send(ctx, REQUEST))
    assert result['status'] == 'failed' and result['error_code'] == 'agent.capability_missing'
    assert not guide_cards(result) and not result['outputs']


@pytest.mark.parametrize('bad_receipt', [False, True])
async def test_failed_or_invalid_guide_is_not_a_success(autonomous_context, monkeypatch, bad_receipt):
    from app.agents.capabilities import business
    async def unavailable(*args, **kwargs):
        if bad_receipt:
            return {'message': '没有上传卡', 'cards': None}
        raise AppError('agent.guide_unavailable', '隔离测试故障', 503)
    monkeypatch.setattr(business, 'read', unavailable)
    ctx = autonomous_context
    ctx['settings'].agent_control_planner = 'existing_text'
    ctx['mock_decision'] = GUIDE
    pending = await finish(ctx, await send(ctx, REQUEST))
    assert pending['status'] == 'waiting_jobs'
    ctx['mock_decision'] = {'summary': '没有可执行步骤', 'steps': []}
    result = await finish(ctx, pending)
    assert result['status'] == 'failed' and result['error_code'] == 'agent.capability_missing'
    assert not any(e['type'] == 'capability_handoff' for e in result['events'])
    assert not result['outputs']


async def test_empty_plan_restores_guide_from_durable_observation(autonomous_context):
    ctx = autonomous_context
    ctx['settings'].agent_control_planner = 'existing_text'
    ctx['mock_decision'] = {'summary': '入口已准备好，请上传。', 'steps': [], 'done': False}
    pending = await send(ctx, REQUEST)
    # Reproduce the persisted shape of the previous release: guide succeeded,
    # then its action receipt was replaced by the next text planning Job.
    async with ctx['session_factory']() as db:
        run = await db.get(AgentRun, pending['id'])
        run.result_json = {**run.result_json, 'autonomy': {'observations': [{
            'capability_id': 'business.guide_batch_inputs', 'status': 'succeeded',
            'result': {'message': '请上传模板图和服装主图。', 'cards': [{'type': 'batch_upload_guide'}]},
        }]}}
        await db.commit()
    ready = await finish(ctx, pending)
    assert ready['status'] == 'completed' and not ready['error_code']
    assert len(guide_cards(ready)) == 1 and len(ready['jobs']) == 1
    assert not ready['outputs']


async def test_guide_does_not_skip_other_requested_tools_and_receipt_survives_replan(autonomous_context):
    ctx = autonomous_context
    ctx['settings'].agent_control_planner = 'existing_text'
    ctx['mock_decision'] = {**GUIDE, 'steps': [*GUIDE['steps'], {
        'capability_id': 'business.current_context', 'arguments': {}, 'reason': '同时核对现有素材'}]}
    pending = await finish(ctx, await send(ctx, REQUEST + '同时核对现有素材。'))
    assert pending['status'] == 'waiting_jobs' and len(pending['jobs']) == 2
    assert len(guide_cards(pending)) == 1
    assert [o['capability_id'] for o in pending['result']['autonomy']['observations']] == [
        'business.guide_batch_inputs', 'business.current_context']
    ctx['mock_decision'] = {'summary': '已核对，等待上传。', 'steps': [], 'done': True}
    ready = await finish(ctx, pending)
    assert ready['status'] == 'completed' and len(guide_cards(ready)) == 1


async def test_upload_after_guide_continues_native_sample_flow(autonomous_context):
    from tests.test_agent_material_import import imported, MSG
    ctx = autonomous_context
    ctx['settings'].agent_control_planner = 'existing_text'
    ctx['mock_decision'] = GUIDE
    guide = await finish(ctx, await send(ctx, REQUEST))
    assert guide['status'] == 'completed'
    template, _ = await imported(ctx, 'model.png', 'templates/model.png', 'template')
    garment, _ = await imported(ctx, 'front.png', '服装/0000532/front.png', 'garment')
    ctx['settings'].agent_control_planner = 'mock'
    sample = await finish(ctx, await send(ctx, MSG, use_batch_inputs=True))
    result = await finish(ctx, sample)
    assert result['id'] != guide['id'] and result['status'] == 'completed'
    assert len(result['outputs']) == 1
    image = next(job for job in result['jobs'] if job['capability'] != 'text_generation')
    async with ctx['session_factory']() as db:
        stored = await db.get(Job, image['id'])
        assert stored.input_json['reference_asset_ids'] == [template['id'], garment['id']]
    refreshed = (await ctx['client'].get('/api/v1/agent/runs/' + guide['id'], headers=ctx['headers'])).json()
    assert len(guide_cards(refreshed)) == 1 and not refreshed['outputs']
