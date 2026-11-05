"""Opt-in browser import acceptance, private DB and Mock Worker only."""
import os
import asyncio
import json
from pathlib import Path
from zipfile import ZipFile
import pytest
from sqlalchemy import select,func
from tests.test_agent_control import agent_context
from tests.test_agent_chat_v2 import chat_context
from tests.test_agent_second_round import second_context
from tests.test_agent_autonomous import autonomous_context
from tests.test_batch_tryon_workflow import PNG
from app.models.tasks import Job
from app.models.content import GeneratedOutput


@pytest.mark.skipif(os.getenv('AGENT_IMPORT_BROWSER_PROBE')!='1',reason='Opt-in private browser + Mock only')
async def test_isolated_browser_batch(autonomous_context,tmp_path):
    import uvicorn
    from fastapi.responses import FileResponse
    from playwright.async_api import async_playwright,expect
    ctx=autonomous_context;ctx['settings'].agent_auto_submissions_per_minute=30
    dist=Path(__file__).resolve().parents[2]/'dist'
    @ctx['app'].get('/{path:path}',include_in_schema=False)
    async def frontend(path:str):
        target=(dist/path).resolve()
        return FileResponse(target if target.is_relative_to(dist) and target.is_file() else dist/'index.html')
    server=uvicorn.Server(uvicorn.Config(ctx['app'],host='127.0.0.1',port=18483,log_level='error'))
    serving=asyncio.create_task(server.serve());stop=asyncio.Event()
    async def work():
        while not stop.is_set():
            async with ctx['session_factory']() as db:ids=list((await db.scalars(select(Job.id).where(Job.status=='queued'))).all())
            for jid in ids:
                async with ctx['session_factory']() as db:job=await db.get(Job,jid)
                if (job.input_json.get('metadata') or {}).get('workflow')=='agent_control':
                    if ctx.get('hold_import_planner'):continue
                    if ctx.get('adaptive_import_planner'):
                        context=json.loads(job.input_json['user_prompt'])['context']
                        prepared=any(o['capability_id']=='business.analyze_assets' and o['status']=='succeeded' for o in context.get('observations',[]))
                        if prepared:
                            plan=context['production_plans'][0]
                            step={'capability_id':'business.generate_tryon','arguments':{'plan_id':plan['id'],'expected_revision':plan['revision'],'stage':'validation'},'reason':'Mock：按已理解的素材验证样图'}
                        else:
                            step={'capability_id':'business.analyze_assets','arguments':{'asset_ids':[a['id'] for a in context['assets']]},'reason':'Mock：先理解最新素材'}
                        ctx['mock_decision']={'summary':'Mock 批量素材与样图准备','skills':['batch-production'],'steps':[step]}
                await ctx['worker']._execute_job(jid)
            await asyncio.sleep(.2)
    working=asyncio.create_task(work())
    root=dist.parent/'diagnostics'/'agent-import';root.mkdir(parents=True,exist_ok=True)
    folder=tmp_path/'服装'/'NF0000532';folder.mkdir(parents=True)
    (folder/'front.png').write_bytes(PNG);(folder/'back.png').write_bytes(PNG)
    archive=tmp_path/'补充服装.zip'
    with ZipFile(archive,'w') as z:
        z.writestr('服装/NF0000533/front.png',PNG);z.writestr('服装/NF0000533/back.png',PNG)
        z.writestr('说明.txt','这是Mock验收，不是实际商品图。')
    try:
        while not server.started:await asyncio.sleep(.1)
        async with async_playwright() as p:
            browser=await p.chromium.launch(channel='msedge',headless=True,args=['--no-proxy-server'])
            page=await browser.new_page(viewport={'width':1440,'height':1000})
            blocked=[]
            async def local_only(route):
                # Isolated acceptance never depends on third-party fonts/services.
                if route.request.url.startswith('http://127.0.0.1:18483/'):
                    await route.continue_()
                else:
                    from urllib.parse import urlsplit
                    address=urlsplit(route.request.url)
                    blocked.append(address.netloc+address.path)
                    await route.abort()
            await page.route('**/*',local_only)
            await page.goto('http://127.0.0.1:18483/login',wait_until='domcontentloaded')
            await page.wait_for_load_state('networkidle')
            await page.get_by_placeholder('请输入账号').fill('first-admin')
            await page.get_by_placeholder('请输入密码').fill('correct-password')
            await expect(page.get_by_placeholder('请输入账号')).to_have_value('first-admin')
            await expect(page.get_by_placeholder('请输入密码')).to_have_value('correct-password')
            try:
                async with page.expect_response(lambda r:'/api/v1/auth/login' in r.url) as login_response:
                    await page.get_by_role('button',name='登录',exact=True).click()
            except Exception:
                print('ISOLATED_BLOCKED_ORIGINS:',blocked)
                print('ISOLATED_LOGIN_TEXT:',await page.locator('body').inner_text())
                raise
            login=await login_response.value
            assert login.status==200,f'Isolated login HTTP {login.status}'
            await page.wait_for_url(lambda url:'/login' not in url,wait_until='domcontentloaded')
            await page.goto('http://127.0.0.1:18483/workspaces/agent-control',wait_until='domcontentloaded')
            # Real-model response shape + original text Job/Worker, but no paid call.
            from tests.test_agent_upload_guide import GUIDE
            ctx['settings'].agent_control_planner='existing_text';ctx['mock_decision']=GUIDE
            await page.get_by_role('button',name='批量换衣',exact=True).click()
            await page.get_by_role('button',name='导入模板',exact=True).wait_for(timeout=30000)
            await expect(page.get_by_label('批量换衣上传引导')).to_be_visible(timeout=30000)
            await expect(page.get_by_label('Agent 工具调度')).to_contain_text('成功')
            await expect(page.get_by_text('agent.capability_missing',exact=False)).to_have_count(0)
            async with ctx['session_factory']() as db:
                assert await db.scalar(select(func.count()).select_from(Job))==1
                assert await db.scalar(select(func.count()).select_from(Job).where(Job.capability!='text_generation'))==0
            await page.screenshot(path=str(root/'upload-guide.png'),full_page=True)
            await page.reload(wait_until='domcontentloaded')
            await expect(page.get_by_label('批量换衣上传引导')).to_be_visible(timeout=30000)
            ctx['hold_import_planner']=True;ctx['adaptive_import_planner']=True
            await page.get_by_role('button',name='自动识别',exact=True).click()
            async with page.expect_file_chooser() as f:
                await page.get_by_role('dialog',name='导入混合素材方式',exact=True).get_by_role('button',name='选择图片',exact=True).click()
            await (await f.value).set_files([{'name':'template.png','mimeType':'image/png','buffer':PNG}])
            await expect(page.get_by_label('批量换衣素材清单')).to_contain_text('1 张图片需要明确角色',timeout=30000)
            async def planner_count():
                async with ctx['session_factory']() as db:
                    return await db.scalar(select(func.count()).select_from(Job).where(Job.operation_code=='listing.plan'))
            for _ in range(100):
                if await planner_count()==2:break
                await asyncio.sleep(.1)
            assert await planner_count()==2
            await page.get_by_role('button',name='导入服装',exact=True).click()
            await page.screenshot(path=str(root/'import-entry.png'),full_page=True)
            async with page.expect_file_chooser() as f:
                await page.get_by_role('button',name='选择文件夹',exact=True).click()
            await (await f.value).set_files(str(folder.parent))
            await expect(page.get_by_label('批量换衣素材清单')).to_contain_text('0 个模板 · 1 件服装',timeout=30000)
            await page.wait_for_load_state('networkidle')
            assert await planner_count()==2  # Guide + one pending planner, not one per import.
            await page.screenshot(path=str(root/'pending-import-coalesced.png'),full_page=True)
            ctx['hold_import_planner']=False
            await expect(page.get_by_label('对话图片结果',exact=True)).to_have_count(1,timeout=60000)
            await expect(page.get_by_label('批量换衣素材清单')).to_contain_text('1 个模板 · 1 件服装')
            await page.reload(wait_until='domcontentloaded')
            await expect(page.get_by_label('对话图片结果',exact=True)).to_have_count(1,timeout=30000)
            await page.wait_for_load_state('networkidle')
            await page.get_by_role('button',name='自动识别',exact=True).click()
            await expect(page.get_by_role('button',name='自动识别',exact=True)).to_have_attribute('aria-expanded','true')
            async with page.expect_file_chooser() as f:
                try:
                    await page.get_by_role('dialog',name='上传服装方式',exact=True).get_by_role('button',name='选择 ZIP',exact=True).click()
                except Exception:
                    print('ISOLATED_IMPORT_TEXT:',await page.locator('body').inner_text())
                    await page.screenshot(path=str(root/'zip-menu-failure.png'),full_page=True,timeout=5000)
                    raise
            await (await f.value).set_files(str(archive))
            await expect(page.get_by_label('批量换衣素材清单')).to_contain_text('1 个模板 · 2 件服装',timeout=30000)
            current=page.get_by_label('聊天内套图规则与样图').filter(has_text='1 个模板 · 2 件服装')
            await expect(current).to_have_count(1,timeout=60000)
            await current.get_by_role('button',name='通过',exact=True).click()
            await current.get_by_role('button',name='已通过',exact=True).wait_for(timeout=30000)
            await current.get_by_role('button',name='批量生成剩余 2 张',exact=True).click()
            results=page.get_by_label('对话图片结果',exact=True).locator('article')
            await expect(results).to_have_count(3,timeout=60000)
            for card in await results.all():
                await card.scroll_into_view_if_needed()
                await expect(card.locator('img')).to_be_visible(timeout=30000)
            await page.screenshot(path=str(root/'desktop.png'),full_page=True)
            assert await page.locator('body').evaluate('(el)=>el.scrollWidth<=window.innerWidth')
            await page.reload(wait_until='domcontentloaded')
            await expect(page.get_by_label('对话图片结果',exact=True).locator('article')).to_have_count(3,timeout=30000)
            await page.set_viewport_size({'width':390,'height':844})
            await expect(page.get_by_role('button',name='导入模板',exact=True)).to_be_enabled(timeout=30000)
            await page.screenshot(path=str(root/'mobile.png'),full_page=True)
            assert await page.locator('body').evaluate('(el)=>el.scrollWidth<=window.innerWidth')
            async with ctx['session_factory']() as db:
                images=list((await db.scalars(select(Job).where(Job.capability!='text_generation'))).all())
                assert len(images)==3 and await db.scalar(select(func.count()).select_from(GeneratedOutput))==3
                assert all(j.input_json['reference_asset_ids'][1] not in j.input_json['reference_asset_ids'][:1] for j in images)
            await browser.close()
    except Exception:
        try:
            if 'page' in locals() and not page.is_closed():
                await page.screenshot(path=str(root/'failure.png'),full_page=True)
                print('IMPORT_BROWSER_TEXT:',(await page.locator('body').inner_text())[-5000:])
        except Exception:pass
        raise
    finally:
        stop.set();server.should_exit=True;await working;await serving


@pytest.mark.skipif(os.getenv('AGENT_ROLE_IMPORT_BROWSER_PROBE')!='1',reason='Opt-in role upload browser check, Mock only')
async def test_separate_cards_preserve_sources_for_images_folders_and_zip(autonomous_context,tmp_path):
    import uvicorn
    from fastapi.responses import FileResponse
    from playwright.async_api import async_playwright,expect
    from tests.test_agent_upload_guide import GUIDE
    ctx=autonomous_context;ctx['settings'].agent_control_planner='existing_text';ctx['mock_decision']=GUIDE
    dist=Path(__file__).resolve().parents[2]/'dist'
    @ctx['app'].get('/{path:path}',include_in_schema=False)
    async def frontend(path:str):
        target=(dist/path).resolve()
        return FileResponse(target if target.is_relative_to(dist) and target.is_file() else dist/'index.html')
    # Match the existing browser harness: this SQLite fixture uses one shared
    # connection. Serialize HTTP/Mock Worker access here, never in production.
    gate=asyncio.Lock()
    class SerialProbe:
        def __init__(self,app):self.app=app
        async def __call__(self,scope,receive,send):
            if scope['type']=='http':
                async with gate:await self.app(scope,receive,send)
            else:await self.app(scope,receive,send)
    server=uvicorn.Server(uvicorn.Config(SerialProbe(ctx['app']),host='127.0.0.1',port=18487,log_level='error'))
    serving=asyncio.create_task(server.serve());stop=asyncio.Event();hold=False
    async def work():
        while not stop.is_set():
            if not hold:
                async with gate:
                    async with ctx['session_factory']() as db:ids=list((await db.scalars(select(Job.id).where(Job.status=='queued'))).all())
                    for jid in ids:await ctx['worker']._execute_job(jid)
            await asyncio.sleep(.1)
    working=asyncio.create_task(work())
    folder=tmp_path/'templates'/'NF0000532';folder.mkdir(parents=True)
    (folder/'front.png').write_bytes(PNG);(folder/'back.png').write_bytes(PNG)
    archive=tmp_path/'garments.zip'
    with ZipFile(archive,'w') as z:z.writestr('NF0000533.png',PNG)
    receipts=[];root=tmp_path/'screenshots';root.mkdir()
    try:
        while not server.started:await asyncio.sleep(.1)
        async with async_playwright() as p:
            browser=await p.chromium.launch(channel='msedge',headless=True,args=['--no-proxy-server'])
            page=await browser.new_page(viewport={'width':1440,'height':1000})
            async def local_only(route):
                if route.request.url.startswith('http://127.0.0.1:18487/'):await route.continue_()
                else:await route.abort()
            await page.route('**/*',local_only)
            def capture(request):
                if request.method=='POST' and request.url.endswith('/attachments'):
                    receipts.append((request.url.split('/conversations/')[1].split('/')[0],request.post_data_json))
            page.on('request',capture)
            await page.goto('http://127.0.0.1:18487/login',wait_until='networkidle')
            await page.get_by_placeholder('请输入账号').fill('first-admin')
            await page.get_by_placeholder('请输入密码').fill('correct-password')
            await page.get_by_role('button',name='登录',exact=True).click()
            await page.wait_for_url(lambda url:'/login' not in url,wait_until='domcontentloaded')
            await page.goto('http://127.0.0.1:18487/workspaces/agent-control',wait_until='domcontentloaded')
            await page.get_by_role('button',name='批量换衣',exact=True).click()
            template=page.get_by_role('group',name='上传模板图卡片',exact=True)
            garment=page.get_by_role('group',name='上传服装卡片',exact=True)
            await expect(template).to_be_visible(timeout=30000);await expect(garment).to_be_visible()
            hold=True  # Import acceptance does not need to execute generation jobs.
            await page.screenshot(path=str(root/'separate-cards-desktop.png'),full_page=True)
            await page.set_viewport_size({'width':390,'height':844})
            await page.get_by_role('button',name='导入模板',exact=True).click()
            await expect(page.get_by_role('dialog',name='上传模板图方式',exact=True)).to_be_visible()
            await page.get_by_role('button',name='导入服装',exact=True).click()
            await expect(page.get_by_role('dialog',name='上传模板图方式',exact=True)).to_have_count(0)
            await expect(page.get_by_role('dialog',name='上传服装方式',exact=True)).to_be_visible()
            assert await page.locator('body').evaluate('(el)=>el.scrollWidth<=window.innerWidth')
            await page.get_by_role('dialog',name='上传服装方式',exact=True).get_by_role('button',name='收起',exact=True).click()
            await page.get_by_label('分别导入模板与服装',exact=True).scroll_into_view_if_needed()
            await expect(template).to_be_in_viewport();await expect(garment).to_be_in_viewport()
            await page.screenshot(path=str(root/'separate-cards-mobile.png'),full_page=True)
            assert await page.locator('body').evaluate('(el)=>el.scrollWidth<=window.innerWidth')
            await page.set_viewport_size({'width':1440,'height':1000})
            async with page.expect_file_chooser() as f:await template.get_by_role('button',name='选择图片',exact=True).click()
            await (await f.value).set_files([{'name':'shirt-front.png','mimeType':'image/png','buffer':PNG}])
            await expect(page.get_by_label('shirt-front.png 图片角色',exact=True)).to_have_value('template')
            async with page.expect_file_chooser() as f:await garment.get_by_role('button',name='选择文件夹',exact=True).click()
            await (await f.value).set_files(str(folder))
            await expect(page.get_by_label('批量换衣素材清单')).to_contain_text('1 个模板 · 1 件服装',timeout=30000)
            await page.get_by_role('button',name='导入服装',exact=True).click()
            dialog=page.get_by_role('dialog',name='上传服装方式',exact=True)
            async with page.expect_file_chooser() as f:await dialog.get_by_role('button',name='选择 ZIP',exact=True).click()
            await (await f.value).set_files(str(archive))
            await expect(page.get_by_label('批量换衣素材清单')).to_contain_text('1 个模板 · 2 件服装',timeout=30000)
            assert [body['import_info']['source'] for _,body in receipts].count('template')==1
            assert [body['import_info']['source'] for _,body in receipts].count('garment')==3
            cid=receipts[0][0]
            async with gate:m=(await ctx['client'].get(f'/api/v1/agent/conversations/{cid}/batch-inputs',headers=ctx['headers'])).json()
            assert len(m['templates'])==1 and len(m['garments'])==2
            assert sorted(e['role'] for e in m['entries'])==['back','front','garment','template']
            assert all(e['manual'] for e in m['entries'])  # Explicit role did not depend on a visual prediction.
            await page.reload(wait_until='domcontentloaded')
            await expect(page.get_by_label('批量换衣素材清单')).to_contain_text('1 个模板 · 2 件服装',timeout=30000)
            async with gate:
                async with ctx['session_factory']() as db:
                    assert await db.scalar(select(func.count()).select_from(Job).where(Job.capability!='text_generation'))==0
            print('ROLE_IMPORT_SCREENSHOTS:',str(root))
            await browser.close()
    finally:
        stop.set();server.should_exit=True;await working;await serving
