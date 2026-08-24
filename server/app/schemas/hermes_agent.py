from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class HermesStatusResponse(BaseModel):
    enabled: bool
    available: bool
    mode: Literal["suggest"] = "suggest"
    model: str
    profile: str
    message: str


class HermesAction(BaseModel):
    tool: str = Field(min_length=1, max_length=80)
    arguments: dict[str, object] = Field(default_factory=dict)


class HermesProposalResponse(BaseModel):
    id: str
    summary: str
    actions: list[HermesAction]
    expected_state_signature: str
    status: str
    result: dict[str, object]
    error_message: str | None
    created_at: datetime
    applied_at: datetime | None


class HermesMessageResponse(BaseModel):
    id: str
    role: Literal["user", "assistant", "system"] | str
    content: str
    metadata: dict[str, object]
    external_response_id: str | None
    created_at: datetime
    proposal: HermesProposalResponse | None = None


class HermesConversationResponse(BaseModel):
    id: str
    project_id: str
    title: str
    mode: str
    status: str
    created_at: datetime
    updated_at: datetime
    messages: list[HermesMessageResponse] = Field(default_factory=list)


class HermesConversationCreateRequest(BaseModel):
    title: str = Field(default="Hermes 智能助理", min_length=1, max_length=160)


class HermesChatRequest(BaseModel):
    content: str = Field(min_length=1, max_length=12000)


class HermesProposalApplyResponse(BaseModel):
    proposal: HermesProposalResponse
    state_signature: str
    results: list[dict[str, object]]
