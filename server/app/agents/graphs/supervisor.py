from app.agents.state import AgentState


def build_graph(*, checkpointer, identify, plan, execute):
    from langgraph.graph import StateGraph, START, END
    from langgraph.types import interrupt

    async def identify_node(state):
        return {"intent": await identify(), "status": "planning"}

    async def confirmation_node(state, config):
        # Explicit context propagation also supports the project's local Python 3.10.
        from langchain_core.runnables.config import set_config_context
        with set_config_context(config) as context:
            response = context.run(interrupt, {"kind": "confirm_plan", "plan": state["plan"]})
        approved = isinstance(response, dict) and response.get("approved") is True
        return {"decision": {"approved": approved}, "status": "submitting" if approved else "cancelled"}

    async def execute_node(state):
        result = await execute(state["plan"])
        return {"result": result, "status": "waiting_jobs" if result.get("job_ids") else "completed"}

    graph = StateGraph(AgentState)
    graph.add_node("identify", identify_node)
    from app.agents.graphs.batch_tryon import build_batch_subgraph
    graph.add_node("plan", build_batch_subgraph(plan))
    graph.add_node("confirm", confirmation_node)
    graph.add_node("execute", execute_node)
    graph.add_edge(START, "identify")
    graph.add_edge("identify", "plan")
    graph.add_edge("plan", "confirm")
    graph.add_conditional_edges("confirm", lambda s: "execute" if s["decision"]["approved"] else END)
    graph.add_edge("execute", END)
    return graph.compile(checkpointer=checkpointer)
