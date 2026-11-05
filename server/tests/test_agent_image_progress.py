import pytest
from datetime import datetime,timezone
from sqlalchemy import select
from app.models.tasks import Job,JobAttempt
from tests.test_agent_control import agent_context
from tests.test_agent_chat_v2 import chat_context,send
from tests.test_agent_second_round import second_context,finish
from tests.test_agent_autonomous import autonomous_context
from tests.test_amazon_advisor import advisor,suite,model_step


async def started(ctx):
    p=suite(ctx);ctx['mock_decision']=model_step('business.save_aplus_plan',{'plan':p.model_dump(mode='json')})
    run=await finish(ctx,await send(ctx,'给这款衣服生成整套Listing图片',[ctx['product_attachment']['id']],creative_module='listing_images'))
    assert run['status']=='waiting_jobs',run
    return run


async def test_auto_suite_partial_results_refresh_and_single_retry(advisor):
    ctx=advisor;run=await started(ctx)
    images=[j for j in run['jobs'] if j['capability']!='text_generation'];assert len(images)==4
    await ctx['worker']._execute_job(images[0]['id'])
    first=(await ctx['client'].get('/api/v1/agent/runs/'+run['id'],headers=ctx['headers'])).json()
    assert first['status']=='waiting_jobs' and len(first['outputs'])==1
    async with ctx['session_factory']() as db:
        j=await db.get(Job,images[1]['id']);j.status='failed';j.error_code='provider.rejected';await db.commit()
    for job in images[2:]:await ctx['worker']._execute_job(job['id'])
    ended=(await ctx['client'].get('/api/v1/agent/runs/'+run['id'],headers=ctx['headers'])).json()
    assert ended['status']=='failed' and len(ended['outputs'])==3
    failed=next(j for j in ended['jobs'] if j['id']==images[1]['id']);assert failed['can_retry'] and not failed['upstream_unknown']
    retry=await send(ctx,'仅重新生成这张失败图片',retry_image_job_id=failed['id'])
    assert len(retry['jobs'])==1 and retry['jobs'][0]['capability']!='text_generation'
    assert retry['result']['retry_of_job_id']==failed['id']
    again=await send(ctx,'重试同一张',retry_image_job_id=failed['id'])
    assert again['id']==retry['id'] and len(again['jobs'])==1
    complete=await finish(ctx,retry);assert complete['status']=='completed' and len(complete['outputs'])==1
    assert len(ended['outputs'])==3  # untouched successful originals
    history=(await ctx['client'].get('/api/v1/agent/conversations/'+ctx['chat']['id'],headers=ctx['headers'])).json()
    assert sum(len(r['outputs']) for r in history['runs'])==4


async def test_generic_524_http_attempt_is_not_retryable(advisor):
    ctx=advisor;run=await started(ctx)
    jid=next(j['id'] for j in run['jobs'] if j['capability']!='text_generation')
    async with ctx['session_factory']() as db:
        job=await db.get(Job,jid);job.status='failed';job.error_code='provider.upstream_error'
        db.add(JobAttempt(job_id=jid,organization_id=job.organization_id,attempt_number=1,worker_name='mock',
            status='failed',http_status=524,error_code='provider.upstream_error',started_at=datetime.now(timezone.utc)))
        await db.commit()
    observed=(await ctx['client'].get('/api/v1/agent/runs/'+run['id'],headers=ctx['headers'])).json()
    item=next(j for j in observed['jobs'] if j['id']==jid)
    assert item['upstream_unknown'] and not item['can_retry']
    response=await ctx['client'].post('/api/v1/agent/conversations/'+ctx['chat']['id']+'/messages',headers=ctx['headers'],json={
        'content':'仅重新生成这张失败图片','client_request_id':'unknown-retry','chat_mode':True,'retry_image_job_id':jid})
    assert response.status_code==409 and 'agent.remote_unknown' in response.text


@pytest.mark.parametrize('raw',[
    '{"summary":"private-note","steps":[',
    '{"summary":"private-note","summary":"duplicate","steps":[]}',
])
async def test_unsafe_planner_result_stops_without_another_model_or_image(advisor,raw):
    ctx=advisor
    first=await send(ctx,'生成一套A+图片',[ctx['product_attachment']['id']],creative_module='amazon_aplus')
    async with ctx['session_factory']() as db:
        j=await db.get(Job,first['jobs'][0]['id']);j.status='succeeded'
        j.result_json={'metadata':{'text':raw,'finish_reason':'stop'}};await db.commit()
    for _ in range(2):
        result=(await ctx['client'].get('/api/v1/agent/runs/'+first['id'],headers=ctx['headers'])).json()
        assert result['status']=='failed' and result['error_code']=='agent.invalid_planner_result'
        assert len(result['jobs'])==1 and result['jobs'][0]['capability']=='text_generation'
        assert '无法安全执行' in result['result']['execution_error']
    event=next(e for e in result['events'] if e['type']=='planner_result_rejected')
    assert 'private-note' not in str(event['payload'])
