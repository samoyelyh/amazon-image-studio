"""Capability plans are model proposals, never executable policy.

The real planner uses the existing separately-confirmed text Job. Mock is an
explicit test double over the same selected catalog, not a claimed AI agent.
"""
import re
from app.agents.capabilities.contracts import CapabilityDecision, PlannedStep


class Planner:
    @staticmethod
    def simulate(goal, selection, observations, *, has_parent=False, business_context=None):
        tools = {t["id"]: t for t in selection["tools"]}
        skills = [s["id"] for s in selection["skills"]][:3]
        if observations:
            failures = [o for o in observations if o["status"] != "succeeded"]
            if observations[-1]["status"] == "succeeded":
                plans=(business_context or {}).get('production_plans',[])
                if observations[-1]['capability_id']=='business.analyze_assets' and plans and 'business.generate_tryon' in tools:
                    from app.agents.execution_policy import wants_sample_review
                    plan=plans[0]
                    return CapabilityDecision(summary='使用已分析清单提交原生批量换衣任务。',skills=skills,steps=[PlannedStep(
                        capability_id='business.generate_tryon',arguments={'plan_id':plan['id'],'expected_revision':plan['revision'],
                            'stage':'validation' if plan.get('sample_review_required') or wants_sample_review(goal) else 'production'},reason='Mock验证原生业务链，不代表真实模型自主规划')])
                search = next((o for o in observations if o["capability_id"] == "business.search_my_assets" and o["status"] == "succeeded"), None)
                if search and "生成" in goal and "business.create_images" in tools:
                    found = search.get("result", {}).get("items", [])
                    if not found:
                        return CapabilityDecision(summary="没有找到目标素材，未发送生图请求。", skills=skills, question="需要换个关键词，还是直接上传参考图片？")
                    return CapabilityDecision(summary="已找到本人素材，请确认使用该参考图创建图片。", skills=skills,
                        steps=[PlannedStep(capability_id="business.create_images", arguments={"instruction": goal,
                            "reference_asset_ids": [found[0]["asset_id"]]}, reason="复用本次查询实际返回的参考图，提交前单独确认费用")])
                return CapabilityDecision(summary="已完成获准工具查询；工具结果及此前失败均保留在本条记录中。", skills=skills, done=True)
            # Safe, bounded alternative comes only from this run's currently selected catalog.
            if failures:
                used = {o["capability_id"] for o in observations}
                fallback = next((k for k, t in tools.items() if k not in used and t["source"] == "mcp"), None)
                if fallback:
                    return CapabilityDecision(summary="首个工具不可用，尝试另一项已授权的公开查询能力。", skills=skills,
                        steps=[PlannedStep(capability_id=fallback, arguments={"query": goal[:100]}, reason="获准只读替代工具")])
                return CapabilityDecision(summary="工具未能完成查询；已记录脱敏原因，未编造结果。", skills=skills, done=True)
            return CapabilityDecision(summary="已完成所选工具查询，结果可在本条消息的工具记录中查看。", skills=skills, done=True)
        steps = []
        if any(w in goal for w in ("搜索", "查找")) and "business.search_my_assets" in tools:
            query = re.split(r"[，,]|并(?:生成|制作)", re.sub(r".*?(?:搜索|查找)(?:我的)?(?:素材)?[：:\s]*", "", goal))[0].strip()[:100]
            steps.append(PlannedStep(capability_id="business.search_my_assets", arguments={"query": query}, reason="先查询本人素材库"))
            if "当前" in goal and "business.current_context" in tools:
                steps.append(PlannedStep(capability_id="business.current_context", reason="核对本会话素材与版本"))
        elif any(w in goal for w in ("队列", "排队")) and "business.read_shared_queue" in tools:
            steps.append(PlannedStep(capability_id="business.read_shared_queue", reason="读取实际共享队列摘要"))
        elif any(w in goal for w in ("进度", "任务状态")) and "business.current_jobs" in tools:
            steps.append(PlannedStep(capability_id="business.current_jobs", reason="读取当前会话实际任务，不猜测任务ID"))
        elif (any(w in goal for w in ("套图", "个模板", "件服装", "件衣服",'换衣','衣服全部套','衣服套到')) or len((business_context or {}).get('assets',[]))>10) and "business.analyze_assets" in tools:
            assets = (business_context or {}).get("assets", [])
            if 'business.analyze_assets' in tools:
                return CapabilityDecision(summary='先逐图理解素材，确认规则后再验证样图。',skills=skills,steps=[
                    PlannedStep(capability_id='business.analyze_assets',arguments={'asset_ids':list(dict.fromkeys(a['id'] for a in assets))},reason='识别角色并复用分层规则，不直接提交整批图片')]) if assets else CapabilityDecision(summary='上传模板和服装后开始。',skills=skills,steps=[PlannedStep(capability_id='business.guide_batch_inputs',reason='Mock上传引导')])
            templates = list(dict.fromkeys(a["id"] for a in assets if a["role"] == "template"))
            garments = list(dict.fromkeys(a["id"] for a in assets if a["role"] == "garment"))
            if not templates or not garments or any(a["role"] in {"font", "front", "back", "detail"} for a in assets):
                return CapabilityDecision(summary="需要确认模板/服装角色及正背字体映射，尚未提交生产任务。", question="哪些素材分别是模板、服装及对应参考？", skills=skills)
            steps.append(PlannedStep(capability_id="business.prepare_tryon_workspace", arguments={
                "template_asset_ids": templates, "garment_asset_ids": garments}, reason="关联到原B生产工作台继续规则与样图确认"))
        elif any(w in goal for w in ("生成", "修改", "换成", "修一下")) and "business.create_images" in tools:
            count = re.search(r"生成([1-9])张", goal)
            ordinal = re.search(r"第([1-9])张", goal)
            steps.append(PlannedStep(capability_id="business.create_images", arguments={"instruction": goal,
                "count": int(count[1]) if count else 1, "reference_number": int(ordinal[1]) if ordinal else None,
                "edit": has_parent or bool(ordinal) or any(w in goal for w in ("修改", "换成", "修一下"))}, reason="简单需求直接使用原图片工具"))
        else:
            candidate = next((t for t in selection["tools"] if t["source"] == "mcp"), None)
            if candidate:
                steps.append(PlannedStep(capability_id=candidate["id"], arguments={"query": goal[:100]}, reason="选择匹配任务的获准外部查询工具"))
        if not steps:
            return CapabilityDecision(summary="当前已授权的能力目录不能完成该目标，未伪造工具或结果。", skills=skills,
                question="请提供必要素材，或请管理员登记所需能力。")
        return CapabilityDecision(summary="根据本次目标选择能力并逐步执行。", skills=skills, steps=steps)


class Replanner(Planner):
    """Same constrained contract, now provided with bounded observations/failures."""
