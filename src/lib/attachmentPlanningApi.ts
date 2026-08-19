import { authenticatedFetch } from './authApi'
import type { AttachmentModuleCode } from './attachmentImageWorkbench'
import type { Asset } from './contentApi'

export interface AttachmentSkillSource {
  skill_name: string
  skill_version_id: string | null
  skill_version_number: number | null
  can_view_rules: boolean
  module_rule: Record<string, unknown> | null
}

export interface AttachmentModulePlan {
  id: string
  module_key: AttachmentModuleCode
  module_name: string
  plan_summary_cn: string
  prompt_cn: string
  operator_requirement_cn: string
  aspect_ratio: string
  source: string
  current_version_number: number
  status: string
  planning_job_id: string | null
  error_message: string | null
  reference_context_dirty: boolean
  reference_state_version: number
  reference_analysis_job_id: string | null
  state_version: number
  last_saved_at: string | null
  skill_source: AttachmentSkillSource
}

export interface AttachmentPlanningState {
  id: string
  project_id: string
  session_id: string
  visual_direction_cn: string
  visual_direction_source: string
  visual_direction_version: number
  planning_status: string
  planning_job_id: string | null
  error_message: string | null
  state_version: number
  last_saved_at: string | null
  modules: AttachmentModulePlan[]
}

export interface AttachmentPlanVersion {
  id: string
  version_scope: string
  module_key: AttachmentModuleCode | null
  version_number: number
  action: string
  visual_direction_cn: string | null
  plan_summary_cn: string | null
  prompt_cn: string | null
  operator_requirement_cn: string
  aspect_ratio: string | null
  selected_module_keys: string[]
  skill_version_id: string | null
  source_version_id: string | null
  ai_job_id: string | null
  ai_model: string | null
  reference_understanding_id: string | null
  created_by: string
  created_at: string
}

export type AttachmentReferenceSlotType = 'PRODUCT' | 'TEMPLATE' | 'SCENE' | 'PRINT' | 'OTHER'

export interface AttachmentReferenceUnderstanding {
  id: string
  version_number: number
  status: string
  structured: Record<string, unknown>
  source_snapshot: Record<string, unknown>
  ai_job_id: string | null
  ai_model: string | null
  error_message: string | null
  created_at: string
}

export interface AttachmentProductReferenceItem {
  id: string
  asset: Asset
  source_asset_id: string | null
  view_role: 'front' | 'back' | 'detail'
  sort_order: number
  source: 'session' | 'override'
  transform_metadata: Record<string, unknown>
}

export interface AttachmentModuleReference {
  id: string
  slot_type: AttachmentReferenceSlotType
  asset: Asset
  sort_order: number
  metadata: Record<string, unknown>
}

export interface AttachmentModuleReferenceState {
  module_key: AttachmentModuleCode
  slot_definitions: Array<{
    slot_type: AttachmentReferenceSlotType
    required: boolean
    recommended: boolean
    max_items: number
  }>
  references: AttachmentModuleReference[]
  reference_context_dirty: boolean
  reference_state_version: number
  reference_analysis_job_id: string | null
  understanding: AttachmentReferenceUnderstanding | null
}

export interface AttachmentReferenceState {
  product_group_id: string
  product_state_version: number
  product_references: AttachmentProductReferenceItem[]
  modules: AttachmentModuleReferenceState[]
}

export interface AttachmentPlanningModuleInput {
  module_key: AttachmentModuleCode
  aspect_ratio: string
  operator_requirement_cn: string
}

export function getAttachmentPlanning(projectId: string) {
  return authenticatedFetch<AttachmentPlanningState>(`/attachment-workbench/projects/${projectId}/planning`)
}

export function getAttachmentReferences(projectId: string) {
  return authenticatedFetch<AttachmentReferenceState>(`/attachment-workbench/projects/${projectId}/references`)
}

export function addAttachmentReference(projectId: string, moduleKey: AttachmentModuleCode, input: {
  slot_type: AttachmentReferenceSlotType
  asset_id: string
  metadata?: Record<string, unknown>
}) {
  return authenticatedFetch<AttachmentReferenceState>(`/attachment-workbench/projects/${projectId}/modules/${moduleKey}/references`, {
    method: 'POST', body: JSON.stringify({ ...input, metadata: input.metadata || {} }),
  })
}

export function removeAttachmentReference(projectId: string, moduleKey: AttachmentModuleCode, referenceId: string) {
  return authenticatedFetch<AttachmentReferenceState>(`/attachment-workbench/projects/${projectId}/modules/${moduleKey}/references/${referenceId}`, {
    method: 'DELETE',
  })
}

export function analyzeAttachmentReferences(projectId: string, moduleKey: AttachmentModuleCode, idempotencyKey: string) {
  return authenticatedFetch<AttachmentReferenceState>(`/attachment-workbench/projects/${projectId}/modules/${moduleKey}/references/analyze`, {
    method: 'POST', body: JSON.stringify({ idempotency_key: idempotencyKey }),
  })
}

export function putAttachmentProductReference(projectId: string, input: {
  asset_id: string
  source_asset_id?: string
  view_role: 'front' | 'back' | 'detail'
  transform_metadata?: Record<string, unknown>
}) {
  return authenticatedFetch<AttachmentReferenceState>(`/attachment-workbench/projects/${projectId}/product-references/${input.view_role}`, {
    method: 'PUT', body: JSON.stringify({ ...input, transform_metadata: input.transform_metadata || {} }),
  })
}

export function planAttachmentSuite(projectId: string, input: {
  modules: AttachmentPlanningModuleInput[]
  visual_direction_cn: string
  idempotency_key: string
}) {
  return authenticatedFetch<AttachmentPlanningState>(`/attachment-workbench/projects/${projectId}/plan`, {
    method: 'POST', body: JSON.stringify(input),
  })
}

export function replanAttachmentModule(projectId: string, moduleKey: AttachmentModuleCode, input: {
  aspect_ratio: string
  operator_requirement_cn: string
  idempotency_key: string
}) {
  return authenticatedFetch<AttachmentPlanningState>(`/attachment-workbench/projects/${projectId}/modules/${moduleKey}/replan`, {
    method: 'POST', body: JSON.stringify(input),
  })
}

export function optimizeAttachmentModulePrompt(projectId: string, moduleKey: AttachmentModuleCode, input: {
  aspect_ratio: string
  operator_requirement_cn: string
  idempotency_key: string
}) {
  return authenticatedFetch<AttachmentPlanningState>(`/attachment-workbench/projects/${projectId}/modules/${moduleKey}/optimize-prompt`, {
    method: 'POST', body: JSON.stringify(input),
  })
}

export function updateAttachmentVisualDirection(projectId: string, input: {
  visual_direction_cn: string
  expected_state_version: number
}) {
  return authenticatedFetch<AttachmentPlanningState>(`/attachment-workbench/projects/${projectId}/visual-direction`, {
    method: 'PATCH', body: JSON.stringify(input),
  })
}

export function updateAttachmentModule(projectId: string, moduleKey: AttachmentModuleCode, input: {
  plan_summary_cn?: string
  prompt_cn?: string
  operator_requirement_cn?: string
  aspect_ratio?: string
  expected_state_version: number
}) {
  return authenticatedFetch<AttachmentPlanningState>(`/attachment-workbench/projects/${projectId}/modules/${moduleKey}`, {
    method: 'PATCH', body: JSON.stringify(input),
  })
}

export function listAttachmentPlanVersions(projectId: string, moduleKey?: AttachmentModuleCode) {
  const suffix = moduleKey ? `?module_key=${encodeURIComponent(moduleKey)}` : ''
  return authenticatedFetch<AttachmentPlanVersion[]>(`/attachment-workbench/projects/${projectId}/versions${suffix}`)
}
