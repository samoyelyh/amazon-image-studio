from dataclasses import dataclass
from typing import Type

from pydantic import BaseModel
from sqlalchemy import select

from app.core.errors import AppError
from app.models.tasks import JobBatch
from app.agents import contracts as c
from app.agents.adapters import batch_tryon as batch
from app.agents.planner import submit_intent_job
from app.agents.production import AnalyzeAssets, PlanAction
from app.agents.amazon_contracts import SavePlan, ModuleRevision, ModuleRevisions, GenerateAPlus
from app.agents.capabilities.contracts import ResearchAction


@dataclass(frozen=True)
class ToolSpec:
    schema: Type[BaseModel]
    permissions: tuple[str, ...]
    writes: bool = False
    model_cost: bool = False
    ready: bool = True


class IntentRequest(c.StrictModel):
    project_id: str | None = None
    content: str
    chat_mode: bool = False
    reference_asset_ids: list[str] = []
    context_summary: dict = {}
    model_code: str | None = None


from app.agents.batch_manifest import ManifestPatch
from app.agents.batch_followup import BatchFollowup
from app.agents.samples import ReviewSamples
from app.agents.experience import MemoryQuery,PreferenceChange

TOOLS = {
    'guide_batch_inputs':ToolSpec(c.QueueRead,('assets.read',)),
    'recall_user_experience':ToolSpec(MemoryQuery,('assets.read',)),
    'manage_user_preference':ToolSpec(PreferenceChange,('assets.read',),True),
    'review_tryon_samples':ToolSpec(ReviewSamples,('batch_tryon.review','assets.read'),True),
    'followup_batch_results': ToolSpec(BatchFollowup,('jobs.submit','assets.read','projects.write','batch_tryon.review'),True,True),
    'configure_batch_inputs': ToolSpec(ManifestPatch,('assets.read','projects.write'),True),
    'suggest_creative_directions': ToolSpec(c.SuggestCreativeDirections, ('jobs.submit','assets.read'), True, True),
    'research_amazon': ToolSpec(ResearchAction, ('jobs.read',), True, True),
    'save_aplus_plan': ToolSpec(SavePlan, ('projects.write','assets.read'), True),
    'revise_aplus_module': ToolSpec(ModuleRevision, ('projects.write','assets.read'), True),
    'revise_amazon_modules': ToolSpec(ModuleRevisions, ('projects.write','assets.read'), True),
    'generate_aplus': ToolSpec(GenerateAPlus, ('jobs.submit','projects.write','assets.read'), True, True),
    "read_business_context": ToolSpec(c.ContextRead, ("jobs.read", "projects.read", "assets.read")),
    "read_jobs": ToolSpec(c.JobRead, ("jobs.read",)),
    "read_shared_queue": ToolSpec(c.QueueRead, ("jobs.read",)),
    "analyze_tryon_references": ToolSpec(c.WorkflowAction, ("jobs.submit",), True, True),
    "compile_prompt_plan": ToolSpec(c.WorkflowAction, ("jobs.read", "assets.read")),
    "submit_tryon_batch": ToolSpec(c.WorkflowAction, ("jobs.submit",), True, True),
    "review_output": ToolSpec(c.ReviewDecision, ("batch_tryon.review",), True),
    "export_results": ToolSpec(c.ExportRequest, ("jobs.read", "assets.read")),
    "plan_intent": ToolSpec(IntentRequest, ("jobs.submit",), True, True),
    "generate_chat_images": ToolSpec(c.ChatImageAction, ("jobs.submit", "projects.write", "assets.read"), True, True),
    "prepare_tryon_workspace": ToolSpec(c.PrepareTryOnAction, ("projects.write", "assets.read"), True),
    "show_message": ToolSpec(c.MessageAction, ("jobs.read",)),
    "analyze_chat_assets": ToolSpec(AnalyzeAssets, ("jobs.submit", "assets.read"), True, True),
    "generate_chat_tryon": ToolSpec(PlanAction, ("jobs.submit", "projects.write", "assets.read"), True, True),
}


def catalog():
    return [{"name": name, "permissions": list(s.permissions), "writes": s.writes,
             "may_charge": s.model_cost, "input_schema": s.schema.model_json_schema()} for name, s in TOOLS.items()]


def validate_action(action):
    spec = TOOLS.get(action.tool)
    if spec is None:
        raise AppError("agent.tool_not_allowed", "该工具未获授权。", 422)
    return spec, spec.schema.model_validate(action.arguments)


async def execute(db, settings, redis, *, org, user, permissions, action, action_key, confirmed=False, conversation_id=None, autonomous_production=False,sample_review_required=False,human_request='',card_review=None,run_id=None):
    spec, args = validate_action(action)
    if not set(spec.permissions) <= set(permissions):
        raise AppError("auth.permission_denied", "当前账号没有执行该动作的权限。", 403)
    if spec.writes and not confirmed:
        raise AppError("agent.confirmation_required", "写操作缺少有效的服务端执行授权。", 409)
    if spec.writes and not settings.agent_control_writes_enabled:
        raise AppError("agent.writes_disabled", "总控写操作尚未启用；原专业工作台不受影响。", 409)
    if spec.model_cost and not settings.agent_control_model_calls_enabled:
        raise AppError("agent.model_calls_disabled", "模型调用尚未启用，不会发送收费请求。", 409)
    if action.tool == "show_message":
        return {"message": args.message}
    if action.tool in {'guide_batch_inputs','recall_user_experience','manage_user_preference','review_tryon_samples'}:
        from app.agents import runtime,experience,samples
        conv=await runtime.conversation(db,org,user,conversation_id,lock=spec.writes)
        if action.tool=='guide_batch_inputs':return {'message':'请在这里上传模板图和服装主图；正背面及字体图可随后补充。准备好后我会先为每个模板生成一张样图。','cards':[{'type':'batch_upload_guide'}]}
        if action.tool=='recall_user_experience':return await experience.recall(db,conv,args)
        if action.tool=='manage_user_preference':return await experience.change(db,conv,args,human_request=human_request,source_run_id=run_id)
        if any(d.decision!='approve' for d in args.decisions) and 'jobs.submit' not in permissions:
            raise AppError('auth.permission_denied','当前账号没有重做图片的权限。',403)
        return await samples.execute(db,settings,conv,args,action_key,human_request=human_request,card_request=card_review)
    if action.tool=='configure_batch_inputs':
        from app.agents import runtime,batch_manifest
        conv=await runtime.conversation(db,org,user,conversation_id,lock=True)
        return {'batch_input_manifest':await batch_manifest.patch(db,conv,args)}
    if action.tool=='followup_batch_results':
        from app.agents import runtime,batch_followup
        conv=await runtime.conversation(db,org,user,conversation_id,lock=True)
        return await batch_followup.execute(db,settings,conv,args,action_key)
    if action.tool == 'suggest_creative_directions':
        from app.agents import runtime, creative_assistance
        conv = await runtime.conversation(db, org, user, conversation_id, lock=True)
        if conv.mode != 'chat':
            raise AppError('agent.mode_mismatch', '创作建议仅用于聊天。', 409)
        return await creative_assistance.submit(db, settings, conv, args, action_key)
    if action.tool=='research_amazon':
        from app.agents import amazon_research, runtime
        conv=await runtime.conversation(db,org,user,conversation_id,lock=True)
        return await amazon_research.execute(db,settings,conv,permissions,args,action_key)
    if action.tool in {'save_aplus_plan','revise_aplus_module','revise_amazon_modules','generate_aplus'}:
        from app.agents import amazon, runtime
        conv=await runtime.conversation(db,org,user,conversation_id,lock=True)
        if action.tool=='save_aplus_plan':return await amazon.save(db,conv,args.plan,action_key)
        if action.tool in {'revise_aplus_module','revise_amazon_modules'}:
            _,plan=await amazon.record(db,conv,args.plan_id)
            requested=amazon.requested_revision_ids(human_request,plan)
            changed={m.id for m in args.modules} if action.tool=='revise_amazon_modules' else {args.module.id}
            if requested and requested!=changed:
                raise AppError('agent.module_scope_mismatch','修改范围与用户指定的图片序号不一致，未修改其他图片。',409)
            return await (amazon.revise(db,conv,args) if action.tool=='revise_aplus_module' else amazon.revise_many(db,conv,args))
        return await amazon.generate(db,settings,conv,args,action_key)
    if action.tool in {"generate_chat_images", "prepare_tryon_workspace", "analyze_chat_assets", "generate_chat_tryon"}:
        from app.models.hermes_agent import HermesConversation
        from app.agents.adapters import chat
        conv = await db.scalar(select(HermesConversation).where(HermesConversation.id == conversation_id,
            HermesConversation.organization_id == org, HermesConversation.user_id == user,
            HermesConversation.controller_type.in_(["langgraph", "dsh"]), HermesConversation.mode == "chat"))
        if conv is None:
            raise AppError("agent.conversation_not_found", "会话不存在或无权访问。", 404)
        if action.tool == "generate_chat_images":
            return await chat.generate(db, settings, conv, args, action_key)
        if action.tool in {"analyze_chat_assets", "generate_chat_tryon"}:
            from app.agents import production
            return await (production.analyze(db,settings,conv,args,action_key) if action.tool=='analyze_chat_assets'
                else production.generate(db,settings,conv,args,action_key,autonomous=autonomous_production,sample_review_required=sample_review_required))
        return await chat.prepare_tryon(db, settings, conv, args)
    if action.tool == "read_business_context":
        if args.context_kind == "attachment":
            from app.agents.adapters.attachment import read_context
            return await read_context(db, org, user, args.project_id)
        return await batch.read_context(db, org, user, args.project_id)
    if action.tool == "read_jobs":
        return {"jobs": await batch.read_jobs(db, org, user, args.job_ids)}
    if action.tool == "read_shared_queue":
        from app.services.batch_tryon_shared_queue_service import shared_queue_snapshot
        board = await shared_queue_snapshot(db, redis, settings, organization_id=org, user_id=user, limit=args.limit)
        return board.model_dump(mode="json")
    if action.tool in {"compile_prompt_plan", "submit_tryon_batch", "analyze_tryon_references"}:
        await batch.verify_workflow(db, org, user, args.workflow)
        if action.tool == "compile_prompt_plan":
            return batch.compile_prompt(args.workflow)
        return await batch.submit_workflow(db, settings, org, user, args.workflow, action_key,
            analysis_only=action.tool == "analyze_tryon_references")
    if action.tool == "review_output":
        return await batch.approve(db, org, user, args.item_id, args.version_id)
    if action.tool == "export_results":
        row = await db.scalar(select(JobBatch).where(JobBatch.id == args.batch_id,
            JobBatch.organization_id == org, JobBatch.created_by == user, JobBatch.workspace_type == "batch_tryon"))
        if row is None:
            raise AppError("agent.batch_not_found", "批次不存在或无权访问。", 404)
        return {"download_path": f"/api/v1/job-batches/{row.id}/batch-tryon-results.zip?allow_partial={str(args.allow_partial).lower()}",
                "note": "下载由原导出服务再次校验权限、可用版本、缺失文件及 ZIP 完整性。"}
    if action.tool == "plan_intent":
        if args.project_id:
            await batch.owned_project(db, org, user, args.project_id)
        return await submit_intent_job(db, settings, org, user, args.project_id, args.content, action_key,
            chat_mode=args.chat_mode, reference_asset_ids=args.reference_asset_ids, context_summary=args.context_summary, model_code=args.model_code)
    raise AppError("agent.tool_not_allowed", "该工具不可用。", 422)
