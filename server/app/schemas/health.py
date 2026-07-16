from typing import Literal

from pydantic import BaseModel, Field


class ComponentHealth(BaseModel):
    status: Literal["ok", "error"]
    latency_ms: float = Field(ge=0)
    message: str | None = None


class LivenessResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str
    version: str


class ReadinessResponse(BaseModel):
    status: Literal["ok", "degraded"]
    service: str
    version: str
    components: dict[str, ComponentHealth]
