"""Actual React/API polling, refresh and failed-only retry; isolated Mock Worker."""
import asyncio
import os,json
from pathlib import Path
import pytest
from sqlalchemy import select
from app.models.tasks import Job
from tests.test_agent_control import agent_context
from tests.test_agent_chat_v2 import chat_context
from tests.test_agent_second_round import second_context
from tests.test_agent_autonomous import autonomous_context
from tests.test_amazon_advisor import advisor,suite,model_step
from tests.test_batch_tryon_workflow import PNG


@pytest.mark.skipif(os.getenv('ADVISOR_BROWSER')!='1',reason='Explicit isolated browser acceptance')
async def test_progress_partial_refresh_failure_retry_mobile(advisor):
    import uvicorn
    from fastapi.responses import FileResponse
    from playwright.async_api import async_playwright,expect
    ctx=advisor;dist=Path(__file__).resolve().parents[2]/'dist';gate=asyncio.Lock()
    ctx['mock_decision']=model_step('business.save_aplus_plan',{'plan':suite(ctx).model_dump(mode='json')})
    @ctx['app'].get('/{path:path}',include_in_schema=False)
    async def frontend(path:str):
        target=(dist/path).resolve()
        return FileResponse(target if target.is_relative_to(dist) and target.is_file() else dist/'index.html')
    class Serial:
        async def __call__(self,scope,receive,send):
            if scope['type']=='http' and not scope.get('path','').endswith('/stream'):
                async with gate:await ctx['app'](scope,receive,send)
            else:await ctx['app'](scope,receive,send)
    server=uvicorn.Server(uvicorn.Config(Serial(),host='127.0.0.1',port=18485,log_level='error'))
    serving=asyncio.create_task(server.serve())
    output=dist.parent/'diagnostics'/'terra-progress-browser';output.mkdir(parents=True,exist_ok=True)
    async def rows():
        async with gate:
            async with ctx['session_factory']() as db:return list((await db.scalars(select(Job).where(Job.capability!='text_generation'))).all())
    try:
        while not server.started:await asyncio.sleep(.1)
        async with async_playwright() as p:
            browser=await p.chromium.launch(channel='msedge',headless=True,args=['--no-proxy-server'])
            page=await browser.new_page(viewport={'width':1440,'height':1000})
            await page.route('**/*',lambda r:r.continue_() if r.request.url.startswith('http://127.0.0.1:18485/') else r.abort())
            await page.goto('http://127.0.0.1:18485/login',wait_until='networkidle')
            await page.get_by_placeholder('请输入账号').fill('first-admin')
            await page.get_by_placeholder('请输入密码').fill('correct-password')
            await page.get_by_role('button',name='登录',exact=True).click()
            await page.wait_for_url(lambda url:'/login' not in url)
            await page.goto('http://127.0.0.1:18485/workspaces/agent-control',wait_until='networkidle')
            await page.locator('input[type=file]').first.set_input_files({'name':'progress-jersey.png','mimeType':'image/png','buffer':PNG})
            await page.get_by_role('combobox',name='当前专业模块').select_option('listing_images')
            await page.locator('textarea').first.fill('给现有球衣素材直接生成一套Listing附图，不用审核方案')
            await page.get_by_role('button',name='发送',exact=True).click()
            for _ in range(200):
                async with gate:
                    async with ctx['session_factory']() as db:
                        jid=await db.scalar(select(Job.id).where(Job.capability=='text_generation',Job.status=='queued'))
                    if jid:
                        async with ctx['session_factory']() as db:
                            job=await db.get(Job,jid)
                            assets=json.loads(job.input_json['user_prompt'])['context']['assets']
                            ctx['product']={'id':next(a['id'] for a in assets if a['filename']=='progress-jersey.png')}
                            ctx['mock_decision']=model_step('business.save_aplus_plan',{'plan':suite(ctx).model_dump(mode='json')})
                        await ctx['worker']._execute_job(jid)
                if len(await rows())==4:break
                await asyncio.sleep(.1)
            jobs=await rows();assert len(jobs)==4
            progress=page.get_by_label('图片生成进度').first
            await expect(progress).to_contain_text('成功 0/4 张',timeout=20000)
            async with gate:
                await ctx['worker']._execute_job(jobs[0].id)
                async with ctx['session_factory']() as db:
                    j=await db.get(Job,jobs[1].id);j.status='running';await db.commit()
            await expect(progress.get_by_role('progressbar')).to_have_attribute('aria-valuenow','25',timeout=20000)
            await expect(progress).to_contain_text('生成中：1')
            await progress.scroll_into_view_if_needed()
            await page.screenshot(path=str(output/'partial-desktop.png'))
            await page.reload(wait_until='networkidle')
            await expect(progress).to_contain_text('成功 1/4 张',timeout=20000)
            async with gate:
                async with ctx['session_factory']() as db:
                    j=await db.get(Job,jobs[1].id);j.status='failed';j.error_code='provider.rejected';await db.commit()
                for j in jobs[2:]:await ctx['worker']._execute_job(j.id)
            await expect(progress.get_by_role('progressbar')).to_have_attribute('aria-valuenow','100',timeout=20000)
            await expect(progress).to_contain_text('成功 3/4 张')
            await expect(progress).to_contain_text('失败：1')
            await progress.locator('summary').click()
            await expect(progress.get_by_role('button',name='仅重新生成这张')).to_have_count(1)
            await progress.get_by_role('button',name='仅重新生成这张').click()
            for _ in range(100):
                current=await rows()
                if len(current)==5:break
                await asyncio.sleep(.1)
            assert len(current)==5
            new=next(j for j in current if j.id not in {x.id for x in jobs})
            async with gate:await ctx['worker']._execute_job(new.id)
            await expect(page.get_by_label('图片生成进度').last).to_contain_text('成功 1/1 张',timeout=20000)
            await expect(progress).to_contain_text('已创建单张重试')
            await page.reload(wait_until='networkidle')
            await expect(page.get_by_label('图片生成进度')).to_have_count(2,timeout=20000)
            await page.screenshot(path=str(output/'retried-desktop.png'))
            await page.set_viewport_size({'width':390,'height':844})
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            await page.get_by_label('图片生成进度').last.scroll_into_view_if_needed()
            await page.screenshot(path=str(output/'retried-mobile.png'))
            await browser.close()
    finally:
        server.should_exit=True;await serving
