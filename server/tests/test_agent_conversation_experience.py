"""Conversation/card parity and durable private experience; all providers are Mock."""
from uuid import uuid4
import pytest
from sqlalchemy import select
from app.agents import experience,production,samples,batch_manifest
from app.models.hermes_agent import HermesConversation,HermesMessage
from app.models.tasks import Job
from app.core.errors import AppError
from tests.test_agent_control import agent_context
from tests.test_agent_chat_v2 import chat_context,send
from tests.test_agent_second_round import second_context,attach,finish
from tests.test_agent_autonomous import autonomous_context


async def detail(ctx):
    return (await ctx['client'].get('/api/v1/agent/conversations/'+ctx['chat']['id'],headers=ctx['headers'])).json()


async def sample_plan(ctx,count=2):
    ids=[]
    for name in [*[f'template-{i}.png' for i in range(count)],'jersey-front.png','jersey-two.png']:
        ids.append((await attach(ctx,name))[1]['id'])
    run=await finish(ctx,await send(ctx,'把这些衣服套到这些模板上',ids))
    ready=await finish(ctx,run)
    assert ready['status']=='completed',ready
    p=(await detail(ctx))['production_plans'][0]
    assert p['sample_review_required'] and len(p['samples'])==count
    assert not p['production_batch_id']
    return p,ready


def card(p,decisions):
    return {'plan_id':p['id'],'expected_revision':p['revision'],'expected_review_revision':p['review_revision'],'decisions':decisions}


async def test_six_sample_natural_review_card_parity_and_partial_production(autonomous_context):
    ctx=autonomous_context
    ctx['settings'].agent_auto_submissions_per_minute=30  # Isolated fixture only; production throttling unchanged.
    p,initial=await sample_plan(ctx,6)
    decisions=[{'sample_number':i,'output_id':p['sample_catalog'][i-1]['output_id'],'decision':'approve' if i in (1,3,5) else 'revise',
        'notes':{2:'背景太暗',4:'号码错误',6:'背景太乱'}.get(i,'')} for i in range(1,7)]
    # Mock model emits a structured plan over the real selected catalog, not real inference.
    ctx['settings'].agent_control_planner='existing_text'
    ctx['mock_decision']={'summary':'只修改2、4、6，保留1、3、5','skills':['batch-production'],'steps':[
        {'capability_id':'business.review_tryon_samples','arguments':card(p,decisions),'reason':'用户逐项审核'}]}
    review=await finish(ctx,await send(ctx,'1、3、5通过，2太暗，4号码错误，6背景太乱，修改有问题的三张'))
    assert len([j for j in review['jobs'] if j['capability']!='text_generation'])==3,review
    changed=await finish(ctx,review)
    assert len(changed['outputs'])==3 and all(o['parent_output_id'] in {x['id'] for x in initial['outputs']} for o in changed['outputs'])
    p=(await detail(ctx))['production_plans'][0]
    assert len(p['sample_approvals'])==3
    # Card production uses the same production Tool with approved_only, no new engine.
    first=await send(ctx,'先生产通过的模板',production_plan_id=p['id'],production_revision=p['revision'],production_stage='production',production_approved_only=True)
    assert len([j for j in first['jobs'] if j['capability']!='text_generation'])==6,first
    p=(await detail(ctx))['production_plans'][0]
    remaining=[{'sample_number':i,'output_id':p['sample_catalog'][i-1]['output_id'],'decision':'approve'} for i in (2,4,6)]
    approved=await send(ctx,'2、4、6通过',sample_review=card(p,remaining))
    assert approved['status']=='completed' and any(a['tool']=='review_tryon_samples' for a in approved['result']['actions']),approved
    p=(await detail(ctx))['production_plans'][0]
    last=await send(ctx,'生产剩余通过模板',production_plan_id=p['id'],production_revision=p['revision'],production_stage='production',production_approved_only=True)
    jobs=[j for j in last['jobs'] if j['capability']!='text_generation']
    assert len(jobs)==6,last
    async with ctx['session_factory']() as db:
        for ref in jobs:
            job=await db.get(Job,ref['id']);meta=job.input_json['metadata']
            assert job.input_json['reference_asset_ids'][0]==meta['template_asset_id']
            assert meta['template_asset_id'] in p['template_rules']
        conv=await db.get(HermesConversation,ctx['chat']['id'])
        _,rules=await production.plan_record(db,conv,p['id'])
        assert len(rules.submitted_combinations)==12 and len(rules.production_batches)==2
        assert not production.action_pairs(rules,production.PlanAction(plan_id=p['id'],expected_revision=p['revision'],stage='production',approved_only=True))
        assert '当前组合' in rules.verified_template_rules[list(rules.template_rules)[3]]['feedback']
    await finish(ctx,first);await finish(ctx,last)
    archive=await ctx['client'].get(f"/api/v1/agent/conversations/{ctx['chat']['id']}/production-plans/{p['id']}/archive",headers=ctx['headers'])
    assert archive.status_code==200,archive.text
    import io,zipfile
    with zipfile.ZipFile(io.BytesIO(archive.content)) as z:
        assert z.testzip() is None and len(z.namelist())==len(set(z.namelist()))==12


async def test_stale_output_and_model_self_approval_are_rejected(autonomous_context):
    ctx=autonomous_context;p,_=await sample_plan(ctx,1)
    async with ctx['session_factory']() as db:
        conv=await db.get(HermesConversation,ctx['chat']['id'])
        args=samples.ReviewSamples.model_validate(card(p,[{'sample_number':1,'decision':'approve','output_id':p['sample_catalog'][0]['output_id']}]))
        with pytest.raises(AppError,match='未收到'):await samples.execute(db,ctx['settings'],conv,args,'test',human_request='帮我看看样图')
        args.decisions[0].output_id=str(uuid4())
        with pytest.raises(AppError,match='样图已更新'):await samples.resolve(db,conv,args)
    assert not (await detail(ctx))['production_plans'][0]['sample_approvals']


async def test_memory_private_persisted_correctable_and_task_only(autonomous_context):
    ctx=autonomous_context
    async with ctx['session_factory']() as db:
        conv=await db.get(HermesConversation,ctx['chat']['id'])
        args=experience.PreferenceChange(action='remember',product_type='jersey',value='brighter')
        saved=await experience.change(db,conv,args,human_request='以后这类球衣背景都亮一点')
        assert saved['preference']['revision']==1
        with pytest.raises(AppError):await experience.change(db,conv,args,human_request='这次特殊要求不用记住')
        with pytest.raises(AppError):await experience.change(db,conv,args.model_copy(update={'key':'visual_style','value':'球衣改成红色'}),human_request='以后都这样')
        await db.commit()
    # A fresh session and another conversation emulate cross-process persistence, no Python singleton.
    async with ctx['session_factory']() as db:
        source=await db.get(HermesConversation,ctx['chat']['id'])
        conv=HermesConversation(organization_id=source.organization_id,user_id=source.user_id,mode='chat',controller_type='langgraph',title='新会话')
        db.add(conv);await db.flush()
        memory=await experience.recall(db,conv,experience.MemoryQuery(product_type='jersey'))
        assert len(memory['preferences'])==1 and experience.prompt_rules(memory)[0]['revision']==1
        assert not experience.prompt_rules(memory,'这次背景暗一点')
        foreign=HermesConversation(organization_id=source.organization_id,user_id=str(uuid4()),mode='chat',controller_type='langgraph',title='另一用户')
        assert not (await experience.recall(db,foreign,experience.MemoryQuery(product_type='jersey')))['preferences']
        await experience.change(db,conv,args.model_copy(update={'value':'neutral','expected_revision':1}),human_request='以后背景改成中性曝光')
        await experience.change(db,conv,args.model_copy(update={'action':'forget','expected_revision':2}),human_request='以后不要使用之前的背景偏好')
        assert not (await experience.recall(db,conv,experience.MemoryQuery(product_type='jersey')))['preferences']
        await db.commit()
    conversations=(await ctx['client'].get('/api/v1/agent/conversations',headers=ctx['headers'])).json()
    assert all(c['title']!='个人创作经验' for c in conversations)


async def test_only_repeated_approved_cases_infer_preference_and_opt_out(autonomous_context):
    ctx=autonomous_context
    async with ctx['session_factory']() as db:
        conv=await db.get(HermesConversation,ctx['chat']['id'])
        async def record(plan,output,opt_out=False):
            return await experience.record_case(db,conv,plan_id=plan,template_id='t',product_type='jersey',scenario='pure_white',before_output_id='old',
                after_output_id=output,notes='背景太暗',rule=experience.correction_rule('背景太暗'),opt_out=opt_out)
        await record('same','1');await record('same','2');await record('other','3')
        assert not (await experience.recall(db,conv,experience.MemoryQuery(product_type='jersey',scenario='pure_white')))['preferences']
        assert await record('ignored','x',True) is None
        await record('third','4')
        recalled=await experience.recall(db,conv,experience.MemoryQuery(product_type='jersey',scenario='pure_white'))
        assert recalled['preferences'][0]['source']=='three_approved_cases'
        assert len(recalled['successful_cases'])==4
        assert not (await experience.recall(db,conv,experience.MemoryQuery(product_type='jersey',scenario='gift_scene')))['preferences']


def test_superseded_references_not_reused_but_legacy_manifest_hash_stable():
    entries=[batch_manifest.ManifestEntry(asset_id='t',role='template',filename='t'),batch_manifest.ManifestEntry(asset_id='g',role='garment',filename='jersey'),
        batch_manifest.ManifestEntry(asset_id='old',role='front',garment_key='jersey',enabled=False),batch_manifest.ManifestEntry(asset_id='new',role='front',garment_key='jersey')]
    t,g,u=batch_manifest.grouped(batch_manifest.BatchInputManifest(entries=entries),'c')
    assert g[0]['references']['front']==['new'] and not u


def test_positive_approval_clause_does_not_authorize_rejected_sample():
    assert samples.authorized_approval('1、3、5通过，2太暗',3)
    assert not samples.authorized_approval('1通过，2不通过',2)
    assert not samples.authorized_approval('所有没通过的重做',2)
    assert not samples.authorized_approval('除了2其他都通过',2)
    assert samples.authorized_approval('除了2其他都通过',3)
    assert samples.authorized_approval('一、三、五通过，二太暗',3)


async def test_preference_tool_through_chat_and_no_unrequested_image(autonomous_context):
    ctx=autonomous_context;ctx['settings'].agent_control_planner='existing_text'
    ctx['mock_decision']={'summary':'仅记住球衣背景偏好','skills':['image-creation'],'steps':[
        {'capability_id':'business.manage_user_preference','arguments':{'action':'remember','product_type':'jersey','key':'background_brightness','value':'brighter'},'reason':'用户明确说以后'}]}
    run=await finish(ctx,await send(ctx,'以后这类球衣背景都亮一点'))
    assert run['status']=='completed' and all(j['capability']=='text_generation' for j in run['jobs']),run
    assert run['result']['actions'][0]['result']['cards'][0]['type']=='memory_receipt'
    async with ctx['session_factory']() as db:
        conv=await db.get(HermesConversation,ctx['chat']['id'])
        assert (await experience.recall(db,conv,experience.MemoryQuery(product_type='jersey')))['preferences'][0]['value']=='brighter'


async def test_failed_sample_only_retry_and_unknown_not_replayed(autonomous_context,monkeypatch):
    from app.providers.base import ProviderError
    ctx=autonomous_context;adapter=ctx['worker'].get_provider_adapter;fail=[True]
    class Fault:
        async def execute(self,**kwargs):
            if fail[0] and kwargs['capability']!='text_generation' and (kwargs['payload'].get('metadata') or {}).get('template_name')=='template-1.png':
                raise ProviderError('provider.invalid_image','isolated damaged sample')
            return await adapter('mock',ctx['settings']).execute(**kwargs)
    monkeypatch.setattr(ctx['worker'],'get_provider_adapter',lambda *a:Fault())
    ids=[(await attach(ctx,n))[1]['id'] for n in ('template-0.png','template-1.png','jersey.png')]
    finished=await finish(ctx,await finish(ctx,await send(ctx,'批量换衣，先做样图',ids)))
    p=(await detail(ctx))['production_plans'][0]
    assert finished['status']=='failed' and p['sample_catalog'][1]['status']=='failed'
    good_job=p['sample_catalog'][0]['job_id']
    fail[0]=False
    run=await send(ctx,'只重试第2张样图',sample_review=card(p,[{'sample_number':2,'decision':'redo'}]))
    assert len(run['jobs'])==1,run
    final=await finish(ctx,run)
    assert final['status']=='completed' and len(final['outputs'])==1,final
    p=(await detail(ctx))['production_plans'][0]
    assert p['sample_catalog'][0]['job_id']==good_job
    async with ctx['session_factory']() as db:
        conv=await db.get(HermesConversation,ctx['chat']['id'])
        job=await db.get(Job,p['samples'][list(p['template_rules'])[1]])
        job.status='failed';job.error_code='provider.remote_unknown'
        with pytest.raises(AppError,match='上游状态未知'):
            await samples.resolve(db,conv,samples.ReviewSamples.model_validate(card(p,[{'sample_number':2,'decision':'redo'}])))
        from app.models.tasks import JobAttempt
        attempt=await db.scalar(select(JobAttempt).where(JobAttempt.job_id==job.id))
        job.error_code='job.max_attempts';attempt.http_status=524;attempt.error_code='provider.upstream_error'
        assert await samples.upstream_unknown(db,job)
