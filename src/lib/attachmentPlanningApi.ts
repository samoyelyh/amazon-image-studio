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
  supports_creative: boolean
  supports_multi_product: boolean
  supports_model: boolean
  derived_from_output_id: string | null
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
  generation_mode: 'standard' | 'creative' | string
  creative_direction_index: number | null
  derived_from_output_id: string | null
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
  product_composition_version_id: string | null
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
  keywords: string[]
  guidance: string
  library_item_id: string | null
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

export interface AttachmentProductIdentityLock {
  id: string
  version_number: number
  status: 'analyzing' | 'ready' | 'failed' | 'stale' | string
  structured: Record<string, unknown>
  ai_model: string | null
  error_message: string | null
  corrected_by_user: boolean
  created_at: string
}

export interface AttachmentProductCompositionAsset {
  id: string
  asset: Asset
  source_asset_id: string | null
  view_role: 'front' | 'back' | 'detail' | string
  sort_order: number
}

export interface AttachmentProductCompositionItem {
  id: string
  product_role: 'PRIMARY' | 'SECONDARY'
  source_session_id: string
  source_project_id: string | null
  display_name: string
  category_name: string
  display_order: number
  assets: AttachmentProductCompositionAsset[]
}

export interface AttachmentProductComposition {
  id: string
  module_key: AttachmentModuleCode
  mode: 'SINGLE' | 'MULTI'
  current_version_id: string
  current_version_number: number
  state_version: number
  products: AttachmentProductCompositionItem[]
}

export interface AttachmentPlanningModuleInput {
  module_key: AttachmentModuleCode
  aspect_ratio: string
  operator_requirement_cn: string
}

export interface AttachmentGenerationModulePreview {
  module_key: AttachmentModuleCode
  module_name: string
  aspect_ratio: string
  image_count: number
  generation_mode: string
  delivery_width: number
  delivery_height: number
  plan_version_id: string
  plan_version_number: number
  prompt_version_id: string
  prompt_version_number: number
  reference_understanding_id: string
  reference_understanding_version: number
  reference_count: number
  product_mode: 'SINGLE' | 'MULTI' | string
  product_count: number
  model_count: number
  products: Array<Record<string, unknown>>
  directions: AttachmentCreativeDirection[]
}

export interface AttachmentCreativeDirection {
  plan_version_id: string
  module_key: AttachmentModuleCode
  direction_index: number
  plan_summary_cn: string
  prompt_cn: string
  aspect_ratio: string
}

export interface AttachmentCreativePlanningResult {
  project_id: string
  planning_job_id: string
  status: 'queued' | 'running' | 'ready' | 'failed' | 'cancelled' | 'stale' | string
  error_message: string | null
  directions: AttachmentCreativeDirection[]
  created: boolean
}

export interface AttachmentGenerationPreview {
  project_id: string
  model_code: string
  modules: AttachmentGenerationModulePreview[]
  total_images: number
  snapshot_signature: string
}

export interface AttachmentGenerationResult {
  project_id: string
  batch_id: string
  task_group_id: string
  group_number: number
  status: string
  job_ids: string[]
  module_keys: AttachmentModuleCode[]
  total_images: number
  created: boolean
}

export interface AttachmentModuleResultState {
  module_key: AttachmentModuleCode
  current_final_output_id: string | null
  results_cleared_at: string | null
  state_version: number
  visible_output_count: number
  history_output_count: number
  pending_review_count: number
  approved_count: number
  rejected_count: number
}

export interface AttachmentResultState {
  project_id: string
  total_outputs: number
  reviewed_outputs: number
  final_module_count: number
  modules: AttachmentModuleResultState[]
}

export interface AttachmentOutputState {
  output_id: string
  module_key: AttachmentModuleCode
  review_status: 'pending_review' | 'approved' | 'rejected'
  review_state_version: number
  reviewed_at: string | null
  discarded_at: string | null
  is_final: boolean
  module_state_version: number
}

export function previewAttachmentGeneration(projectId: string, selectedModuleKeys: AttachmentModuleCode[], creativePlanningJobId?: string) {
  return authenticatedFetch<AttachmentGenerationPreview>(`/attachment-workbench/projects/${projectId}/generation-preview`, {
    method: 'POST', body: JSON.stringify({
      selected_module_keys: selectedModuleKeys,
      creative_planning_job_id: creativePlanningJobId || null,
    }),
  })
}

export function generateAttachments(projectId: string, input: {
  selected_module_keys: AttachmentModuleCode[]
  snapshot_signature: string
  idempotency_key: string
  creative_planning_job_id?: string
}) {
  return authenticatedFetch<AttachmentGenerationResult>(`/attachment-workbench/projects/${projectId}/generate`, {
    method: 'POST', body: JSON.stringify(input),
  })
}

export function startAttachmentCreativePlanning(projectId: string, selectedModuleKeys: AttachmentModuleCode[], idempotencyKey: string) {
  return authenticatedFetch<AttachmentCreativePlanningResult>(`/attachment-workbench/projects/${projectId}/creative-plans`, {
    method: 'POST', body: JSON.stringify({
      selected_module_keys: selectedModuleKeys,
      idempotency_key: idempotencyKey,
    }),
  })
}

export function getAttachmentCreativePlanning(projectId: string, planningJobId: string) {
  return authenticatedFetch<AttachmentCreativePlanningResult>(`/attachment-workbench/projects/${projectId}/creative-plans/${planningJobId}`)
}

export function adoptAttachmentCreativeDirection(projectId: string, outputId: string, expectedStateVersion: number) {
  return authenticatedFetch<AttachmentPlanningState>(`/attachment-workbench/projects/${projectId}/outputs/${outputId}/adopt-direction`, {
    method: 'POST', body: JSON.stringify({ expected_state_version: expectedStateVersion }),
  })
}

export function getAttachmentResultState(projectId: string) {
  return authenticatedFetch<AttachmentResultState>(`/attachment-workbench/projects/${projectId}/results`)
}

export function reviewAttachmentOutput(projectId: string, outputId: string, input: {
  status: 'approved' | 'rejected'
  expected_review_state_version: number
  clear_final_if_rejected?: boolean
}) {
  return authenticatedFetch<AttachmentOutputState>(`/attachment-workbench/projects/${projectId}/outputs/${outputId}/review`, {
    method: 'POST', body: JSON.stringify({ ...input, clear_final_if_rejected: input.clear_final_if_rejected || false }),
  })
}

export function setAttachmentFinal(projectId: string, outputId: string) {
  return authenticatedFetch<AttachmentOutputState>(`/attachment-workbench/projects/${projectId}/outputs/${outputId}/final`, {
    method: 'POST',
  })
}

export function clearAttachmentFinal(projectId: string, moduleKey: AttachmentModuleCode) {
  return authenticatedFetch<AttachmentResultState>(`/attachment-workbench/projects/${projectId}/modules/${moduleKey}/final`, {
    method: 'DELETE',
  })
}

export function discardAttachmentResults(projectId: string, moduleKeys: AttachmentModuleCode[]) {
  return authenticatedFetch<AttachmentResultState>(`/attachment-workbench/projects/${projectId}/discard-results`, {
    method: 'POST', body: JSON.stringify({ module_keys: moduleKeys }),
  })
}

export function resetAttachmentModule(projectId: string, moduleKey: AttachmentModuleCode) {
  return authenticatedFetch<AttachmentPlanningState>(`/attachment-workbench/projects/${projectId}/modules/${moduleKey}/reset`, {
    method: 'POST',
  })
}

export function retryAttachmentJob(projectId: string, jobId: string, idempotencyKey: string) {
  return authenticatedFetch<import('./listingWorkflowApi').ListingImageTaskGroup>(`/attachment-workbench/projects/${projectId}/jobs/${jobId}/retry`, {
    method: 'POST', body: JSON.stringify({ idempotency_key: idempotencyKey }),
  })
}

export function getAttachmentPlanning(projectId: string) {
  return authenticatedFetch<AttachmentPlanningState>(`/attachment-workbench/projects/${projectId}/planning`)
}

export function getAttachmentReferences(projectId: string) {
  return authenticatedFetch<AttachmentReferenceState>(`/attachment-workbench/projects/${projectId}/references`)
}

export function getAttachmentProductIdentityLock(projectId: string) {
  return authenticatedFetch<AttachmentProductIdentityLock>(`/attachment-workbench/projects/${projectId}/product-identity-lock`)
}

export function reextractAttachmentProductIdentityLock(projectId: string) {
  return authenticatedFetch<AttachmentProductIdentityLock>(`/attachment-workbench/projects/${projectId}/product-identity-lock/reextract`, {
    method: 'POST',
  })
}

export function updateAttachmentProductIdentityLock(projectId: string, structured: Record<string, unknown>) {
  return authenticatedFetch<AttachmentProductIdentityLock>(`/attachment-workbench/projects/${projectId}/product-identity-lock`, {
    method: 'PATCH', body: JSON.stringify({ structured }),
  })
}

export function getAttachmentProductCompositions(projectId: string) {
  return authenticatedFetch<AttachmentProductComposition[]>(`/attachment-workbench/projects/${projectId}/product-compositions`)
}

export function updateAttachmentProductMode(
  projectId: string, moduleKey: AttachmentModuleCode, mode: 'SINGLE' | 'MULTI', expectedStateVersion: number,
) {
  return authenticatedFetch<AttachmentProductComposition>(`/attachment-workbench/projects/${projectId}/modules/${moduleKey}/product-composition`, {
    method: 'PATCH', body: JSON.stringify({ mode, expected_state_version: expectedStateVersion }),
  })
}

export function addAttachmentSecondaryProduct(
  projectId: string, moduleKey: AttachmentModuleCode, sourceSessionId: string, expectedStateVersion: number,
) {
  return authenticatedFetch<AttachmentProductComposition>(`/attachment-workbench/projects/${projectId}/modules/${moduleKey}/product-composition/products`, {
    method: 'POST', body: JSON.stringify({ source_session_id: sourceSessionId, expected_state_version: expectedStateVersion }),
  })
}

export function replaceAttachmentSecondaryProduct(
  projectId: string, moduleKey: AttachmentModuleCode, itemId: string,
  sourceSessionId: string, expectedStateVersion: number,
) {
  return authenticatedFetch<AttachmentProductComposition>(`/attachment-workbench/projects/${projectId}/modules/${moduleKey}/product-composition/products/${itemId}`, {
    method: 'PUT', body: JSON.stringify({ source_session_id: sourceSessionId, expected_state_version: expectedStateVersion }),
  })
}

export function removeAttachmentSecondaryProduct(
  projectId: string, moduleKey: AttachmentModuleCode, itemId: string, expectedStateVersion: number,
) {
  return authenticatedFetch<AttachmentProductComposition>(`/attachment-workbench/projects/${projectId}/modules/${moduleKey}/product-composition/products/${itemId}?expected_state_version=${expectedStateVersion}`, {
    method: 'DELETE',
  })
}

export function addAttachmentReference(projectId: string, moduleKey: AttachmentModuleCode, input: {
  slot_type: AttachmentReferenceSlotType
  asset_id: string
  metadata?: Record<string, unknown>
  keywords?: string[]
  guidance?: string
  library_item_id?: string
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

export function updateAttachmentReferenceOptions(projectId: string, moduleKey: AttachmentModuleCode, referenceId: string, input: {
  keywords: string[]
  guidance: string
  expected_reference_state_version: number
}) {
  return authenticatedFetch<AttachmentReferenceState>(`/attachment-workbench/projects/${projectId}/modules/${moduleKey}/references/${referenceId}`, {
    method: 'PATCH', body: JSON.stringify(input),
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
