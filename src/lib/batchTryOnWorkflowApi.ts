import { authenticatedFetch } from './authApi'
import type { BatchTryOnPresetSelection } from '../types'

export type BatchTryOnGenerationMode = 'normal_tryon' | 'detail_tryon'
export type BatchTryOnPromptMode = 'direct' | 'ai_analysis' | 'ai_detailed'
export type BatchTryOnPromptStatus = 'draft' | 'analyzing' | 'ready' | 'effective' | 'stale' | 'failed'
export type BatchTryOnTemplateType =
  | 'pure_white'
  | 'gift_scene'
  | 'stadium_scene'
  | 'detail_display'
  | 'casual_scene'
  | 'custom_process'

export interface BatchTryOnPromptPreset {
  id: string
  scope: 'system' | 'organization' | 'user'
  organization_id: string | null
  owner_user_id: string | null
  template_type: BatchTryOnTemplateType
  label: string
  analysis_prompt_template: string
  enabled: boolean
  sort_order: number
  is_system_preset: boolean
}

export interface BatchTryOnTemplatePrompt {
  id: string
  workflow_job_id: string
  template_id: string
  garment_id: string | null
  client_item_id: string | null
  template_type: BatchTryOnTemplateType
  preset_id: string | null
  template_asset_id: string
  first_garment_asset_id: string
  font_reference_asset_id: string | null
  analysis_job_id: string | null
  analysis_prompt_used: string
  generated_final_prompt: string | null
  edited_final_prompt: string | null
  prompt_status: BatchTryOnPromptStatus
  prompt_version: number
  error_code: string | null
  error_message: string | null
}

export interface BatchTryOnWorkflowGarmentProfile {
  profile_key: string
  source_sample_asset_id: string
  category: string
  garment_structure: Record<string, unknown>
  view_rules: Record<string, unknown>
  design_rules: Record<string, unknown>
  structure_rules: Record<string, unknown>
  analysis_model: string
  analysis_version: string
  observation?: Record<string, unknown>
}

export interface BatchTryOnWorkflowInput {
  project_id: string
  name: string
  idempotency_key: string
  generation_mode: BatchTryOnGenerationMode
  prompt_mode: BatchTryOnPromptMode
  templates: Array<{
    template_id: string
    asset_id: string
    name: string
    order: number
    focus_area?: string
    crop_type?: string
    detail_priority?: string
    visible_regions?: string[]
    template_type?: BatchTryOnTemplateType
    prompt_preset_id?: string
    analysis_prompt?: string
    garment_view?: 'auto' | 'front' | 'back' | 'front_back' | 'detail'
  }>
  garments: Array<{
    garment_id: string
    asset_id: string
    filename: string
    order: number
    font_reference_asset_id?: string
    front_reference_asset_id?: string
    back_reference_asset_id?: string
    detail_reference_asset_id?: string
  }>
  combinations: Array<{
    client_item_id: string
    template_id: string
    garment_id: string
    order: number
    size?: string
    aspect_ratio?: string
    requested_width?: number
    requested_height?: number
    font_reference_asset_id?: string
  }>
  preset_selection: BatchTryOnPresetSelection
  extra_requirements: string
  size: string
  aspect_ratio: string
  requested_width?: number
  requested_height?: number
  quality: string
  output_format: 'png' | 'jpeg' | 'webp'
  output_compression?: number | null
  concurrency: number
  admin_test_mode: boolean
  workspace_batch_id?: string
  submission_kind?: 'validation' | 'production'
}

export interface BatchTryOnWorkflowResponse {
  workflow_job_id: string
  project_id: string | null
  generation_mode: BatchTryOnGenerationMode
  prompt_mode: BatchTryOnPromptMode
  submission_kind: 'validation' | 'production'
  workspace_batch_id: string | null
  status: 'analyzing_garment' | 'analyzing_templates' | 'analyzing_prompts' | 'awaiting_prompt_confirmation' | 'submitting_batch' | 'generating' | 'completed' | 'failed' | 'cancelled'
  analysis_call_target: number
  analysis_jobs: Array<{
    id: string
    role: 'garment_analysis' | 'template_analysis' | 'prompt_analysis' | 'detailed_prompt_analysis'
    status: string
    error_code: string | null
    error_message: string | null
  }>
  templates: BatchTryOnWorkflowInput['templates']
  garments: BatchTryOnWorkflowInput['garments']
  combinations: BatchTryOnWorkflowInput['combinations']
  garment_profile: BatchTryOnWorkflowGarmentProfile | null
  template_profiles: Record<string, Record<string, unknown>>
  template_prompts: BatchTryOnTemplatePrompt[]
  batch_id: string | null
  error_code: string | null
  error_message: string | null
  created_at: string
  updated_at: string
}

export function resolveValidationWorkflowTemplateId(workflow: BatchTryOnWorkflowResponse) {
  if (workflow.submission_kind !== 'validation') return undefined
  return workflow.combinations[0]?.template_id || workflow.templates[0]?.template_id
}

export function createBatchTryOnWorkflow(input: BatchTryOnWorkflowInput) {
  return authenticatedFetch<BatchTryOnWorkflowResponse>('/batch-tryon/workflows', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function getBatchTryOnWorkflow(workflowJobId: string) {
  return authenticatedFetch<BatchTryOnWorkflowResponse>(`/batch-tryon/workflows/${workflowJobId}`)
}

export function getLatestBatchTryOnWorkflow(projectId: string, workspaceBatchId?: string) {
  const query = new URLSearchParams({ project_id: projectId })
  if (workspaceBatchId) query.set('workspace_batch_id', workspaceBatchId)
  return authenticatedFetch<BatchTryOnWorkflowResponse>(`/batch-tryon/workflows?${query.toString()}`)
}

export function listBatchTryOnPromptPresets() {
  return authenticatedFetch<BatchTryOnPromptPreset[]>('/batch-tryon/prompt-presets')
}

export function createBatchTryOnPromptPreset(input: {
  template_type: BatchTryOnTemplateType
  label: string
  analysis_prompt_template: string
}) {
  return authenticatedFetch<BatchTryOnPromptPreset>('/batch-tryon/prompt-presets', {
    method: 'POST', body: JSON.stringify(input),
  })
}

export function updateBatchTryOnPromptPreset(
  presetId: string,
  input: {
    label?: string
    analysis_prompt_template?: string
    enabled?: boolean
    sort_order?: number
  },
) {
  return authenticatedFetch<BatchTryOnPromptPreset>(
    `/batch-tryon/prompt-presets/${encodeURIComponent(presetId)}`,
    { method: 'PATCH', body: JSON.stringify(input) },
  )
}

export function confirmBatchTryOnTemplatePrompt(
  workflowJobId: string, templateId: string, editedFinalPrompt: string | null,
) {
  return authenticatedFetch<BatchTryOnTemplatePrompt>(
    `/batch-tryon/workflows/${workflowJobId}/template-prompts/${encodeURIComponent(templateId)}`,
    { method: 'PATCH', body: JSON.stringify({ edited_final_prompt: editedFinalPrompt }) },
  )
}

export function reanalyzeBatchTryOnTemplatePrompt(
  workflowJobId: string, templateId: string, analysisPrompt: string,
) {
  return authenticatedFetch<BatchTryOnTemplatePrompt>(
    `/batch-tryon/workflows/${workflowJobId}/template-prompts/${encodeURIComponent(templateId)}/analyze`,
    { method: 'POST', body: JSON.stringify({ analysis_prompt: analysisPrompt }) },
  )
}

export function submitConfirmedBatchTryOnWorkflow(workflowJobId: string, idempotencyKey: string) {
  return authenticatedFetch<BatchTryOnWorkflowResponse>(`/batch-tryon/workflows/${workflowJobId}/submit`, {
    method: 'POST', body: JSON.stringify({ idempotency_key: idempotencyKey }),
  })
}
