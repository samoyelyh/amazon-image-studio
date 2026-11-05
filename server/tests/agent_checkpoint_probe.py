"""Subprocess crash/restart probe. Refuses non-test databases. Never invokes a model."""
import asyncio
import json
import os
import sys
from urllib.parse import urlsplit

from pydantic import SecretStr

from app.core.config import Settings
from app.agents.runtime import checkpoint_store
from app.agents.graphs.supervisor import build_graph


async def probe(phase, thread):
    url = os.environ["AGENT_TEST_CHECKPOINT_URL"]
    parsed = urlsplit(url)
    if parsed.hostname not in {"127.0.0.1", "localhost"} or not parsed.path.lstrip("/").startswith("agent_phase1_"):
        raise RuntimeError("Only an explicit local agent_phase1_ test database is allowed")
    settings = Settings(_env_file=None, environment="test", agent_checkpoint_url=SecretStr(url))
    async with checkpoint_store(settings, setup=phase == "prepare") as saver:
        async def identify(): return {"intent": "context", "summary": "probe"}
        def plan(_): return {"summary": "probe", "actions": []}
        async def execute(_): return {"probe": thread}
        graph = build_graph(checkpointer=saver, identify=identify, plan=plan, execute=execute)
        config = {"configurable": {"thread_id": thread}}
        from langgraph.types import Command
        if phase == "prepare":
            await graph.ainvoke({"run_id": thread, "request_hash": "probe"}, config)
        elif phase == "resume":
            await graph.ainvoke(Command(resume={"approved": True}), config)
        state = await graph.aget_state(config)
        return {"status": state.values["status"], "next": list(state.next), "result": state.values.get("result")}


if __name__ == "__main__":
    print(json.dumps(asyncio.run(probe(sys.argv[1], sys.argv[2]))))
