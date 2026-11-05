from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator,field_validator

from app.schemas.batch_tryon_workflow import BatchTryOnWorkflowCreateRequest


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ContextRead(StrictModel):
    project_id: str = Field(min_length=36, max_length=36)
    context_kind: Literal["batch_tryon", "attachment"] = "batch_tryon"


class JobRead(StrictModel):
    job_ids: list[str] = Field(min_length=1, max_length=100)


class QueueRead(StrictModel):
    limit: int = Field(default=30, ge=1, le=100)


class WorkflowAction(StrictModel):
    workflow: BatchTryOnWorkflowCreateRequest


class ReviewDecision(StrictModel):
    item_id: str = Field(min_length=36, max_length=36)
    version_id: str = Field(min_length=36, max_length=36)


class ExportRequest(StrictModel):
    batch_id: str = Field(min_length=36, max_length=36)
    allow_partial: bool = False


ToolName = Literal[
    "read_business_context", "read_jobs", "read_shared_queue", "analyze_tryon_references",
    "compile_prompt_plan", "submit_tryon_batch", "review_output", "export_results",
    "plan_intent", "generate_chat_images", "prepare_tryon_workspace", "show_message", "analyze_chat_assets", "generate_chat_tryon",
    "save_aplus_plan", "revise_aplus_module", "revise_amazon_modules", "generate_aplus", "research_amazon",
    "suggest_creative_directions", "configure_batch_inputs", "followup_batch_results", "review_tryon_samples", "recall_user_experience", "manage_user_preference", "guide_batch_inputs",
]


class IntentDecision(StrictModel):
    intent: Literal["context", "queue", "jobs", "generate", "analyze", "compile", "clarify", "model_plan"]
    summary: str = Field(min_length=1, max_length=1000)
    workflow: Literal["fast", "production", "research", "edit", "query", "clarify"] | None = None
    image_count: int = Field(default=1, ge=1, le=10)
    reference_number: int | None = Field(default=None, ge=1)
    question: str | None = Field(default=None, max_length=300)
    risks: list[str] = Field(default_factory=list, max_length=10)
    capability_plan: dict | None = None


class ToolAction(StrictModel):
    tool: ToolName
    arguments: dict = Field(default_factory=dict)


class AgentPlan(StrictModel):
    schema_version: Literal[1] = 1
    summary: str
    actions: list[ToolAction] = Field(min_length=1, max_length=4)
    image_count: int = Field(default=0, ge=0, le=500)
    may_charge: bool = False
    cost_note: str = "不发送模型请求"
    workflow: str | None = None
    needs_input: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    blocked_reason: str | None = None
    budget: dict | None = None
    capability_context: dict | None = None


class ConversationCreate(StrictModel):
    project_id: str | None = Field(default=None, min_length=36, max_length=36)
    context_kind: Literal["batch_tryon", "attachment", "chat"] = "batch_tryon"
    title: str = Field(default="AI 总控", min_length=1, max_length=160)
    creative_module:Literal['auto','amazon_aplus','batch_tryon','listing_images','free_creation','image_edit']|None=None


class MessageCreate(StrictModel):
    content: str = Field(min_length=1, max_length=12000)
    client_request_id: str = Field(min_length=8, max_length=80)
    template_asset_ids: list[str] = Field(default_factory=list, max_length=10)
    garment_asset_ids: list[str] = Field(default_factory=list, max_length=50)
    prompt: str = Field(default="", max_length=10000)
    prompt_kind: Literal["final", "analysis"] = "final"
    template_type: Literal["pure_white", "gift_scene", "stadium_scene", "detail_display", "casual_scene", "custom_process"] = "pure_white"
    garment_view: Literal["auto", "front", "back", "front_back", "detail"] = "auto"
    chat_mode: bool = False
    auto_execute: bool = False  # Human send action, never supplied by a model tool.
    request_mode: Literal['create', 'suggest'] = 'create'
    reply_to_run_id: str | None = Field(default=None, min_length=36, max_length=36)
    reply_to_revision: int | None = Field(default=None, ge=1)
    review_before_generation: bool | None = None
    start_new_task: bool = False
    use_batch_inputs: bool = False
    creative_module:Literal['auto','amazon_aplus','batch_tryon','listing_images','free_creation','image_edit']|None=None
    sample_review:dict|None=None
    prompt_source_run_id: str | None = Field(default=None,min_length=36,max_length=36)
    prompt_version_id: str | None = Field(default=None,min_length=36,max_length=36)
    attachment_ids: list[str] = Field(default_factory=list, max_length=50)
    parent_output_id: str | None = Field(default=None, min_length=36, max_length=36)
    production_plan_id: str | None = Field(default=None,min_length=36,max_length=36)
    production_stage: Literal['validation','production'] | None = None
    production_revision: int | None = Field(default=None,ge=1)
    production_approved_only:bool=False
    amazon_plan_id: str | None = None
    amazon_revision: int | None = Field(default=None, ge=1)
    amazon_module_ids: list[str] = Field(default_factory=list, max_length=7)
    retry_image_job_id:str|None=Field(default=None,min_length=36,max_length=36)

    @model_validator(mode='after')
    def validate_reply(self):
        if self.retry_image_job_id and (not self.chat_mode or self.request_mode!='create' or self.attachment_ids or self.parent_output_id or self.amazon_plan_id or self.production_plan_id or self.prompt_source_run_id):
            raise ValueError('A single failed-image retry must be a standalone chat action')
        if self.sample_review is not None:
            from app.agents.samples import ReviewSamples
            self.sample_review=ReviewSamples.model_validate(self.sample_review).model_dump(mode='json')
            if not self.chat_mode or self.request_mode!='create' or self.production_plan_id or self.attachment_ids or self.parent_output_id:
                raise ValueError('Sample card actions must be a standalone chat action')
        if self.start_new_task and self.reply_to_run_id:raise ValueError('A new task cannot also reply to a pending task')
        if (self.prompt_source_run_id is None)!=(self.prompt_version_id is None):
            raise ValueError('Prompt source run and version must be supplied together')
        if self.prompt_source_run_id and (not self.chat_mode or self.request_mode!='create' or self.production_plan_id or self.amazon_plan_id or self.reply_to_run_id or self.attachment_ids or self.parent_output_id):
            raise ValueError('Saved image prompts can only be used for ordinary chat generation')
        if (self.reply_to_run_id is None) != (self.reply_to_revision is None):
            raise ValueError('reply_to_run_id and reply_to_revision must be supplied together')
        if not self.chat_mode and (self.reply_to_run_id or self.request_mode != 'create'):
            raise ValueError('Creative suggestions and replies require a chat conversation')
        return self

    def submission_payload(self):
        payload = self.model_dump(mode='json')
        # Preserve request hashes for existing clients replaying pre-extension messages.
        for key, default in (('request_mode','create'),('reply_to_run_id',None),('reply_to_revision',None),('review_before_generation',None),('start_new_task',False),('use_batch_inputs',False),('creative_module',None),('sample_review',None),('production_approved_only',False),('prompt_source_run_id',None),('prompt_version_id',None),('retry_image_job_id',None)):
            if payload.get(key) == default:
                payload.pop(key, None)
        return payload


class CreativeSuggestion(StrictModel):
    title: str = Field(min_length=1, max_length=80)
    instruction: str = Field(min_length=1, max_length=3000)


class CreativeSuggestions(StrictModel):
    summary: str = Field(min_length=1, max_length=500)
    options: list[CreativeSuggestion] = Field(min_length=1, max_length=3)


class SuggestCreativeDirections(StrictModel):
    instruction: str = Field(min_length=1, max_length=12000)
    reference_asset_ids: list[str] = Field(default_factory=list, max_length=10)
    model_code: str


class MaterialImport(StrictModel):
    batch_id:str=Field(min_length=8,max_length=80)
    total_files:int=Field(ge=1,le=500)
    source:Literal['template','garment','auto']='auto'
    relative_path:str=Field(min_length=1,max_length=1000)

    @field_validator('relative_path')
    @classmethod
    def validate_path(cls,value):
        from app.agents.material_import import safe_path
        return safe_path(value)


class AttachmentCreate(StrictModel):
    asset_id: str = Field(min_length=36, max_length=36)
    role: Literal["reference", "template", "garment", "front", "back", "detail", "font"] = "reference"
    import_info:MaterialImport|None=None


class ChatImageAction(StrictModel):
    project_id: str | None = None
    prompt: str = Field(min_length=1, max_length=10000)
    reference_asset_ids: list[str] = Field(default_factory=list, max_length=10)
    parent_output_id: str | None = None
    parent_asset_id: str | None = None
    root_output_id: str | None = None
    count: int = Field(default=1, ge=1, le=10)
    model_code: str = Field(min_length=1, max_length=120)
    capability: Literal["image_generation", "image_edit", "multi_image_reference"]
    # This action intentionally does not expose provider, URLs, arbitrary params or credentials.


class MessageAction(StrictModel):
    message: str = Field(min_length=1, max_length=2000)


class PrepareTryOnAction(StrictModel):
    template_asset_ids: list[str] = Field(min_length=1, max_length=10)
    garment_asset_ids: list[str] = Field(min_length=1, max_length=50)


class ConfirmRequest(StrictModel):
    expected_revision: int = Field(ge=1)
    state_signature: str = Field(pattern="^[a-f0-9]{64}$")
    confirmation_token: str = Field(min_length=64, max_length=64, repr=False)


class PromptRevisionRequest(StrictModel):
    expected_revision: int = Field(ge=1)
    content: str = Field(min_length=1, max_length=10000)
    source_id: str = Field(min_length=1, max_length=100)


class RunResponse(StrictModel):
    id: str
    conversation_id: str
    status: str
    revision: int
    planner_mode: str
    plan: AgentPlan | None
    result: dict
    error_code: str | None
    state_signature: str | None = None
    confirmation_token: str | None = None
    events: list[dict] = Field(default_factory=list)
    jobs: list[dict] = Field(default_factory=list)
    workspace_url: str | None = None
    outputs: list[dict] = Field(default_factory=list)
    verification: dict = Field(default_factory=dict)
    execution_notice: dict | None = None
    prompts: list[dict] = Field(default_factory=list)
