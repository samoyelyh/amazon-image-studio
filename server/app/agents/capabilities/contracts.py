from dataclasses import dataclass
from typing import Literal

from pydantic import Field, model_validator
from app.agents.contracts import StrictModel


@dataclass(frozen=True)
class ExecutionContext:
    organization_id: str
    user_id: str
    conversation_id: str
    run_id: str
    permissions: frozenset[str]


class ToolApproval(StrictModel):
    name: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,100}$")
    description: str = Field(min_length=1, max_length=500)
    input_schema: dict
    permissions: list[str] = Field(default_factory=lambda: ["jobs.read"])
    risk: Literal["read_only", "write", "sensitive"] = "read_only"
    may_charge: bool = True  # An administrator must explicitly attest to zero cost.
    max_charge_units: int | None = Field(default=None, ge=1, le=100)
    keywords: list[str] = Field(default_factory=list, max_length=30)


class MCPApproval(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,50}$")
    version: str = Field(min_length=1, max_length=80)
    enabled: bool = False
    approved_by: str = Field(min_length=1, max_length=100)
    organizations: list[str] = Field(min_length=1, max_length=100)
    users: list[str] = Field(default_factory=list, max_length=100)
    url: str = Field(max_length=1000)
    allow_local_http: bool = False
    trust_environment_proxy: bool = False
    credential_env: str | None = Field(default=None, pattern=r"^AGENT_MCP_[A-Z0-9_]{1,100}$")
    credential_header: Literal['Authorization', 'secret-key'] = 'Authorization'
    profile: Literal['generic', 'sellersprite'] = 'generic'
    daily_unit_limit: int = Field(default=100, ge=1, le=1000)
    calls_per_minute: int = Field(default=3, ge=1, le=30)
    timeout_seconds: float = Field(default=10, ge=.1, le=30)
    max_calls_per_run: int = Field(default=3, ge=1, le=8)
    tools: list[ToolApproval] = Field(default_factory=list, max_length=50)

    @model_validator(mode='after')
    def enabled_server_requires_reviewed_tools(self):
        # A disabled server can be staged for tools/list before its real schemas are known.
        if self.enabled and not self.tools:
            raise ValueError('Enabled MCP servers require at least one reviewed tool schema')
        return self


class SkillApproval(StrictModel):
    path: str = Field(min_length=1, max_length=1000)
    version: str = Field(min_length=1, max_length=80)
    enabled: bool = False
    approved_by: str = Field(min_length=1, max_length=100)
    organizations: list[str] = Field(min_length=1, max_length=100)
    users: list[str] = Field(default_factory=list, max_length=100)
    permissions: list[str] = Field(default_factory=lambda: ["jobs.read"])
    allowed_tools: list[str] = Field(min_length=1, max_length=30)
    keywords: list[str] = Field(default_factory=list, max_length=30)


class CapabilityManifest(StrictModel):
    schema_version: Literal[1] = 1
    skills: list[SkillApproval] = Field(default_factory=list, max_length=100)
    mcp_servers: list[MCPApproval] = Field(default_factory=list, max_length=30)


class PlannedStep(StrictModel):
    capability_id: str = Field(min_length=1, max_length=180)
    arguments: dict = Field(default_factory=dict)
    reason: str = Field(min_length=1, max_length=500)


class InferredAssetRole(StrictModel):
    asset_id: str = Field(min_length=36,max_length=36)
    role: Literal['template','garment','reference','front','back','detail','font']
    confidence: float = Field(ge=0,le=1)
    reason: str = Field(min_length=1,max_length=500)


class CapabilityDecision(StrictModel):
    summary: str = Field(min_length=1, max_length=1000)
    skills: list[str] = Field(default_factory=list, max_length=3)
    steps: list[PlannedStep] = Field(default_factory=list, max_length=6)
    done: bool = False
    question: str | None = Field(default=None, max_length=300)
    asset_roles: list[InferredAssetRole] = Field(default_factory=list,max_length=50)
    discover: list[str] = Field(default_factory=list,max_length=12,
        description='Approved capability IDs whose complete input schemas are needed before planning their arguments. Discovery does not execute tools.')


class ImageRequest(StrictModel):
    instruction: str = Field(min_length=1, max_length=10000)
    count: int = Field(default=1, ge=1, le=10)
    reference_number: int | None = Field(default=None, ge=1, description='Only the visible number of an existing generated Output; never an uploaded image index.')
    edit: bool = Field(default=False, description='Edit an uploaded reference or an existing Output. New uploads do not require a historical Output.')
    reference_asset_ids: list[str] | None = Field(default=None, max_length=10)
    independent_edits:bool=Field(default=False,description='Edit each selected source independently, one result per source. Not a composite, try-on matrix or variation count.')


class LibrarySearch(StrictModel):
    query: str = Field(default="", max_length=100)


class Empty(StrictModel):
    pass


class ResearchAction(StrictModel):
    capability_id: str = Field(max_length=180)
    arguments: dict
    max_charge_units: int = Field(ge=1, le=100)
