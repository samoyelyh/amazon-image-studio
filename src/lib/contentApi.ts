import { authenticatedFetch, authenticatedFetchResponse } from './authApi'

export type UploadAssetCategory = 'product_reference' | 'model_template' | 'garment' | 'style_reference' | 'temporary' | 'print_asset'
export type GeneratedAssetCategory = 'listing_output' | 'batch_tryon_output' | 'aplus_output' | 'material_extract_output' | 'print_design_output'
export type AssetCategory = UploadAssetCategory | GeneratedAssetCategory
export type ProjectType = 'listing' | 'batch_tryon' | 'aplus' | 'print_design'

export interface Asset {
  id: string
  category: AssetCategory
  filename: string
  mime_type: string
  size: number
  width: number
  height: number
  sha256: string
  source_asset_id?: string | null
  metadata_json?: Record<string, unknown> | null
  created_by: string
  created_at: string
  updated_at: string
  url: string | null
  url_expires_at: string | null
}

export interface AssetPage { items: Asset[]; total: number; limit: number; offset: number }
export interface ProjectVersion { id: string; version_number: number; draft_json: Record<string, unknown>; change_summary: string | null; created_by: string; created_at: string }
export interface ProjectAsset {
  id: string
  role: string
  sort_order: number
  display_name: string | null
  is_default: boolean
  asset: Asset
  created_at: string
}
export interface ProjectAssetLinkMutation {
  id: string
  project_id: string
  asset_id: string
  role: string
  sort_order: number
  display_name: string | null
  is_default: boolean
  created_at: string
}
export interface Project {
  id: string
  project_type: ProjectType
  name: string
  description: string | null
  status: 'draft' | 'archived'
  created_by: string
  updated_by: string
  created_at: string
  updated_at: string
  latest_version: ProjectVersion
  assets: ProjectAsset[]
}
export interface ProjectPage { items: Project[]; total: number; limit: number; offset: number }

function params(values: Record<string, string | undefined>) {
  const query = new URLSearchParams()
  Object.entries(values).forEach(([key, value]) => { if (value) query.set(key, value) })
  const encoded = query.toString()
  return encoded ? `?${encoded}` : ''
}

export function listAssets(category?: GeneratedAssetCategory, search?: string) {
  return authenticatedFetch<AssetPage>(`/assets${params({ category, search })}`)
}

export function getAsset(assetId: string) {
  return authenticatedFetch<Asset>(`/assets/${assetId}`)
}

export function uploadAsset(file: File, category: UploadAssetCategory) {
  const body = new FormData()
  body.append('file', file)
  body.append('category', category)
  return authenticatedFetch<Asset>('/assets', { method: 'POST', body })
}

export function uploadGarmentReference(
  file: File,
  input: {
    sourceAssetId: string
    garmentView: 'front' | 'back' | 'detail'
    transformType: 'crop' | 'keep' | 'mask' | 'crop_mask'
    transformMetadata: Record<string, unknown>
  },
) {
  const body = new FormData()
  body.append('file', file)
  body.append('source_asset_id', input.sourceAssetId)
  body.append('garment_view', input.garmentView)
  body.append('transform_type', input.transformType)
  body.append('transform_metadata', JSON.stringify(input.transformMetadata))
  return authenticatedFetch<Asset>('/assets/garment-references', { method: 'POST', body })
}

export function uploadRegionReplaceReference(
  file: File,
  input: {
    sourceAssetId: string
    assetRole: 'target_edit_mask' | 'source_reference_mask' | 'reference_patch'
    transformMetadata: Record<string, unknown>
  },
) {
  const body = new FormData()
  body.append('file', file)
  body.append('source_asset_id', input.sourceAssetId)
  body.append('asset_role', input.assetRole)
  body.append('transform_metadata', JSON.stringify(input.transformMetadata))
  return authenticatedFetch<Asset>('/assets/region-replace-references', { method: 'POST', body })
}

export function uploadPrintDesignReference(
  file: File,
  input: {
    sourceAssetId: string
    assetRole: 'composite_input' | 'asset_alpha_mask' | 'replacement_mask' | 'protect_mask' | 'blend_mask'
    metadata?: Record<string, unknown>
  },
) {
  const body = new FormData()
  body.append('file', file)
  body.append('source_asset_id', input.sourceAssetId)
  body.append('asset_role', input.assetRole)
  body.append('metadata', JSON.stringify(input.metadata ?? {}))
  return authenticatedFetch<Asset>('/assets/print-design-references', { method: 'POST', body })
}

export function removeAsset(assetId: string) {
  return authenticatedFetch<void>(`/assets/${assetId}`, { method: 'DELETE' })
}

export async function fetchAssetBlob(url: string): Promise<Blob> {
  return (await authenticatedFetchResponse(url)).blob()
}

export function listProjects(projectType?: ProjectType, search?: string) {
  return authenticatedFetch<ProjectPage>(`/projects${params({ project_type: projectType, search })}`)
}

export function getProject(projectId: string) {
  return authenticatedFetch<Project>(`/projects/${projectId}`)
}

export function createProject(input: { project_type: ProjectType; name: string; description?: string; draft: Record<string, unknown> }) {
  return authenticatedFetch<Project>('/projects', { method: 'POST', body: JSON.stringify(input) })
}

export function saveProjectVersion(projectId: string, draft: Record<string, unknown>, expectedVersion: number, changeSummary?: string) {
  return authenticatedFetch<ProjectVersion>(`/projects/${projectId}/versions`, {
    method: 'POST',
    body: JSON.stringify({ draft, expected_version: expectedVersion, change_summary: changeSummary || undefined }),
  })
}

export function updateProject(projectId: string, input: Partial<Pick<Project, 'name' | 'description' | 'status'>>) {
  return authenticatedFetch<Project>(`/projects/${projectId}`, { method: 'PATCH', body: JSON.stringify(input) })
}

export function linkProjectAsset(
  projectId: string,
  assetId: string,
  role: string,
  sortOrder = 0,
  displayName?: string,
  isDefault = false,
) {
  return authenticatedFetch<Project>(`/projects/${projectId}/assets`, {
    method: 'POST',
    body: JSON.stringify({
      asset_id: assetId,
      role,
      sort_order: sortOrder,
      display_name: displayName,
      is_default: isDefault,
    }),
  })
}

export function linkProjectAssetCompact(
  projectId: string,
  assetId: string,
  role: string,
  sortOrder = 0,
  displayName?: string,
  isDefault = false,
) {
  return authenticatedFetch<ProjectAssetLinkMutation>(`/projects/${projectId}/asset-links`, {
    method: 'POST',
    body: JSON.stringify({
      asset_id: assetId,
      role,
      sort_order: sortOrder,
      display_name: displayName,
      is_default: isDefault,
    }),
  })
}

export function updateProjectAsset(
  projectId: string,
  linkId: string,
  input: { display_name?: string; is_default?: boolean; sort_order?: number },
) {
  return authenticatedFetch<Project>(`/projects/${projectId}/assets/${linkId}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  })
}

export function unlinkProjectAsset(projectId: string, linkId: string) {
  return authenticatedFetch<void>(`/projects/${projectId}/assets/${linkId}`, { method: 'DELETE' })
}

export function removeProject(projectId: string) {
  return authenticatedFetch<void>(`/projects/${projectId}`, { method: 'DELETE' })
}
