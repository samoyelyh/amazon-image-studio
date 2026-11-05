"""Original upload/Manifest/Agent/Worker in an isolated DB; no paid calls."""
import json
from uuid import uuid4
import pytest
from sqlalchemy import select,func
from pydantic import ValidationError
from app.agents import batch_manifest,production
from app.agents.contracts import MaterialImport
from app.agents.material_import import assignment
from app.models.tasks import Job
from app.models.hermes_agent import HermesConversation
from app.models.content import GeneratedOutput
from tests.test_agent_control import agent_context
from tests.test_agent_chat_v2 import chat_context,send
from tests.test_agent_second_round import second_context,finish
from tests.test_agent_autonomous import autonomous_context
from tests.test_batch_tryon_workflow import upload

MSG='素材导入或关联已更新，请沿用本会话当前批量换衣要求，基于最新素材继续准备；每个模板先生成一张样图，生成后等我审核。'


@pytest.mark.parametrize('source,path,role,key',[
 ('template','衣服/front.png','template',''),
 ('garment','templates/NF0000532-front.png','front','sku:0000532'),
 ('garment','people.png','garment','people'),
 ('garment','包/服装/NF0000532-front.png','front','sku:0000532'),
 ('auto','资料/模板/1.png','template',''),
 ('auto','资料/服装/红球衣/front.png','front','folder:资料/红球衣'),
 ('auto','资料/服装/红球衣/back.png','back','folder:资料/红球衣'),
 ('garment','NF0000532-font.png','font','sku:0000532'),
 ('auto','people.png','reference',''),
])
def test_source_directory_and_sku_hints(source,path,role,key):
    info=MaterialImport(batch_id='import-test',total_files=3,source=source,relative_path=path)
    actual=assignment(info)
    assert actual[:2]==(role,key)


@pytest.mark.parametrize('path',['../a.png','/a.png','C:/a.png','a/../b.png','a//b.png','a\x00.png','a/./b.png','a\u202e.png','a/'*17+'b.png'])
def test_unsafe_paths_rejected_server_side(path):
    with pytest.raises(ValidationError):MaterialImport(batch_id='import-test',total_files=1,relative_path=path)


def test_mixed_front_back_original_allows_optional_existing_crop_tool():
    from types import SimpleNamespace
    t=batch_manifest.ManifestEntry(asset_id='template',role='template',analysis={'view':'back'},import_batch_id='templates',import_total_files=1)
    garment=batch_manifest.ManifestEntry(asset_id='original',role='garment',garment_key='sku:0000532',analysis={'view':'front_back'},import_batch_id='garments',import_total_files=1)
    row=SimpleNamespace(id='manifest',organization_id='org',user_id='user',conversation_id='conv')
    value=batch_manifest.BatchInputManifest(entries=[t,garment])
    first=batch_manifest.snapshot(row,value)
    assert first['crop_recommended_asset_ids']==['original'] and first['crop_required_asset_ids']==[]
    assert first['continue_after_import']
    assert batch_manifest.effective_references(first,'template',first['garments'][0]['id'],strict=True)==['original']
    clean=batch_manifest.ManifestEntry(asset_id='crop',role='back',garment_key='sku:0000532',analysis={'view':'back'},manual=True)
    value.entries.append(clean)
    next=batch_manifest.snapshot(row,value)
    assert next['crop_required_asset_ids']==[] and next['continue_after_import']
    assert batch_manifest.effective_references(next,'template',next['garments'][0]['id'])==['crop']


async def imported(ctx,filename,path,source='auto',total=1,batch=None):
    asset=await upload(ctx['client'],ctx['headers'],'product_reference',filename)
    body={'asset_id':asset['id'],'import_info':{'relative_path':path,'source':source,'total_files':total,'batch_id':batch or str(uuid4())}}
    r=await ctx['client'].post(f"/api/v1/agent/conversations/{ctx['chat']['id']}/attachments",headers=ctx['headers'],json=body)
    assert r.status_code==201,r.text
    return asset,r.json()


async def manifest(ctx):
    return (await ctx['client'].get(f"/api/v1/agent/conversations/{ctx['chat']['id']}/batch-inputs",headers=ctx['headers'])).json()


async def test_import_receipt_grouping_refresh_and_manual_bulk_correction(autonomous_context):
    ctx=autonomous_context;b=str(uuid4())
    t,_=await imported(ctx,'model.png','templates/model.png','template')
    await imported(ctx,'front.png','衣服/0000532/front.png','garment',2,b)
    incomplete=await manifest(ctx)
    assert incomplete['import_summary']['complete'] is False and not incomplete['continue_after_import']
    await imported(ctx,'back.png','衣服/0000532/back.png','garment',2,b)
    m=await manifest(ctx)
    assert len(m['templates'])==1 and len(m['garments'])==1 and m['combination_count']==1
    assert m['import_summary']=={**m['import_summary'],'complete':True,'front_bound':1,'back_bound':1}
    assert m['continue_after_import'] and m['entries'][1]['relative_path']=='衣服/0000532/front.png'
    assert await manifest(ctx)==m
    url=f"/api/v1/agent/conversations/{ctx['chat']['id']}/batch-inputs"
    # Existing bulk API, no new classification service; input provenance immutable.
    for e in m['entries']:
        if e['asset_id']!=t['id']:e['garment_key']='corrected-product'
        e.pop('relative_path',None)
    r=await ctx['client'].put(url,headers=ctx['headers'],json={'expected_revision':m['revision'],'entries':m['entries']})
    assert r.status_code==200,r.text
    assert len(r.json()['garments'])==1 and r.json()['entries'][1]['relative_path']=='衣服/0000532/front.png'
    assert r.json()['continuation_key']!=m['continuation_key']
    viewer=(await ctx['client'].post('/api/v1/auth/login',json={'account':'first-viewer','password':'viewer-password'})).json()
    denied=await ctx['client'].get(url,headers={'Authorization':'Bearer '+viewer['access_token']})
    assert denied.status_code in (403,404)


async def test_known_roles_are_pinned_and_manual_change_invalidates_only_that_cache(autonomous_context):
    ctx=autonomous_context
    t,_=await imported(ctx,'model.png','模特/model.png','template')
    g,_=await imported(ctx,'back.png','服装/NF0000532/back.png','garment')
    async with ctx['session_factory']() as db:
        conv=await db.get(HermesConversation,ctx['chat']['id'])
        a=production.AnalyzeAssets(asset_ids=[t['id'],g['id']],analysis_mode='per_asset')
        result=await production.analyze(db,ctx['settings'],conv,a,'test-import-analysis')
        for jid in result['job_ids']:
            job=await db.get(Job,jid);request=json.loads(job.input_json['user_prompt'])
            assert request['role'] in ('template','back')
            assert request['relative_path']
        await db.commit()
    for jid in result['job_ids']:await ctx['worker']._execute_job(jid)
    async with ctx['session_factory']() as db:
        conv=await db.get(HermesConversation,ctx['chat']['id'])
        await production.cache_completed_analyses(db,conv,result)
        plan=await production.collect_understanding(db,conv,result)
        assert len(plan['template_rules'])==len(plan['garment_rules'])==1
        q=await production.analyze_quote(db,conv,a,ctx['settings']);assert q['analysis_count']==0
        m=await batch_manifest.sync(db,conv)
        entries=[{**e,'role':'front' if e['asset_id']==g['id'] else e['role']} for e in m['entries']]
        await batch_manifest.update(db,conv,batch_manifest.ManifestUpdate(expected_revision=m['revision'],entries=entries))
        q=await production.analyze_quote(db,conv,a,ctx['settings']);assert q['uncached_asset_ids']==[g['id']]


async def test_import_continuation_real_jobs_mock_provider_and_idempotent_refresh(autonomous_context):
    ctx=autonomous_context
    t,_=await imported(ctx,'template.png','模板/template.png','template')
    f,_=await imported(ctx,'NF0000532-front.png','服装/NF0000532-front.png','garment')
    b,_=await imported(ctx,'NF0000532-back.png','服装/NF0000532-back.png','garment')
    m=await manifest(ctx)
    body={'content':MSG,'client_request_id':'imports:'+m['continuation_key'],'chat_mode':True,'auto_execute':True,
        'attachment_ids':[],'use_batch_inputs':True,'creative_module':'batch_tryon'}
    url=f"/api/v1/agent/conversations/{ctx['chat']['id']}/messages"
    r=await ctx['client'].post(url,headers=ctx['headers'],json=body);assert r.status_code==200,r.text
    run=r.json()
    for _ in range(12):
        if run['status'] not in ('waiting_jobs','planning','ready_to_submit','submitted'):break
        run=await finish(ctx,run)
    async with ctx['session_factory']() as db:
        images=list((await db.scalars(select(Job).where(Job.capability!='text_generation'))).all())
        assert len(images)==1
        assert images[0].input_json['reference_asset_ids']==[t['id'],f['id']]
        assert b['id'] not in images[0].input_json['reference_asset_ids']
        assert await db.scalar(select(func.count()).select_from(GeneratedOutput))==1
        before=await db.scalar(select(func.count()).select_from(Job))
    replay=await ctx['client'].post(url,headers=ctx['headers'],json=body)
    assert replay.status_code==200 and replay.json()['id']==run['id']
    async with ctx['session_factory']() as db:assert await db.scalar(select(func.count()).select_from(Job))==before
    await imported(ctx,'NF0000533-front.png','服装/NF0000533-front.png','garment')
    newest=await manifest(ctx)
    body['client_request_id']='imports:'+newest['continuation_key']
    added=await ctx['client'].post(url,headers=ctx['headers'],json=body)
    assert added.status_code==200 and added.json()['id']!=run['id']  # Same words, genuinely changed batch.


async def test_visual_predictions_do_not_change_import_continuation_key(autonomous_context):
    ctx=autonomous_context
    a,_=await imported(ctx,'unknown.png','mixed/unknown.png')
    async with ctx['session_factory']() as db:
        conv=await db.get(HermesConversation,ctx['chat']['id'])
        before=await batch_manifest.sync(db,conv)
        after=await batch_manifest.sync(db,conv,{a['id']:{'role':'template','confidence':.95}})
        assert after['continuation_key']==before['continuation_key']
        low=await batch_manifest.sync(db,conv,{a['id']:{'role':'template','confidence':.2}})
        assert low['unresolved_asset_ids']==[a['id']]


async def test_partial_import_requires_explicit_acceptance_and_is_durable(autonomous_context):
    ctx=autonomous_context
    await imported(ctx,'template.png','templates/template.png','template')
    await imported(ctx,'front.png','garments/NF0000532/front.png','garment',2)
    m=await manifest(ctx);assert not m['continue_after_import']
    url=f"/api/v1/agent/conversations/{ctx['chat']['id']}/batch-inputs"
    r=await ctx['client'].put(url,headers=ctx['headers'],json={'expected_revision':m['revision'],'entries':m['entries'],'accept_partial_imports':True})
    assert r.status_code==200 and r.json()['continue_after_import']
    assert (await manifest(ctx))['import_summary']['complete']
    async with ctx['session_factory']() as db:
        conv=await db.get(HermesConversation,ctx['chat']['id'])
        assert (await batch_manifest.sync(db,conv))['import_summary']['complete']


async def test_bulk_edit_does_not_pin_untouched_unknown_images(autonomous_context):
    ctx=autonomous_context
    await imported(ctx,'template.png','templates/template.png','template')
    unknown,_=await imported(ctx,'unknown.png','mixed/unknown.png')
    async with ctx['session_factory']() as db:
        conv=await db.get(HermesConversation,ctx['chat']['id'])
        m=await batch_manifest.sync(db,conv)
        updated=await batch_manifest.update(db,conv,batch_manifest.ManifestUpdate(expected_revision=m['revision'],entries=m['entries']))
        assert next(e for e in updated['entries'] if e['asset_id']==unknown['id'])['manual'] is False
        after=await batch_manifest.sync(db,conv,{unknown['id']:{'role':'garment','confidence':.95}})
        assert len(after['garments'])==1


async def test_planner_524_hidden_by_max_attempts_is_remote_unknown(autonomous_context):
    from datetime import datetime,timezone
    from app.models.tasks import JobAttempt
    ctx=autonomous_context;ctx['settings'].agent_control_planner='existing_text'
    run=await send(ctx,'帮我生成一张球衣展示图')
    async with ctx['session_factory']() as db:
        job=await db.get(Job,run['jobs'][0]['id'])
        job.status='failed';job.error_code='job.max_attempts'
        db.add(JobAttempt(job_id=job.id,organization_id=job.organization_id,attempt_number=1,status='failed',
            http_status=524,error_code='provider.upstream_error',started_at=datetime.now(timezone.utc)))
        await db.commit()
    observed=(await ctx['client'].get('/api/v1/agent/runs/'+run['id'],headers=ctx['headers'])).json()
    assert observed['status']=='remote_unknown' and observed['error_code']=='agent.remote_unknown'
    assert observed['outputs']==[]


async def test_confirming_rules_does_not_bypass_exact_missing_view_check(autonomous_context):
    from app.models.hermes_agent import HermesMessage
    from app.core.errors import AppError
    from tests.test_agent_analysis_reminders import warning_batch
    ctx=autonomous_context
    case=await warning_batch(ctx,clean=False,template_view='back',garment_view='front')
    async with ctx['session_factory']() as db:
        conv=await db.get(HermesConversation,ctx['chat']['id'])
        row=await db.get(HermesMessage,case['plan_id'])
        r=production.ProductionRules.model_validate(row.metadata_json)
        r.common_prompt+='必须精确还原背面设计'
        r.confirmed_signature=production.rules_signature(r)
        row.metadata_json=r.model_dump(mode='json');await db.flush()
        with pytest.raises(AppError) as caught:
            await production.image_quote(db,conv,production.PlanAction(plan_id=row.id,expected_revision=1),autonomous=True)
        assert caught.value.code=='agent.reference_view_missing'
        assert '背面' in caught.value.message and 'NF0000532.png' in caught.value.message


async def test_added_garment_preserves_sample_review_and_submitted_combinations(autonomous_context):
    ctx=autonomous_context
    t,_=await imported(ctx,'template.png','templates/template.png','template')
    f,_=await imported(ctx,'NF0000532-front.png','garments/NF0000532-front.png','garment')
    async def understand(ids,key):
        async with ctx['session_factory']() as db:
            conv=await db.get(HermesConversation,ctx['chat']['id'])
            r=await production.analyze(db,ctx['settings'],conv,production.AnalyzeAssets(asset_ids=ids),key)
            await db.commit()
        for jid in r['job_ids']:await ctx['worker']._execute_job(jid)
        async with ctx['session_factory']() as db:
            conv=await db.get(HermesConversation,ctx['chat']['id'])
            p=await production.collect_understanding(db,conv,r);await db.commit();return p
    p=await understand([t['id'],f['id']],'first')
    async with ctx['session_factory']() as db:
        conv=await db.get(HermesConversation,ctx['chat']['id'])
        r=await production.generate(db,ctx['settings'],conv,production.PlanAction(plan_id=p['id'],expected_revision=1),'first-sample',autonomous=True)
        await db.commit()
    await ctx['worker']._execute_job(r['job_ids'][0])
    # The normal Agent links are not needed in this service-level test; sample
    # approval snapshot is stored as it would be after the existing review Tool.
    async with ctx['session_factory']() as db:
        conv=await db.get(HermesConversation,ctx['chat']['id'])
        row,rules=await production.plan_record(db,conv,p['id'])
        output=await db.scalar(select(GeneratedOutput).where(GeneratedOutput.job_id==r['job_ids'][0]))
        rules.sample_approvals[t['id']]=output.id
        row.metadata_json=rules.model_dump(mode='json');await db.flush()
        production_result=await production.generate(db,ctx['settings'],conv,production.PlanAction(plan_id=p['id'],expected_revision=1,stage='production'),'production-first',autonomous=True)
        # generate reads the persisted record, so retain the human review snapshot.
        row,rules=await production.plan_record(db,conv,p['id'])
        rules.sample_approvals[t['id']]=output.id;row.metadata_json=rules.model_dump(mode='json')
        await db.commit()
    second,_=await imported(ctx,'NF0000533-front.png','garments/NF0000533-front.png','garment')
    new=await understand([t['id'],f['id'],second['id']],'second')
    async with ctx['session_factory']() as db:
        conv=await db.get(HermesConversation,ctx['chat']['id'])
        _,rules=await production.plan_record(db,conv,new['id'])
        assert rules.samples[t['id']]==r['job_ids'][0] and rules.sample_approvals[t['id']]==output.id
        assert production.action_pairs(rules,production.PlanAction(plan_id=new['id'],expected_revision=1))==[]
        assert len(production.action_pairs(rules,production.PlanAction(plan_id=new['id'],expected_revision=1,stage='production')))==1
        retained=await production.generate(db,ctx['settings'],conv,production.PlanAction(plan_id=new['id'],expected_revision=1),'second-sample',autonomous=True)
        assert retained['job_ids']==[]
