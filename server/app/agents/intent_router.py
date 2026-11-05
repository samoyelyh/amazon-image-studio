"""Restricted complexity router. Models classify; server builds and prices actions."""
import re

from app.core.errors import AppError
from app.agents.contracts import AgentPlan, ToolAction, IntentDecision, ChatImageAction
from app.agents.adapters import chat
from app.services.resource_pool_service import resolve_operation_model_code
from app.services.billing_service import estimate_response
from app.agents.execution_policy import explicit_previous_output,approval_question

NUMBERS = {c: i for i, c in enumerate("零一二三四五六七八九十")}
NUMBERS["两"] = 2


def number(value):
    return int(value) if value.isdigit() else NUMBERS.get(value, 1)


def representative_background_edit(content,module='auto'):
    """Only reduce routing previews for an unambiguous per-source background edit.

    Full source IDs remain in the planner context and original pixels still go
    to each edit Job. Composite, comparison and try-on tasks keep all previews.
    """
    if module not in ('auto','image_edit'):return False
    text=re.sub(r'(?:不要|禁止|不得|无需|不)(?:做)?(?:拼图|融合|拼接|合并)','',content)
    return bool('背景' in text and re.search(r'每张|各自|分别|全部|所有|都',text) and re.search(r'替换|更换|换成|改成|改为',text)
        and not re.search(r'拼图|融合|拼接|合并|对比|比较|换衣|换装|套图|套到|替换服装|更换衣服',text))


class IntentRouter:
    @staticmethod
    def simulate(content, has_parent=False):
        """Only a labelled Mock harness, never presented as real model reasoning."""
        ordinal = re.search(r"第([0-9一二三四五六七八九十两]+)张", content)
        count = re.search(r"(?:生成|再来|做)(?:一共)?([0-9一二三四五六七八九十两]+)(?:张|个)", content)
        workflow = "fast"
        if any(w in content for w in ("A+", "A＋", "市场调研", "详情页策划")):
            workflow = "research"
        elif any(w in content for w in ("批量", "件衣服", "件服装", "个模板", "多模板", "套图")):
            workflow = "production"
        elif has_parent or ordinal or any(w in content for w in ("上一张", "上一版", "换成", "修改", "修一下", "其他地方保持")):
            workflow = "edit"
        elif any(w in content for w in ("队列", "排队", "任务进度")):
            workflow = "query"
        return IntentDecision(intent="generate", summary=content[:300], workflow=workflow,
            image_count=min(10, max(1, number(count[1]))) if count else 1,
            reference_number=number(ordinal[1]) if ordinal else None)


def message_plan(message, *, workflow="clarify", needs=None, blocked=None, count=0, risks=None):
    return AgentPlan(summary=message, workflow=workflow, actions=[ToolAction(tool="show_message", arguments={"message": message})],
        needs_input=needs or [], blocked_reason=blocked, image_count=count, risks=risks or [])


async def build_chat_plan(db, settings, org, user, context, selection, decision):
    if decision["intent"] == "model_plan":
        selected = context['assets'] if selection.get('use_batch_inputs') else [a for a in context["assets"] if a["attachment_id"] in selection["attachment_ids"]]
        visual = selected
        representative=len(selected)>1 and representative_background_edit(selection['content'],(selection.get('_creative_context') or {}).get('module','auto'))
        if selection.get('use_batch_inputs'):
            # Import provenance/manual assignments are authoritative. The planner
            # needs pixels only for unresolved roles; garment details are still
            # analyzed per image by the existing understanding/Luna tool later.
            assignments = {e['asset_id']: e['role'] for e in (context.get('batch_input_manifest') or {}).get('entries', [])}
            visual = [a for a in selected if assignments.get(a['id'],a['role'])=='reference']
        if representative:
            order={aid:i for i,aid in enumerate(selection.get('attachment_ids',[]))}
            visual=sorted(visual,key=lambda a:order.get(a['attachment_id'],len(order)))[:1]
        parent=next((o for o in context['outputs'] if o['id']==selection.get('parent_output_id')),None)
        references=list(dict.fromkeys(([parent['asset_id']] if parent else [])+[a['id'] for a in visual[:10]]))[:10]
        try:
            model = await resolve_operation_model_code(db, organization_id=org, operation_code="listing.plan", capability="text_generation",
                additional_capabilities={"vision_input"} if references else set(),
                preferred_model_code=settings.agent_control_text_model)
            budget = (await estimate_response(db, organization_id=org, operation_code="listing.plan", quantity=1,
                factors={"model": model, "resource_pool": "platform"})).model_dump(mode="json")
            budget["model_code"] = model
        except AppError as error:
            return message_plan("文本理解通道不可用，请管理员配置 listing.plan 的文本/视觉资源池和额度规则。", blocked=error.code)
        return AgentPlan(summary="先确认使用文本/视觉模型理解本条需求；尚不会发送生图请求。", workflow="clarify", may_charge=True,
            budget=budget, cost_note="本次仅预占文本理解额度；生图仍须单独确认。", actions=[ToolAction(tool="plan_intent", arguments={
                "project_id": context["project_id"], "content": selection["content"], "chat_mode": True, "model_code": model,
                "reference_asset_ids": references,
                "context_summary": {"history": context["history"], "asset_total":len(selected),"assets": [{k: a[k] for k in ("id", "role", "filename")} for a in selected[:50]],
                    'planner_visual_scope':{'mode':'representative_background_edit' if representative else 'all_selected','visual_count':len(references),'total_sources':len(selected)},
                    'execution_policy':selection.get('_execution_mode','bounded'),
                    'previous_proposal_not_authorization':context.get('pending_action'),
                    'parent_output':{k:parent[k] for k in ('id','asset_id','number','version')} if parent else None,
                    "outputs": [{k: o[k] for k in ("id", "number", "parent_output_id")} for o in context["outputs"][-30:]]}})])
    route = IntentDecision.model_validate(decision)
    if selection.get('_execution_mode')=='autonomous' and approval_question(route.question):
        route=route.model_copy(update={'question':None,'intent':'generate','workflow':route.workflow if route.workflow!='clarify' else 'fast'})
    workflow = route.workflow or {"queue": "query", "jobs": "query", "generate": "fast"}.get(route.intent, "clarify")
    selected = [a for a in context["assets"] if a["attachment_id"] in selection["attachment_ids"]]
    if selection.get('independent_edits'):
        order={aid:i for i,aid in enumerate(selection['attachment_ids'])};selected.sort(key=lambda a:order[a['attachment_id']])
    if workflow == "query":
        return AgentPlan(summary="读取同组织队列摘要", workflow="query", actions=[ToolAction(tool="read_shared_queue")])
    if workflow == "research":
        return message_plan("已识别为 A+ Research Path。目前尚未接入经过授权的联网检索工具，不能声称已调研市场案例。你可以先提供案例或打开原 A+ 工作台。",
            workflow="research", blocked="agent.research_not_configured", risks=["未产生任何市场调研来源或A+收费任务"])
    if workflow == "production":
        candidates = selected or context["assets"]
        if any(a["role"] in {"font", "front", "back", "detail"} for a in candidates):
            return message_plan("请先确认这些正背/细节/图C参考分别属于哪件服装；当前聊天版尚未导入组合映射，请在原工作台继续，避免漏图。",
                workflow="production", needs=["reference_mapping"], risks=["不静默丢弃字体或正背面参考"])
        templates = list(dict.fromkeys(a["id"] for a in candidates if a["role"] == "template"))
        garments = list(dict.fromkeys(a["id"] for a in candidates if a["role"] == "garment"))
        if not templates or not garments:
            return message_plan("这些图片中，哪些是模板图，哪些是服装图？请在附件的角色卡中确认。", workflow="production",
                needs=["asset_roles"], risks=["未确认角色前不创建笛卡尔组合或收费任务"])
        return AgentPlan(summary=f"已识别 {len(templates)} 个模板 × {len(garments)} 件服装，共 {len(templates)*len(garments)} 个逻辑组合。",
            workflow="production", image_count=len(templates)*len(garments),
            cost_note="本次仅关联现有项目素材，不生图、不收费；样图验证和正式生产继续原B流程。",
            risks=["通用规则分层缓存与聊天内样图审核尚未接入，不自动跳过样图门槛"],
            actions=[ToolAction(tool="prepare_tryon_workspace", arguments={"template_asset_ids": templates, "garment_asset_ids": garments})])
    if route.question or workflow == "clarify":
        return message_plan(route.question or "你希望对这些图片做什么修改？", needs=["intent"])
    parent = None
    requested_parent = selection.get("parent_output_id")
    if requested_parent:
        parent = next((o for o in context["outputs"] if o["id"] == requested_parent), None)
        if not parent:
            raise AppError("agent.output_not_found", "指定的结果不属于当前会话。", 404)
        workflow = "edit"
    elif workflow == "edit":
        # Editing a newly uploaded Asset is not editing a historical Output.
        # A model's reference_number must not turn upload #1 into nonexistent result #1.
        if not selected or explicit_previous_output(selection['content']):
            candidates = [o for o in context["outputs"] if o["number"] == route.reference_number] if route.reference_number else context["outputs"][-1:]
            if len(candidates) != 1:
                return message_plan("没有找到要修改的历史结果，请选择对应结果，或上传要编辑的图片。", workflow="edit", needs=["parent_output_id"])
            parent = candidates[0]
    references = list(dict.fromkeys(([parent["asset_id"]] if parent else []) + [a["id"] for a in selected]))
    if len(references) > 10:
        return message_plan("单次创作最多引用10张图片，请减少附件，或明确使用批量套图。", needs=["reference_limit"])
    independent=bool(selection.get('independent_edits'))
    if independent and not references:return message_plan('请提供需要分别编辑的原图。',workflow='edit',needs=['reference_images'])
    if independent and parent and len(references)>1:
        raise AppError('agent.edit_source_mismatch','独立编辑不能把一个历史父结果绑定到多张其他原图。',409)
    capability = 'image_edit' if independent else "image_generation" if not references else "image_edit" if len(references) == 1 else "multi_image_reference"
    prompt = selection["content"]
    if parent:
        prompt = "编辑第一张参考图中的当前结果，仅执行用户明确提出的修改，其他内容保持不变。\n用户要求：" + prompt
    try:
        model = await resolve_operation_model_code(db, organization_id=org, operation_code="listing.generate", capability=capability)
        action = ChatImageAction(project_id=context["project_id"], prompt=prompt, reference_asset_ids=references,
            parent_output_id=parent["id"] if parent else None, parent_asset_id=parent["asset_id"] if parent else None,
            root_output_id=parent["root_output_id"] if parent else None, count=len(references) if independent else route.image_count, model_code=model, capability=capability)
        budget = await chat.quote(db, org, action)
    except AppError as error:
        return message_plan(f"当前 {capability} 生图通道或额度规则尚未配置，未发送请求，请联系管理员配置 listing.generate。",
            workflow=workflow, blocked=error.code)
    return AgentPlan(summary=f"{'逐张独立编辑原图' if independent else '编辑所选图片' if parent else '按你的要求生成图片'}，共 {action.count} 张。", workflow=workflow,
        actions=[ToolAction(tool="generate_chat_images", arguments=action.model_dump())], image_count=action.count,
        may_charge=True, budget=budget, cost_note="显示的是平台额度估算，不是上游美元账单；执行前再次校验并逐Job预占。", risks=route.risks)
