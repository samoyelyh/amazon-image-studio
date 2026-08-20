import { authenticatedFetch } from './authApi'
import type { Asset } from './contentApi'
import { downloadAuthenticatedFile } from './serverDownloads'

export interface AttachmentMaterialItem {
  id: string
  module_key: string
  source_output_id: string | null
  source_asset_id: string
  source_task_group_id: string | null
  source_job_id: string | null
  plan_version_id: string | null
  prompt_version_id: string | null
  reference_understanding_id: string | null
  product_composition_version_id: string | null
  aspect_ratio: string
  output_size: string
  generation_mode: string
  product_mode: string
  is_manual_revision: boolean
  created_at: string
  asset: Asset
}

export interface AttachmentMaterialVersion {
  id: string
  version_number: number
  content_hash: string
  selected_module_snapshot: string[]
  module_count: number
  target_module_count: number
  is_complete: boolean
  changed_module_keys: string[]
  created_by: string
  created_at: string
  items: AttachmentMaterialItem[]
}

export interface AttachmentMaterialSetSummary {
  id: string
  category_key: string
  category_name: string
  product_name: string
  display_name: string
  source_session_id: string | null
  source_project_id: string | null
  cover_asset_id: string | null
  selected_module_snapshot: string[]
  tags: string[]
  note: string
  is_complete: boolean
  status: string
  current_version_number: number
  module_count: number
  target_module_count: number
  owner_user_id: string
  created_at: string
  updated_at: string
  cover_asset: Asset | null
}

export interface AttachmentMaterialSetDetail extends AttachmentMaterialSetSummary {
  current_version_id: string | null
  versions: AttachmentMaterialVersion[]
}

export interface AttachmentMaterialSetPage {
  items: AttachmentMaterialSetSummary[]
  total: number
  limit: number
  offset: number
}

export interface AttachmentMaterialSaveContext {
  project_id: string
  default_name: string
  existing_material_set_id: string | null
  existing_display_name: string | null
  suggested_tags: string[]
  existing_note?: string
}

export interface AttachmentMaterialSaveInput {
  display_name: string
  tags: string[]
  note: string
  material_set_id?: string | null
  save_mode: 'update_existing' | 'new'
}

export interface AttachmentMaterialSaveResult {
  material_set: AttachmentMaterialSetDetail
  created_set: boolean
  created_version: boolean
  unchanged: boolean
}

function queryString(values: Record<string, string | boolean | undefined>) {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(values)) if (value !== undefined && value !== '') query.set(key, String(value))
  const encoded = query.toString()
  return encoded ? `?${encoded}` : ''
}

export function getAttachmentMaterialSaveContext(projectId: string) {
  return authenticatedFetch<AttachmentMaterialSaveContext>(`/attachment-materials/projects/${projectId}/save-context`)
}

export function saveAttachmentMaterialSet(projectId: string, input: AttachmentMaterialSaveInput) {
  return authenticatedFetch<AttachmentMaterialSaveResult>(`/attachment-materials/projects/${projectId}/save`, {
    method: 'POST', body: JSON.stringify(input),
  })
}

export function saveAttachmentMaterialOutput(projectId: string, outputId: string, input: AttachmentMaterialSaveInput) {
  return authenticatedFetch<AttachmentMaterialSaveResult>(`/attachment-materials/projects/${projectId}/outputs/${outputId}/save`, {
    method: 'POST', body: JSON.stringify(input),
  })
}

export function listAttachmentMaterialSets(input: {
  search?: string
  category_key?: string
  completion?: 'complete' | 'incomplete'
  include_archived?: boolean
  scope?: 'mine' | 'organization'
} = {}) {
  return authenticatedFetch<AttachmentMaterialSetPage>(`/attachment-materials${queryString(input)}`)
}

export function getAttachmentMaterialSet(materialSetId: string) {
  return authenticatedFetch<AttachmentMaterialSetDetail>(`/attachment-materials/${materialSetId}`)
}

export function updateAttachmentMaterialSet(materialSetId: string, input: Pick<AttachmentMaterialSaveInput, 'display_name' | 'tags' | 'note'>) {
  return authenticatedFetch<AttachmentMaterialSetDetail>(`/attachment-materials/${materialSetId}`, {
    method: 'PATCH', body: JSON.stringify(input),
  })
}

export function archiveAttachmentMaterialSet(materialSetId: string) {
  return authenticatedFetch<AttachmentMaterialSetDetail>(`/attachment-materials/${materialSetId}/archive`, { method: 'POST' })
}

export function downloadAttachmentMaterialVersion(materialSetId: string, versionNumber: number, fallbackName: string) {
  return downloadAuthenticatedFile(
    `/attachment-materials/${materialSetId}/versions/${versionNumber}/download`,
    `${fallbackName}_V${versionNumber}.zip`,
  )
}
