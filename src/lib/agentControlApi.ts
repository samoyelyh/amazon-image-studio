import { authenticatedFetch } from './authApi'
import { randomUuid } from './randomUuid'
import type {AmazonPlanRecord,AmazonReceipt} from './amazonAgentApi'
import type {CreativeModule,CreativeContext} from './agentCreativeModules'

export interface AgentStatus {
  controller?: 'dsh' | 'langgraph'
  enabled: boolean; writes_enabled: boolean; model_calls_enabled: boolean
  planner_mode: 'mock' | 'existing_text'; checkpoint_configured: boolean
  models?: Record<string, { configured: boolean; model_code?: string; reason?: string }>
  dynamic_capabilities_enabled?: boolean
  creative_assistance_enabled?: boolean
  auto_execution?: {enabled:boolean;mode?:'bounded'|'autonomous';max_images:number;max_seconds:number;max_credits:number;max_active_runs:number;submissions_per_minute:number}
}
export interface AgentContextOption { id: string; name: string; project_type: string }
export interface AgentAsset { id: string; filename: string; name: string; role: string; content_url: string; source_asset_id: string | null }
export interface AgentContext { project_id: string; name: string; assets: AgentAsset[]; signature: string }
export interface AgentAction { tool: string; arguments: Record<string, unknown> }
export interface AgentPlan { schema_version: 1; summary: string; actions: AgentAction[]; image_count: number; may_charge: boolean; cost_note: string
  workflow?: string; needs_input?: string[]; risks?: string[]; blocked_reason?: string | null
  budget?: { estimated_cost?: number; available_balance?: number; sufficient: boolean; model_code?: string;max_charge_units?:number } | null }
export interface AgentOutput { id: string; asset_id: string; job_id: string; run_id: string; number: number | null; sequence_number: number; size: number; mime_type: string
  source_asset_id?:string|null;source_filename?:string|null;source_index?:number|null
  batch_tryon?:{combination_id:string;template_asset_id:string;template_name:string;garment_id:string;garment_filename:string}|null
  review_item_id?:string|null;review_version_id?:string|null;review_status?:string|null
  amazon_module?:{plan_id:string;module_id:string;slot_id?:string;plan_revision:number;module_snapshot:{title:string}}|null
  filename: string; width: number; height: number; content_url: string; download_url: string; parent_output_id: string | null; root_output_id: string; version: number }
export type AttachmentRole = 'reference' | 'template' | 'garment' | 'front' | 'back' | 'detail' | 'font'
export interface MaterialImportInfo {batch_id:string;total_files:number;source:'template'|'garment'|'auto';relative_path:string}
export interface AgentAttachment { id: string; asset_id: string; filename: string; role: AttachmentRole; content_url: string; submitted: boolean;import_info?:MaterialImportInfo|null }
export interface AgentRun {
  id: string; conversation_id: string; status: string; revision: number; planner_mode: string
  plan: AgentPlan | null; result: { native_state?:string; actions?: Array<{ tool: string; result: Record<string, unknown> }>; job_ids?: string[]
    reply_context?:{source_run_id:string;source_revision:number;goal:string;question:string};execution_error?:string;submitted_import_keys?:string[]
    creative_suggestions?:{summary:string;options:Array<{title:string;instruction:string}>};retry_of_job_id?:string }
  error_code: string | null; state_signature: string | null; confirmation_token: string | null
  events: Array<{ id: string; type: string; payload: Record<string, unknown>; created_at: string }>
  jobs: Array<{ id: string; status: string; progress: number; error_code: string | null; capability?: string;upstream_unknown?:boolean;can_retry?:boolean;label?:string;image_kind?:'aplus'|'listing'|'image' }>
  workspace_url: string | null
  outputs?: AgentOutput[]
  prompts?:AgentPrompt[]
  verification?:Record<string,unknown>
  execution_notice?:{automatic:boolean;reason:string|null;image_count:number;estimated_credits:number;estimate?:{text:string;source:string;maximum_seconds?:number|null;sample_count:number}|null;limits?:Record<string,number>}|null
}
export interface AgentPrompt {id:string;version:number;content:string;source:'plan'|'planner'|'submitted'|'executed'|'user';job_id?:string;job_status?:string;parent_id?:string;created_at?:string;replayable?:boolean}
export interface AgentConversation { id: string; title: string; project_id: string | null; context_kind: string;creative_context?:CreativeContext }
export interface AgentChatMessage { id: string; role: string; content: string; metadata?: { run_id?: string; attachments?: Array<AgentAttachment & { attachment_id?: string }>; parent_output_id?: string | null;reply_to_run_id?:string;request_mode?:'create'|'suggest' } }
export interface AssetUnderstanding {role:AttachmentRole;confidence:number;template_type:string;view:string;protected_elements:string[];allowed_changes:string[];visual_facts:string[];uncertainties:string[]}
export interface AgentProductionPlan {
 id:string;revision:number;common_prompt:string;template_rules:Record<string,AssetUnderstanding>;garment_rules:Record<string,AssetUnderstanding>
 template_prompts?:Record<string,string>;analysis_mode?:'template_first'|'per_asset'
 combination_overrides:Array<{template_asset_id:string;garment_asset_id:string;instruction:string;font_reference_asset_id?:string|null}>
 unresolved_asset_ids:string[];confirmed:boolean;combination_count:number;samples:Record<string,string>;sample_approvals:Record<string,string>;production_batch_id:string|null
 sample_review_required?:boolean;sample_required_template_ids?:string[];input_manifest?:BatchInputManifest|null
 review_revision?:number;submitted_count?:number;submitted_combinations?:Record<string,string>;production_batches?:Array<{batch_id:string;template_ids:string[]}>
 sample_catalog?:Array<{sample_number:number;template_id:string;job_id:string|null;output_id:string|null;asset_id:string|null;status:string;approved:boolean;notes:string}>
}
export interface BatchInputEntry {asset_id:string;filename:string;role:AttachmentRole;garment_key:string;manual:boolean;analysis:Record<string,unknown>;enabled?:boolean;relative_path?:string;import_batch_id?:string;import_total_files?:number}
export interface BatchInputManifest {id:string;revision:number;entries:BatchInputEntry[];templates:Array<{asset_id:string;filename:string}>;garments:Array<{id:string;key:string;label:string;primary_asset_id:string;references:Record<string,string[]>}>;unresolved_asset_ids:string[];pairing_mode:'cartesian'|'paired'|'custom';pairs:Array<{template_asset_id:string;garment_id:string}>;combination_count:number;continuation_key?:string;continue_after_import?:boolean;crop_required_asset_ids?:string[];import_summary?:{complete:boolean;front_bound:number;back_bound:number;batches:Record<string,{received:number;total:number}>}}
export const getBatchInputs=(conversation:string)=>authenticatedFetch<BatchInputManifest|null>(`${root}/conversations/${conversation}/batch-inputs`)
export const saveBatchInputs=(conversation:string,m:BatchInputManifest,acceptPartial=false)=>authenticatedFetch<BatchInputManifest>(`${root}/conversations/${conversation}/batch-inputs`,{method:'PUT',body:JSON.stringify({expected_revision:m.revision,entries:m.entries,pairing_mode:m.pairing_mode,pairs:m.pairs,...(acceptPartial?{accept_partial_imports:true}:{})})})
export interface AgentConversationDetail extends AgentConversation { messages: AgentChatMessage[]; runs: AgentRun[]; attachments?: AgentAttachment[]; production_plans?:AgentProductionPlan[]; amazon_plans?:AmazonPlanRecord[];amazon_research?:AmazonReceipt[] }
export const saveAgentProductionRules=(conversation:string,p:AgentProductionPlan)=>authenticatedFetch<AgentProductionPlan>(`${root}/conversations/${conversation}/production-plans/${p.id}`,{method:'PUT',body:JSON.stringify({expected_revision:p.revision,common_prompt:p.common_prompt,template_rules:p.template_rules,garment_rules:p.garment_rules,combination_overrides:p.combination_overrides,...(p.template_prompts?{template_prompts:p.template_prompts}:{})})})
export const confirmAgentProductionRules=(conversation:string,p:AgentProductionPlan)=>authenticatedFetch<AgentProductionPlan>(`${root}/conversations/${conversation}/production-plans/${p.id}/confirm`,{method:'POST',body:JSON.stringify({expected_revision:p.revision})})
export const approveAgentSample=(conversation:string,p:AgentProductionPlan,outputId:string)=>authenticatedFetch<AgentProductionPlan>(`${root}/conversations/${conversation}/production-plans/${p.id}/approve-sample`,{method:'POST',body:JSON.stringify({output_id:outputId,expected_revision:p.revision})})
export interface AgentMessageInput {
  content: string; client_request_id: string; template_asset_ids: string[]; garment_asset_ids: string[]
  prompt: string; prompt_kind: 'final' | 'analysis'; template_type: string; garment_view: string
}
const root = '/agent'
export function agentRequestId() {
  return randomUuid()
}
export const getAgentStatus = (signal?: AbortSignal) => authenticatedFetch<AgentStatus>(`${root}/status`, { signal })
export const getAgentContexts = (signal?: AbortSignal) => authenticatedFetch<AgentContextOption[]>(`${root}/contexts`, { signal })
export const getAgentContext = (id: string, signal?: AbortSignal) => authenticatedFetch<AgentContext>(`${root}/contexts/${encodeURIComponent(id)}`, { signal })
export const listAgentConversations = (signal?: AbortSignal) => authenticatedFetch<AgentConversation[]>(`${root}/conversations`, { signal })
export const createAgentConversation = (projectId: string) => authenticatedFetch<AgentConversation>(`${root}/conversations`, {
  method: 'POST', body: JSON.stringify({ project_id: projectId, title: 'AI 总控', context_kind: 'batch_tryon' }),
})
export const createAgentChat = (projectId?: string,creativeModule?:CreativeModule) => authenticatedFetch<AgentConversation>(`${root}/conversations`, {
  method: 'POST', body: JSON.stringify({ context_kind: 'chat', title: '新的图片创作', project_id: projectId || null,...(creativeModule?{creative_module:creativeModule}:{}) }),
})
export const setAgentCreativeContext=(conversation:string,module:CreativeModule,revision:number)=>authenticatedFetch<CreativeContext>(`${root}/conversations/${conversation}/creative-context`,{method:'PUT',body:JSON.stringify({module,expected_revision:revision})})
export const attachAgentImage = (id: string, assetId: string, role: AttachmentRole = 'reference',importInfo?:MaterialImportInfo) => authenticatedFetch<AgentAttachment>(`${root}/conversations/${encodeURIComponent(id)}/attachments`, {
  method: 'POST', body: JSON.stringify({ asset_id: assetId, role,...(importInfo?{import_info:importInfo}:{}) }),
})
export const detachAgentImage = (id: string, attachmentId: string) => authenticatedFetch<void>(`${root}/conversations/${encodeURIComponent(id)}/attachments/${encodeURIComponent(attachmentId)}`, { method: 'DELETE' })
export const getAgentLibrary = (search = '') => authenticatedFetch<Array<{ id: string; filename: string; content_url: string; category: string }>>(`${root}/library?search=${encodeURIComponent(search)}`)
export interface SampleReviewInput {plan_id:string;expected_revision:number;expected_review_revision?:number;decisions:Array<{sample_number:number;output_id?:string;decision:'approve'|'revise'|'redo';notes?:string}>}
export const sendAgentChatMessage = (id: string, input: { content: string; client_request_id: string; attachment_ids: string[];use_batch_inputs?:boolean;creative_module?:CreativeModule; parent_output_id?: string | null;production_plan_id?:string;production_revision?:number;production_stage?:'validation'|'production';production_approved_only?:boolean;sample_review?:SampleReviewInput;amazon_plan_id?:string;amazon_revision?:number;amazon_module_ids?:string[];request_mode?:'create'|'suggest';reply_to_run_id?:string;reply_to_revision?:number;start_new_task?:boolean;review_before_generation?:boolean;prompt_source_run_id?:string;prompt_version_id?:string;retry_image_job_id?:string }) => authenticatedFetch<AgentRun>(`${root}/conversations/${encodeURIComponent(id)}/messages`, {
  method: 'POST', body: JSON.stringify({ ...input, chat_mode: true, auto_execute: true }),
})
export const saveAgentPrompt=(run:AgentRun,sourceId:string,content:string)=>authenticatedFetch<AgentRun>(`${root}/runs/${encodeURIComponent(run.id)}/prompts`,{
  method:'POST',body:JSON.stringify({expected_revision:run.revision,source_id:sourceId,content}),
})
export const getAgentConversation = (id: string, signal?: AbortSignal) => authenticatedFetch<AgentConversationDetail>(`${root}/conversations/${encodeURIComponent(id)}`, { signal })
export const sendAgentMessage = (id: string, input: AgentMessageInput) => authenticatedFetch<AgentRun>(`${root}/conversations/${encodeURIComponent(id)}/messages`, {
  method: 'POST', body: JSON.stringify(input),
})
export const getAgentRun = (id: string, signal?: AbortSignal) => authenticatedFetch<AgentRun>(`${root}/runs/${encodeURIComponent(id)}`, { signal, cache: 'no-store' })
export function confirmAgentRun(run: AgentRun) {
  if (!run.confirmation_token || !run.state_signature) return Promise.reject(new Error('请刷新并取得有效确认凭据。'))
  return authenticatedFetch<AgentRun>(`${root}/runs/${encodeURIComponent(run.id)}/confirm`, {
    method: 'POST', body: JSON.stringify({ expected_revision: run.revision, state_signature: run.state_signature, confirmation_token: run.confirmation_token }),
  })
}
export const stopAgentRun = (id: string) => authenticatedFetch<AgentRun>(`${root}/runs/${encodeURIComponent(id)}/stop`, { method: 'POST' })

export function canConfirmAgentRun(run: AgentRun, status: AgentStatus): boolean {
  if (!['awaiting_confirmation','awaiting_review'].includes(run.status) || !run.confirmation_token || !run.plan || run.planner_mode!==status.planner_mode) return false
  const writes = run.plan.actions.some(a => ['submit_tryon_batch', 'analyze_tryon_references', 'review_output', 'plan_intent', 'generate_chat_images', 'prepare_tryon_workspace','save_aplus_plan','revise_aplus_module','generate_aplus','research_amazon','analyze_chat_assets','generate_chat_tryon','suggest_creative_directions'].includes(a.tool))
  return !run.plan.blocked_reason && !run.plan.needs_input?.length && run.plan.budget?.sufficient !== false
    && (!writes || status.writes_enabled) && (!run.plan.may_charge || status.model_calls_enabled)
}

export const setAgentController = (controller: 'dsh'|'langgraph') => authenticatedFetch<{controller:'dsh'|'langgraph'}>(`${root}/controller`, {method:'PUT',body:JSON.stringify({controller})})

export const resumeAgentRun = (id: string) => authenticatedFetch<AgentRun>(`${root}/runs/${encodeURIComponent(id)}/resume`, {method:'POST'})
