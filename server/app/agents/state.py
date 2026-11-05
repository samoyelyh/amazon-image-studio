from typing_extensions import TypedDict


class AgentState(TypedDict, total=False):
    run_id: str
    request_hash: str
    intent: dict
    plan: dict
    decision: dict
    result: dict
    status: str
