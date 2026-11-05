"""Chat-native batch inputs and native B Jobs, isolated SQLite + Mock Provider only."""
import pytest
import os
from uuid import uuid4
from sqlalchemy import select
from app.models.tasks import Job
from app.models.hermes_agent import HermesConversation
from app.agents import production,batch_manifest
from tests.test_agent_control import agent_context
from tests.test_agent_chat_v2 import chat_context,send
from tests.test_agent_second_round import second_context,attach,finish
from tests.test_agent_autonomous import autonomous_context


async def test_direct_analysis_native_job_contract(autonomous_context):
    ctx=autonomous_context
    template,_=await attach(ctx,'template-front.png');garment,_=await attach(ctx,'shirt.png')
    async with ctx['session_factory']() as db:
        conv=await db.get(HermesConversation,ctx['chat']['id'])
        result=await production.analyze(db,ctx['settings'],conv,production.AnalyzeAssets(asset_ids=[template['id'],garment['id']]),'test:'+str(uuid4()))
        assert len(result['job_ids'])==2


async def test_partial_analysis_success_is_cached_before_other_jobs_finish(autonomous_context):
    ctx=autonomous_context
    assets=[(await attach(ctx,n))[0]['id'] for n in ('template.png','garment.png')]
    async with ctx['session_factory']() as db:
        conv=await db.get(HermesConversation,ctx['chat']['id'])
        result=await production.analyze(db,ctx['settings'],conv,production.AnalyzeAssets(asset_ids=assets),'partial:'+str(uuid4()))
        await db.commit()
    await ctx['worker']._execute_job(result['job_ids'][0])
    async with ctx['session_factory']() as db:
        conv=await db.get(HermesConversation,ctx['chat']['id'])
        assert await production.cache_completed_analyses(db,conv,result)
        q=await production.analyze_quote(db,conv,production.AnalyzeAssets(asset_ids=assets),ctx['settings'])
        assert q['analysis_count']==1 and q['uncached_asset_ids']==[assets[1]]


def test_logical_garments_views_and_font_grouping():
    entries=[batch_manifest.ManifestEntry(asset_id='t',filename='template.png',role='template',analysis={'view':'back'}),
        *[batch_manifest.ManifestEntry(asset_id=role,filename='NF0000532-'+role+'.png',role=role) for role in ('front','back','detail','font')]]
    m=batch_manifest.BatchInputManifest(entries=entries)
    templates,garments,unknown=batch_manifest.grouped(m,'conversation')
    assert len(templates)==len(garments)==1 and not unknown
    value={**m.model_dump(),'templates':templates,'garments':garments}
    assert batch_manifest.effective_references(value,'t',garments[0]['id'])==['back','font']
    templates[0]['analysis']['view']='front_back'
    assert batch_manifest.effective_references(value,'t',garments[0]['id'])==['front','back','detail','font']
    templates[0]['analysis']['view']='front';garments[0]['references']['front']=[]
    assert batch_manifest.effective_references(value,'t',garments[0]['id'])==['back','font']
    with pytest.raises(Exception,match='正面'):batch_manifest.effective_references(value,'t',garments[0]['id'],strict=True)


def test_many_files_are_not_counted_as_many_garments_and_pairing_is_explicit():
    entries=[batch_manifest.ManifestEntry(asset_id=f't{i}',filename=f'template-{i}.png',role='template') for i in range(6)]
    entries += [batch_manifest.ManifestEntry(asset_id=f'{i}-{view}',filename=f'NF{i:07}-{view}.png',role=view) for i in range(32) for view in ('front','back','detail')]
    m=batch_manifest.BatchInputManifest(entries=entries)
    t,g,u=batch_manifest.grouped(m,'conv')
    value={**m.model_dump(),'templates':t,'garments':g}
    assert len(entries)==102 and len(g)==32 and not u and len(batch_manifest.pairs(value))==192
    value.update(pairing_mode='custom',pairs=[{'template_asset_id':t[2]['asset_id'],'garment_id':g[7]['id']}])
    assert batch_manifest.pairs(value)==[(t[2]['asset_id'],g[7]['id'])]


def test_dual_view_composer_image_order_is_a_front_font_back():
    from app.agents.production import AssetUnderstanding,ProductionRules,combination_references
    import types
    entries=[batch_manifest.ManifestEntry(asset_id='t',filename='template.png',role='template',analysis={'view':'front_back'}),
        *[batch_manifest.ManifestEntry(asset_id=r,filename='NF0000532-'+r+'.png',role=r) for r in ('front','back','font')]]
    m=batch_manifest.BatchInputManifest(entries=entries)
    t,g,u=batch_manifest.grouped(m,'conv');value={**m.model_dump(),'templates':t,'garments':g}
    rules=ProductionRules(common_prompt='规则',template_rules={'t':AssetUnderstanding(role='template',confidence=1,view='front_back')},garment_rules={},input_manifest=value)
    assert combination_references(rules,'t',g[0]['id'])==['front','font','back']


def test_legacy_rules_signatures_remain_compatible():
    from app.agents.capabilities.registry import digest
    raw={'common_prompt':'规则','template_rules':{},'garment_rules':{},'combination_overrides':[], 'unresolved_asset_ids':[]}
    assert production.rules_signature(production.ProductionRules(**raw))==digest(raw)
    from app.agents.contracts import MessageCreate
    raw_message={'content':'生成图片','client_request_id':str(uuid4()),'chat_mode':True}
    old=MessageCreate.model_validate(raw_message).submission_payload()
    assert 'use_batch_inputs' not in old
    assert old==MessageCreate.model_validate({**raw_message,'use_batch_inputs':False}).submission_payload()


def test_explicit_sample_scope_selects_only_requested_templates():
    rule=production.AssetUnderstanding(role='template',confidence=1)
    r=production.ProductionRules(common_prompt='规则',template_rules={'t1':rule,'t2':rule},garment_rules={'g1':rule,'g2':rule})
    args=production.PlanAction(plan_id=str(uuid4()),expected_revision=1,stage='validation',template_asset_ids=['t2'])
    assert production.action_pairs(r,args)==[('t2','g1')]


async def test_manifest_persists_and_conflicts_and_owner_scope(autonomous_context):
    ctx=autonomous_context
    a,_=await attach(ctx,'template.png');b,_=await attach(ctx,'NF0000532-front.png');c,_=await attach(ctx,'NF0000532-back.png')
    url='/api/v1/agent/conversations/'+ctx['chat']['id']+'/batch-inputs'
    m=(await ctx['client'].get(url,headers=ctx['headers'])).json()
    assert len(m['entries'])==3
    for e in m['entries']:e['role']='template' if e['asset_id']==a['id'] else ('front' if e['asset_id']==b['id'] else 'back')
    payload={'expected_revision':m['revision'],'entries':m['entries'],'pairing_mode':'cartesian','pairs':[]}
    saved=await ctx['client'].put(url,headers=ctx['headers'],json=payload)
    assert saved.status_code==200,saved.text
    assert len(saved.json()['garments'])==1 and saved.json()['combination_count']==1
    stale=await ctx['client'].put(url,headers=ctx['headers'],json=payload)
    assert stale.status_code==409
    restored=(await ctx['client'].get(url,headers=ctx['headers'])).json()
    assert restored==saved.json()
    payload['expected_revision']=restored['revision'];payload['entries'][0]['asset_id']=str(uuid4())
    assert (await ctx['client'].put(url,headers=ctx['headers'],json=payload)).status_code==422
    viewer=(await ctx['client'].post('/api/v1/auth/login',json={'account':'first-viewer','password':'viewer-password'})).json()
    assert (await ctx['client'].get(url,headers={'Authorization':'Bearer '+viewer['access_token']})).status_code in (403,404)


async def test_plain_language_batch_with_front_back_font_outputs_versions_and_zip(autonomous_context,monkeypatch):
    import tests.company_agent_support as support
    original=support.mock_understanding
    def understand(filename):
        data=original(filename)
        if filename.startswith('template'):data['view']='back' if 'back' in filename else 'front'
        else:
            role=filename.split('-')[-1].split('.')[0]
            data.update(role=role,view=role if role in {'front','back','detail'} else 'auto')
        return data
    monkeypatch.setattr(support,'mock_understanding',understand)
    ctx=autonomous_context;assets={};ids=[]
    for name in ('template-front.png','template-back.png','NF0000532-front.png','NF0000532-back.png','NF0000532-font.png'):
        image,a=await attach(ctx,name);assets[name]=image['id'];ids.append(a['id'])
    run=await send(ctx,'帮我把这些衣服全部套到这几个模板上，不用样图',ids)
    assert run['status']=='waiting_jobs' and len(run['jobs'])==5,run
    generated=await finish(ctx,run)
    assert generated['status']=='waiting_jobs',generated
    image_jobs=[j for j in generated['jobs'] if j['capability']!='text_generation']
    assert len(image_jobs)==2
    async with ctx['session_factory']() as db:
        for info in image_jobs:
            job=await db.get(Job,info['id']);meta=job.input_json['metadata']
            view='back' if meta['template_name']=='template-back.png' else 'front'
            assert job.input_json['reference_asset_ids']==[assets['template-'+view+'.png'],assets['NF0000532-'+view+'.png'],assets['NF0000532-font.png']]
            assert len(meta['combination_id'])==32
            assert '实际上传顺序' in job.input_json['prompt']
    completed=await finish(ctx,generated)
    assert len(completed['outputs'])==2 and all(o['batch_tryon']['garment_id'] for o in completed['outputs'])
    assert all(o['review_status']=='pending' for o in completed['outputs'])
    detail=(await ctx['client'].get('/api/v1/agent/conversations/'+ctx['chat']['id'],headers=ctx['headers'])).json()
    p=detail['production_plans'][0]
    assert p['combination_count']==2 and len(p['garment_rules'])==1
    url=f"/api/v1/agent/conversations/{ctx['chat']['id']}/production-plans/{p['id']}/archive"
    archive=await ctx['client'].get(url,headers=ctx['headers'])
    assert archive.status_code==200,archive.text
    import zipfile,io
    with zipfile.ZipFile(io.BytesIO(archive.content)) as z:
        assert z.testzip() is None and len(z.namelist())==2
    gid=next(iter(p['garment_rules']))
    assert (await ctx['client'].get(url+'?garment_id='+gid,headers=ctx['headers'])).status_code==200
    assert (await ctx['client'].get(url+'?garment_id='+str(uuid4()),headers=ctx['headers'])).status_code==404
    ctx['settings'].agent_control_planner='existing_text'
    ctx['mock_decision']={'summary':'只调整第二个模板的结果','skills':['batch-production'],'steps':[{'capability_id':'business.followup_batch_results',
        'arguments':{'plan_id':p['id'],'expected_revision':p['revision'],'template_number':2,'action':'adjust','instruction':'背景适当提亮，衣服设计不变'},'reason':'用户明确指定模板范围'}]}
    followup=await finish(ctx,await send(ctx,'第二个模板的所有结果偏暗，帮我调整'))
    assert len([j for j in followup['jobs'] if j['capability']!='text_generation'])==1,followup
    final=await finish(ctx,followup)
    assert len(final['outputs'])==1 and final['outputs'][0]['version']==2,final
    assert final['outputs'][0]['parent_output_id'] in {o['id'] for o in completed['outputs']}


async def test_failed_combination_only_retry_keeps_successful_jobs(autonomous_context,monkeypatch):
    from app.providers.base import ProviderError
    ctx=autonomous_context;ids=[]
    for name in ('template.png','garment-a.png','garment-b.png'):ids.append((await attach(ctx,name))[1]['id'])
    original=ctx['worker'].get_provider_adapter
    fail=[True]
    class FaultProvider:
        async def execute(self,**kwargs):
            if fail[0] and kwargs['capability']!='text_generation' and (kwargs['payload'].get('metadata') or {}).get('garment_filename')=='garment-b.png':
                raise ProviderError('provider.invalid_image','Mock损坏结果，非真实请求')
            return await original('mock',ctx['settings']).execute(**kwargs)
    monkeypatch.setattr(ctx['worker'],'get_provider_adapter',lambda *a:FaultProvider())
    submitted=await finish(ctx,await send(ctx,'帮我把这些衣服全部套到这几个模板上，不用样图',ids))
    result=await finish(ctx,submitted)
    assert result['status']=='failed' and len(result['outputs'])==1,result
    successful=result['outputs'][0]['job_id']
    detail=(await ctx['client'].get('/api/v1/agent/conversations/'+ctx['chat']['id'],headers=ctx['headers'])).json();p=detail['production_plans'][0]
    fail[0]=False;ctx['settings'].agent_control_planner='existing_text'
    ctx['mock_decision']={'summary':'只重试失败组合','skills':['batch-production'],'steps':[{'capability_id':'business.followup_batch_results',
        'arguments':{'plan_id':p['id'],'expected_revision':p['revision'],'action':'retry_failed'},'reason':'不重做成功项'}]}
    retry=await finish(ctx,await send(ctx,'只重试失败的组合，不要重做成功的'))
    image_jobs=[j for j in retry['jobs'] if j['capability']!='text_generation']
    assert len(image_jobs)==1 and image_jobs[0]['id']!=successful,(retry['status'],retry.get('error_code'),retry['plan'],retry.get('result'))
    final=await finish(ctx,retry)
    assert final['status']=='completed' and len(final['outputs'])==1
    async with ctx['session_factory']() as db:assert (await db.get(Job,successful)).status=='succeeded'


@pytest.mark.skipif(os.getenv('AGENT_BATCH_BROWSER_PROBE')!='1',reason='Opt-in isolated headless browser only')
async def test_isolated_browser_batch(autonomous_context,tmp_path):
    import asyncio
    from pathlib import Path
    import uvicorn
    from fastapi.responses import FileResponse
    from playwright.async_api import async_playwright
    from tests.test_batch_tryon_workflow import PNG
    ctx=autonomous_context
    ctx['settings'].agent_auto_submissions_per_minute=30
    gate=asyncio.Lock()
    dist=Path(__file__).resolve().parents[2]/'dist'
    @ctx['app'].get('/{path:path}',include_in_schema=False)
    async def frontend(path:str):
        target=(dist/path).resolve()
        return FileResponse(target if target.is_relative_to(dist) and target.is_file() else dist/'index.html')
    server=uvicorn.Server(uvicorn.Config(ctx['app'],host='127.0.0.1',port=18481,log_level='error'))
    serving=asyncio.create_task(server.serve())
    stop=asyncio.Event()
    async def worker():
        while not stop.is_set():
            async with gate:
                async with ctx['session_factory']() as db:
                    ids=list((await db.scalars(select(Job.id).where(Job.status=='queued'))).all())
                for jid in ids:await ctx['worker']._execute_job(jid)
            await asyncio.sleep(.2)
    working=asyncio.create_task(worker())
    root=Path(__file__).resolve().parents[2]/'diagnostics'/'agent-batch-product'
    root.mkdir(parents=True,exist_ok=True)
    try:
        while not server.started:await asyncio.sleep(.1)
        async with async_playwright() as p:
            browser=await p.chromium.launch(channel='msedge',headless=True,args=['--no-proxy-server'])
            page=await browser.new_page(viewport={'width':1440,'height':1000})
            await page.goto('http://127.0.0.1:18481/login',wait_until='domcontentloaded')
            await page.get_by_placeholder('请输入账号').fill('first-admin')
            await page.get_by_placeholder('请输入密码').fill('correct-password')
            await page.get_by_role('button',name='登录',exact=True).click()
            # Do not abort the asynchronous login response by navigating immediately.
            await page.wait_for_url(lambda url:'/login' not in url,wait_until='domcontentloaded')
            await page.goto('http://127.0.0.1:18481/workspaces/agent-control',wait_until='domcontentloaded')
            await page.get_by_role('button').filter(has_text='模板与服装智能组合').click()
            await page.get_by_role('group',name='上传模板图卡片',exact=True).wait_for(timeout=30000)
            await page.get_by_label('当前专业模块',exact=True).select_option('amazon_aplus')
            from playwright.async_api import expect
            await expect(page.get_by_label('当前专业模块',exact=True)).to_have_value('amazon_aplus')
            await page.reload(wait_until='domcontentloaded')
            await expect(page.get_by_label('当前专业模块',exact=True)).to_have_value('amazon_aplus')
            await page.get_by_label('当前专业模块',exact=True).select_option('batch_tryon')
            await expect(page.get_by_label('当前专业模块',exact=True)).to_have_value('batch_tryon')
            async with page.expect_file_chooser() as choosing:
                await page.get_by_role('button',name='自动识别',exact=True).click()
                await page.get_by_role('dialog',name='导入混合素材方式',exact=True).get_by_role('button',name='选择图片',exact=True).click()
            chooser=await choosing.value
            await chooser.set_files([{'name':n,'mimeType':'image/png','buffer':PNG} for n in ('template.png','garment.png')])
            from playwright.async_api import expect
            await expect(page.locator('select[aria-label$=" 图片角色"]')).to_have_count(2)
            await page.get_by_label('template.png 图片角色',exact=True).select_option('template')
            await page.get_by_label('garment.png 图片角色',exact=True).select_option('garment')
            await page.get_by_role('button',name='整理素材与关联').click()
            await page.get_by_role('button',name='正背面裁剪与绑定',exact=True).click()
            await page.get_by_role('button',name='批量预览并应用',exact=True).click()
            await page.get_by_role('button',name='确认并保存参考图',exact=True).click()
            await page.get_by_role('heading',name='聊天服装参考处理',exact=True).wait_for(state='hidden',timeout=30000)
            await page.get_by_role('button',name='发送',exact=True).wait_for(state='visible')
            await page.get_by_role('textbox',name='发送创作需求').fill('帮我把这些衣服全部套到这几个模板上')
            await page.get_by_role('button',name='发送',exact=True).click()
            try:
                await page.get_by_label('对话图片结果',exact=True).wait_for(timeout=45000)
            except Exception:
                await page.screenshot(path=str(root/'failure.png'),full_page=True)
                print('ISOLATED_BROWSER_VISIBLE_TEXT:',(await page.locator('body').inner_text())[-2500:])
                raise
            await page.get_by_role('button',name='保存素材关联',exact=True).wait_for()
            # Existing preprocessing is available inside the chat, not a navigation.
            await page.get_by_role('button',name='正背面裁剪与绑定',exact=True).wait_for()
            await page.get_by_role('button',name='通过',exact=True).click()
            await page.get_by_role('button',name='已通过',exact=True).wait_for(timeout=30000)
            await page.get_by_role('button',name='批量生成剩余 1 张',exact=True).click()
            await page.get_by_role('button',name='本批已全部提交',exact=True).wait_for(timeout=30000)
            await expect(page.get_by_label('对话图片结果',exact=True)).to_have_count(2,timeout=30000)
            await page.screenshot(path=str(root/'desktop.png'),full_page=True)
            assert await page.locator('body').evaluate('(el)=>el.scrollWidth<=window.innerWidth')
            await page.reload(wait_until='domcontentloaded')
            await expect(page.get_by_label('对话图片结果',exact=True)).to_have_count(2,timeout=30000)
            await page.wait_for_function("Array.from(document.images).some(i=>i.alt==='样图 1'&&i.complete&&i.naturalWidth>0)")
            async with page.expect_download() as downloaded:
                await page.get_by_role('button',name='导出本批结果',exact=True).click()
            artifact=await downloaded.value
            await artifact.save_as(str(root/'browser-results.zip'))
            import zipfile
            with zipfile.ZipFile(root/'browser-results.zip') as archive:
                assert archive.testzip() is None and len(archive.namelist())==1
            from app.models.content import Asset
            async with ctx['session_factory']() as db:
                images=(await db.scalars(select(Job).where(Job.operation_code=='batch_tryon.generate'))).all()
                assert len(images)==2
                for job in images:
                    reference=await db.get(Asset,job.input_json['reference_asset_ids'][1])
                    # Chat uploads are product_reference; the existing derive endpoint
                    # intentionally preserves that category. Source/view identify the crop.
                    assert reference.source_asset_id and reference.metadata_json['garment_view']=='front'
                    assert (await db.get(Asset,reference.source_asset_id)).filename=='garment.png'
            await page.set_viewport_size({'width':390,'height':844})
            await page.screenshot(path=str(root/'mobile.png'),full_page=True)
            assert await page.locator('body').evaluate('(el)=>el.scrollWidth<=window.innerWidth')
            await browser.close()
    finally:
        stop.set();server.should_exit=True
        await working;await serving
