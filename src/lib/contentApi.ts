import { authenticatedFetch } from './authApi'

export type AssetCategory = 'product_reference' | 'model_template' | 'garment' | 'style_reference' | 'listing_output' | 'batch_tryon_output' | 'aplus_output' | 'temporary'
export type ProjectType = 'listing' | 'batch_tryon' | 'aplus'

export interface Asset {
  id: string
  category: AssetCategory
  filename: string
  mime_type: string
  size: number
  width: number
  height: number
  sha256: string
  created_by: string
  created_at: string
  updated_at: string
  url: string | null
  url_expires_at: string | null
}

export interface AssetPage { items: Asset[]; total: number; limit: number; offset: number }
export interface ProjectVersion { id: string; version_number: number; draft_json: Record<string, unknown>; change_summary: string | null; created_by: string; created_at: string }
export interface ProjectAsset { id: string; role: string; sort_order: number; asset: Asset; created_at: string }
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

export function listAssets(category?: AssetCategory, search?: string) {
  return authenticatedFetch<AssetPage>(`/assets${params({ category, search })}`)
}

export function uploadAsset(file: File, category: AssetCategory) {
  const body = new FormData()
  body.append('file', file)
  body.append('category', category)
  return authenticatedFetch<Asset>('/assets', { method: 'POST', body })
}

export function removeAsset(assetId: string) {
  return authenticatedFetch<void>(`/assets/${assetId}`, { method: 'DELETE' })
}

export function listProjects(projectType?: ProjectType, search?: string) {
  return authenticatedFetch<ProjectPage>(`/projects${params({ project_type: projectType, search })}`)
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

export function removeProject(projectId: string) {
  return authenticatedFetch<void>(`/projects/${projectId}`, { method: 'DELETE' })
}
