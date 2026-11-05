"""Dynamic business adapters call the original tools/services and keep owner checks."""
from sqlalchemy import select
import re
from app.core.errors import AppError
from app.agents.contracts import ToolAction, IntentDecision
from app.agents.intent_router import build_chat_plan
from app.agents.capabilities.contracts import ImageRequest, LibrarySearch


async def materialize_image(db, settings, ctx, business_context, selection, arguments, observations=()):
    args = ImageRequest.model_validate(arguments)
    from app.agents import experience,runtime
    conv=await runtime.conversation(db,ctx.organization_id,ctx.user_id,ctx.conversation_id)
    remembered=await experience.recall(db,conv,experience.MemoryQuery(product_type=experience.scope(selection['content'])))
    preferences=experience.prompt_rules(remembered,selection['content'])
    if preferences:
        suffix='\n个人视觉偏好（仅在不冲突于本次要求及商品真实设计时适用）：'+'；'.join(p['instruction'] for p in preferences)
        if len(args.instruction+suffix)<=10000:args=args.model_copy(update={'instruction':args.instruction+suffix})
    # The model may propose edits, but the server resolves actual Output/Asset IDs and prices.
    local_selection = {**selection, "content": args.instruction,'independent_edits':args.independent_edits}
    # Some planners serialize an unspecified reference list as []. Do not silently
    # drop the human's selected uploads; only the human can explicitly disregard them.
    preserve_uploads=args.reference_asset_ids==[] and selection.get('attachment_ids') and not re.search(
        r'忽略上传图片|不使用参考图|无需参考图|不要使用上传图',selection['content'])
    if args.reference_asset_ids is not None and not preserve_uploads:
        from app.agents.adapters import chat
        known = {a["id"] for a in business_context["assets"]}
        known |= {o['asset_id'] for o in business_context.get('outputs', [])}
        known |= {item["asset_id"] for observation in observations
            if observation["capability_id"] == "business.search_my_assets" and observation["status"] == "succeeded"
            for item in observation.get("result", {}).get("items", [])}
        if set(args.reference_asset_ids) - known:
            raise AppError("agent.reference_not_observed", "只能引用当前会话素材或本次已授权素材查询实际返回的图片。", 403)
        requested=list(dict.fromkeys(args.reference_asset_ids))
        if args.independent_edits:
            by_attachment={a['attachment_id']:a['id'] for a in business_context['assets']}
            order={by_attachment[aid]:i for i,aid in enumerate(selection.get('attachment_ids',[])) if aid in by_attachment}
            fallback={aid:i for i,aid in enumerate(requested)}
            requested.sort(key=lambda aid:order.get(aid,len(order)+fallback[aid]))
        virtual = []
        for asset_id in requested:
            asset = await chat.asset(db, ctx.organization_id, ctx.user_id, asset_id)
            virtual.append({"id": asset.id, "attachment_id": asset.id, "role": "reference", "filename": asset.filename})
        business_context = {**business_context, "assets": virtual}
        local_selection["attachment_ids"] = [a["attachment_id"] for a in virtual]
    return await build_chat_plan(db, settings, ctx.organization_id, ctx.user_id, business_context, local_selection,
        IntentDecision(intent="generate", summary=args.instruction[:300], workflow="edit" if args.edit or args.independent_edits else "fast",
            image_count=args.count, reference_number=args.reference_number).model_dump())


async def read(db, settings, redis, ctx, cap, arguments, business_context):
    if cap.id == 'business.amazon_context':
        from app.agents import amazon, runtime
        conv=await runtime.conversation(db,ctx.organization_id,ctx.user_id,ctx.conversation_id)
        return {'plans':await amazon.list_plans(db,conv),'rules':amazon.rules(),'company_visual_rules':amazon.visual_rules(),
            'assets':business_context['assets'], 'research':business_context.get('amazon_research',[]),
            'note':'没有调研记录表示尚未调研；用户完整资料足够时不必调用收费MCP。'}
    if cap.id == "business.current_jobs":
        from app.models.agent_control import AgentRun, AgentJobLink
        from app.agents.adapters.batch_tryon import read_jobs
        ids = list((await db.scalars(select(AgentJobLink.job_id).join(AgentRun, AgentRun.id == AgentJobLink.run_id)
            .where(AgentRun.conversation_id == ctx.conversation_id, AgentRun.organization_id == ctx.organization_id,
                   AgentRun.user_id == ctx.user_id).limit(100))).all())
        return {"jobs": await read_jobs(db, ctx.organization_id, ctx.user_id, ids) if ids else []}
    if cap.id == "business.search_my_assets":
        from app.models.content import Asset
        args = LibrarySearch.model_validate(arguments)
        rows = list((await db.scalars(select(Asset).where(Asset.organization_id == ctx.organization_id,
            Asset.created_by == ctx.user_id, Asset.deleted_at.is_(None), Asset.filename.contains(args.query))
            .order_by(Asset.created_at.desc(), Asset.id).limit(30))).all())
        return {"items": [{"asset_id": a.id, "filename": a.filename} for a in rows], "count": len(rows)}
    if cap.id == "business.current_context":
        return {"project_id": business_context.get("project_id"),
            "assets": [{k: a[k] for k in ("id", "role", "filename")} for a in business_context["assets"]],
            "outputs": [{k: o[k] for k in ("id", "number", "version")} for o in business_context.get("outputs", [])]}
    args = dict(arguments)
    if cap.source == "hermes":
        args["context_kind"] = "attachment"
    # Project-target operations cannot escape the current conversation via a proposed ID.
    project_id = args.get("project_id") or (args.get("workflow") or {}).get("project_id")
    if project_id and project_id != business_context.get("project_id"):
        raise AppError("agent.context_mismatch", "工具目标与当前会话不一致。", 409)
    from app.agents.tool_registry import execute
    return await execute(db, settings, redis, org=ctx.organization_id, user=ctx.user_id,
        permissions=ctx.permissions, action=ToolAction(tool=cap.binding, arguments=args),
        action_key=f"agent:{ctx.run_id}:readonly", confirmed=False, conversation_id=ctx.conversation_id)
