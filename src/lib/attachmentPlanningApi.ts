import { authenticatedFetch } from './authApi'
import type { AttachmentModuleCode } from './attachmentImageWorkbench'

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
  created_by: string
  created_at: string
}

export interface AttachmentPlanningModuleInput {
  module_key: AttachmentModuleCode
  aspect_ratio: string
  operator_requirement_cn: string
}

export function getAttachmentPlanning(projectId: string) {
  return authenticatedFetch<AttachmentPlanningState>(`/attachment-workbench/projects/${projectId}/planning`)
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
