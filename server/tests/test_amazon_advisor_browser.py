"""Opt-in actual React/API browser acceptance, isolated DB and Mock Worker."""
import asyncio
import json
import os
from pathlib import Path
from zipfile import ZipFile
import pytest
from sqlalchemy import select
from app.models.tasks import Job
from tests.test_agent_control import agent_context
from tests.test_agent_chat_v2 import chat_context
from tests.test_agent_second_round import second_context
from tests.test_agent_autonomous import autonomous_context
from tests.test_amazon_advisor import advisor, suite, model_step
from tests.test_batch_tryon_workflow import PNG


@pytest.mark.skipif(os.getenv('ADVISOR_BROWSER')!='1',reason='Explicit isolated browser acceptance')
async def test_isolated_browser_batch(advisor,tmp_path):
    import uvicorn
    from fastapi.responses import FileResponse
    from playwright.async_api import async_playwright,expect
    ctx=advisor;ctx['settings'].agent_auto_submissions_per_minute=30
    dist=Path(__file__).resolve().parents[2]/'dist';gate=asyncio.Lock();stop=asyncio.Event()
    @ctx['app'].get('/{path:path}',include_in_schema=False)
    async def frontend(path:str):
        target=(dist/path).resolve()
        return FileResponse(target if target.is_relative_to(dist) and target.is_file() else dist/'index.html')
    class Serial:
        async def __call__(self,scope,receive,send):
            if scope['type']=='http':
                async with gate:await ctx['app'](scope,receive,send)
            else:await ctx['app'](scope,receive,send)
    server=uvicorn.Server(uvicorn.Config(Serial(),host='127.0.0.1',port=18484,log_level='error'))
    async def work():
        while not stop.is_set():
            async with gate:
                async with ctx['session_factory']() as db:ids=list((await db.scalars(select(Job.id).where(Job.status=='queued'))).all())
                for jid in ids:
                    async with ctx['session_factory']() as db:
                        job=await db.get(Job,jid)
                        if job.capability=='text_generation':
                            context=json.loads(job.input_json['user_prompt'])['context']
                            ctx['product']={'id':next(a['id'] for a in context['assets'] if a['filename']=='browser-custom-jersey.png')}
                            p=suite(ctx)
                            ctx['mock_decision']=model_step('business.save_aplus_plan',{'plan':p.model_dump(mode='json')})
                    await ctx['worker']._execute_job(jid)
            await asyncio.sleep(.2)
    serving=asyncio.create_task(server.serve());working=asyncio.create_task(work())
    output=dist.parent/'diagnostics'/'amazon-advisor-browser';output.mkdir(parents=True,exist_ok=True)
    try:
        while not server.started:await asyncio.sleep(.1)
        async with async_playwright() as p:
            browser=await p.chromium.launch(channel='msedge',headless=True,args=['--no-proxy-server'])
            page=await browser.new_page(viewport={'width':1440,'height':1000})
            await page.route('**/*',lambda route:route.continue_() if route.request.url.startswith('http://127.0.0.1:18484/') else route.abort())
            await page.goto('http://127.0.0.1:18484/login',wait_until='networkidle')
            await page.get_by_placeholder('请输入账号').fill('first-admin')
            await page.get_by_placeholder('请输入密码').fill('correct-password')
            await page.get_by_role('button',name='登录',exact=True).click()
            await page.wait_for_url(lambda url:'/login' not in url)
            await page.goto('http://127.0.0.1:18484/workspaces/agent-control',wait_until='networkidle')
            await page.locator('input[type=file]').first.set_input_files({'name':'browser-custom-jersey.png','mimeType':'image/png','buffer':PNG})
            await expect(page.get_by_role('combobox',name='当前专业模块')).to_be_enabled()
            await page.get_by_role('combobox',name='当前专业模块').select_option('listing_images')
            composer=page.locator('textarea').first
            await composer.fill('给这款球衣设计一整套亚马逊附图，重点定制、礼品和日常穿着')
            await expect(page.get_by_role('button',name='发送',exact=True)).to_be_enabled()
            await page.get_by_role('button',name='发送',exact=True).click()
            card=page.get_by_label('A+运营需求卡')
            await expect(card).to_contain_text('Listing 图片方案',timeout=45000)
            await expect(card.get_by_role('button',name='确认方案，生成所选 4 张')).to_be_enabled()
            await page.screenshot(path=str(output/'plan-desktop.png'),full_page=True)
            await card.get_by_role('button',name='确认方案，生成所选 4 张').click()
            await expect(card.get_by_text('版本 1 · 待质量审核')).to_have_count(4,timeout=45000)
            await page.reload(wait_until='networkidle')
            await expect(card.get_by_text('版本 1 · 待质量审核')).to_have_count(4,timeout=45000)
            async with page.expect_download() as download:
                await card.get_by_role('button',name='下载整套 ZIP').click()
            zip_path=await (await download.value).path()
            with ZipFile(zip_path) as z:
                assert z.testzip() is None
                data=json.loads(z.read('manifest.json'))
                assert len(data['outputs'])==4 and not data['modules_without_output']
            await page.screenshot(path=str(output/'results-desktop.png'),full_page=True)
            await page.set_viewport_size({'width':390,'height':844})
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            await page.screenshot(path=str(output/'results-mobile.png'),full_page=True)
            await browser.close()
    finally:
        stop.set();server.should_exit=True
        await working;await serving
