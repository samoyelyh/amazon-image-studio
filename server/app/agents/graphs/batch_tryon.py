from app.core.errors import AppError
from app.agents.contracts import AgentPlan, ToolAction
from app.agents.adapters.batch_tryon import build_workflow


def build_batch_subgraph(plan):
    from langgraph.graph import StateGraph, START, END
    from app.agents.state import AgentState
    async def compile_plan(state):
        import inspect
        value = plan(state["intent"])
        if inspect.isawaitable(value):
            value = await value
        return {"plan": value, "status": "awaiting_confirmation"}
    graph = StateGraph(AgentState)
    graph.add_node("compile_plan", compile_plan)
    graph.add_edge(START, "compile_plan")
    graph.add_edge("compile_plan", END)
    return graph.compile()


def build_plan(intent, context, selection, run_id, job_ids):
    mode = intent["intent"]
    if context.get("context_kind") == "attachment":
        return AgentPlan(summary="读取现有 Hermes 附图上下文；策划和生图请继续使用原入口。",
            actions=[ToolAction(tool="read_business_context", arguments={"project_id": context["project_id"], "context_kind": "attachment"})])
    if mode == "queue":
        action = ToolAction(tool="read_shared_queue")
    elif mode == "jobs" and job_ids:
        action = ToolAction(tool="read_jobs", arguments={"job_ids": job_ids})
    elif mode in {"generate", "analyze", "compile"}:
        workflow = build_workflow(context, selection, action_key=f"agent:{run_id}", analysis=mode == "analyze")
        name = {"generate": "submit_tryon_batch", "analyze": "analyze_tryon_references", "compile": "compile_prompt_plan"}[mode]
        return AgentPlan(summary=intent["summary"], actions=[ToolAction(tool=name, arguments={"workflow": workflow.model_dump(mode="json")})],
                         image_count=len(workflow.templates) * len(workflow.garments) if mode == "generate" else 0,
                         may_charge=mode != "compile", cost_note="将复用原任务系统的额度预占和资源池；实际费用由原服务计算。" if mode != "compile" else "仅编译预览，不调用模型。")
    elif mode == "model_plan":
        return AgentPlan(summary="确认使用现有文本通道理解需求（可能产生 Token 费用）",
            actions=[ToolAction(tool="plan_intent", arguments={"project_id": context["project_id"], "content": selection["content"]})],
            may_charge=True, cost_note="仅提交文本规划 Job；不会提交图片任务。图片生成仍需第二次人工确认。")
    else:
        action = ToolAction(tool="read_business_context", arguments={"project_id": context["project_id"]})
    return AgentPlan(summary=intent["summary"], actions=[action])
