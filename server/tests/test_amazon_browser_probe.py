"""Explicit opt-in, original UI/API and isolated DB/Mock Worker. Never production."""
import os
import pytest
from app.agents.capabilities.planner import Planner
from app.agents.capabilities.contracts import CapabilityDecision, PlannedStep
from tests.test_agent_control import agent_context
from tests.test_agent_chat_v2 import chat_context
from tests.test_agent_capabilities import dynamic_context
from tests.test_agent_amazon import amazon_context,sample_plan

@pytest.mark.skipif(os.getenv('AMAZON_BROWSER_PROBE')!='1',reason='Explicit isolated browser probe only')
async def test_amazon_browser(amazon_context,monkeypatch):
    ctx=amazon_context
    def mock_plan(goal,selection,observations,**kwargs):
        if observations:return CapabilityDecision(summary='Mock：已读取上下文。',done=True)
        assets=(kwargs.get('business_context') or {}).get('assets',[])
        if not assets:return CapabilityDecision(summary='请上传产品图。',question='请先上传产品图。')
        return CapabilityDecision(summary='Mock方案：根据提供的商品图片准备A+模块，未进行市场调研。',skills=['amazon-aplus-planner'],
            steps=[PlannedStep(capability_id='business.save_aplus_plan',arguments={'plan':sample_plan(assets[-1]['id']).model_dump(mode='json')},reason='已有资料，不额外查询')])
    monkeypatch.setattr(Planner,'simulate',mock_plan)
    from tests.test_agent_chat_v2 import test_browser_probe
    await test_browser_probe(ctx,monkeypatch)
