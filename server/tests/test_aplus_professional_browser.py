"""Real React/API browser, fake accounts and Mock Provider in an isolated DB."""
import asyncio,json,os
from pathlib import Path
from zipfile import ZipFile
import pytest
from sqlalchemy import select
from app.models.tasks import Job
from tests.test_agent_control import agent_context
from tests.test_agent_chat_v2 import chat_context
from tests.test_agent_second_round import second_context
from tests.test_agent_autonomous import autonomous_context
from tests.test_amazon_advisor import advisor,model_step
from tests.test_aplus_professional import pro,professional_brief
from tests.test_batch_tryon_workflow import PNG

@pytest.mark.skipif(os.getenv('APLUS_BROWSER')!='1',reason='Explicit isolated professional browser acceptance')
async def test_professional_aplus_browser(pro):
    import uvicorn
    from fastapi.responses import FileResponse
    from playwright.async_api import async_playwright,expect
    ctx=pro;dist=Path(__file__).resolve().parents[2]/'dist';gate=asyncio.Lock()
    @ctx['app'].get('/{path:path}',include_in_schema=False)
    async def frontend(path:str):
        target=(dist/path).resolve()
        return FileResponse(target if target.is_relative_to(dist) and target.is_file() else dist/'index.html')
    class Serial:
        async def __call__(self,scope,receive,send):
            if scope['type']=='http' and not scope.get('path','').endswith('/stream'):
                async with gate:await ctx['app'](scope,receive,send)
            else:await ctx['app'](scope,receive,send)
    server=uvicorn.Server(uvicorn.Config(Serial(),host='127.0.0.1',port=18486,log_level='error'))
    serving=asyncio.create_task(server.serve());root=dist.parent/'diagnostics'/'aplus-professional-browser';root.mkdir(parents=True,exist_ok=True)
    async def images():
        async with gate:
            async with ctx['session_factory']() as db:return list((await db.scalars(select(Job).where(Job.capability!='text_generation'))).all())
    try:
        while not server.started:await asyncio.sleep(.1)
        async with async_playwright() as p:
            browser=await p.chromium.launch(channel='msedge',headless=True,args=['--no-proxy-server'])
            page=await browser.new_page(viewport={'width':1440,'height':1000})
            await page.route('**/*',lambda r:r.continue_() if r.request.url.startswith('http://127.0.0.1:18486/') else r.abort())
            await page.goto('http://127.0.0.1:18486/login',wait_until='networkidle')
            await page.get_by_placeholder('请输入账号').fill('first-admin');await page.get_by_placeholder('请输入密码').fill('correct-password')
            await page.get_by_role('button',name='登录',exact=True).click();await page.wait_for_url(lambda u:'/login' not in u)
            await page.goto('http://127.0.0.1:18486/workspaces/agent-control',wait_until='networkidle')
            await page.get_by_role('combobox',name='当前专业模块').select_option('auto')
            await page.locator('input[type=file]').first.set_input_files({'name':'professional-reference.png','mimeType':'image/png','buffer':PNG})
            await page.get_by_role('textbox',name='发送创作需求').fill('帮我做一套图')
            await expect(page.get_by_role('button',name='发送',exact=True)).to_be_enabled()
            await page.get_by_role('button',name='发送',exact=True).click()
            await expect(page.get_by_text('你想做 Amazon A+ 还是 Listing 附图？有参考的竞品 ASIN 也可以一起发我。',exact=True).first).to_be_visible(timeout=15000)
            assert not await images()
            await page.screenshot(path=str(root/'clarification-desktop.png'))
            await page.get_by_role('textbox',name='发送创作需求').fill('要A+，本款支持定制姓名与号码，突出礼品和穿着场景，直接做')
            await page.get_by_role('button',name='发送',exact=True).click()
            for _ in range(200):
                async with gate:
                    async with ctx['session_factory']() as db:
                        job=await db.scalar(select(Job).where(Job.capability=='text_generation',Job.status=='queued'))
                        if job:
                            assets=json.loads(job.input_json['user_prompt'])['context']['assets']
                            aid=next(a['id'] for a in assets if a['filename']=='professional-reference.png')
                            ctx['mock_decision']=model_step('business.save_aplus_plan',{'brief':professional_brief(aid)})
                    if job:await ctx['worker']._execute_job(job.id)
                if len(await images())==7:break
                await asyncio.sleep(.1)
            jobs=await images();assert len(jobs)==7
            async with gate:await ctx['worker']._execute_job(jobs[0].id)
            progress=page.get_by_label('图片生成进度').last
            await expect(progress).to_contain_text('成功 1/7 张',timeout=20000)
            await page.reload(wait_until='networkidle');await expect(progress).to_contain_text('成功 1/7 张',timeout=15000)
            async with gate:
                for j in jobs[1:]:await ctx['worker']._execute_job(j.id)
            await expect(progress).to_contain_text('成功 7/7 张',timeout=20000)
            card=page.get_by_label('A+运营需求卡');await expect(card).to_contain_text('5 个模块 · 7 张素材')
            await card.get_by_role('button',name='双端排版预览').click()
            dialog=page.get_by_role('dialog',name='A+双端排版预览')
            await expect(dialog.locator('article')).to_have_count(5)
            await expect(dialog.locator('[data-layout="three_columns"] img')).to_have_count(3)
            await page.screenshot(path=str(root/'module-composition-desktop.png'))
            await page.set_viewport_size({'width':390,'height':844});await dialog.get_by_role('button',name='手机预览').click()
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            await page.screenshot(path=str(root/'module-composition-mobile.png'))
            await dialog.get_by_role('button',name='关闭预览').click()
            async with page.expect_download() as download:await card.get_by_role('button',name='下载整套 ZIP').click()
            target=await (await download.value).path()
            with ZipFile(target) as z:
                assert z.testzip() is None
                manifest=json.loads(z.read('manifest.json'));assert len(manifest['outputs'])==7 and not manifest['module_slots_without_output']
            await browser.close()
    finally:server.should_exit=True;await serving
