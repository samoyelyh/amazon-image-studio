import { authenticatedFetch } from './authApi'
import type { JobBatchHardDeleteResult } from './jobsApi'

export type BatchTryOnWorkspaceStatus = 'draft' | 'validating' | 'ready' | 'queued' | 'running' | 'review' | 'completed' | 'failed'

export interface BatchTryOnWorkspaceTab {
  id: string
  project_id: string | null
  name: string
  status: BatchTryOnWorkspaceStatus
  hidden: boolean
  config: Record<string, unknown>
  production_batch_ids: string[]
  validation_batch_ids: string[]
  total_jobs: number
  completed_jobs: number
  created_at: string
  updated_at: string
}

export function listBatchTryOnWorkspaces(projectId: string, includeHidden = false) {
  return authenticatedFetch<{ items: BatchTryOnWorkspaceTab[]; total: number }>(
    `/batch-tryon/workspaces?project_id=${encodeURIComponent(projectId)}&include_hidden=${includeHidden}`,
    { cache: 'no-store' },
  )
}

export function createBatchTryOnWorkspace(projectId: string, name?: string, config: Record<string, unknown> = {}) {
  return authenticatedFetch<BatchTryOnWorkspaceTab>('/batch-tryon/workspaces', {
    method: 'POST', body: JSON.stringify({ project_id: projectId, name, config }),
  })
}

export function updateBatchTryOnWorkspace(
  workspaceId: string,
  patch: { name?: string; status?: BatchTryOnWorkspaceStatus; config?: Record<string, unknown> },
) {
  return authenticatedFetch<BatchTryOnWorkspaceTab>(`/batch-tryon/workspaces/${workspaceId}`, {
    method: 'PATCH', body: JSON.stringify(patch),
  })
}

export function hideBatchTryOnWorkspace(workspaceId: string) {
  return authenticatedFetch<BatchTryOnWorkspaceTab>(`/batch-tryon/workspaces/${workspaceId}/hide`, { method: 'POST' })
}

export function deleteBatchTryOnWorkspace(workspaceId: string) {
  return authenticatedFetch<void>(`/batch-tryon/workspaces/${workspaceId}`, { method: 'DELETE' })
}

export function hardDeleteBatchTryOnWorkspace(workspaceId: string) {
  return authenticatedFetch<JobBatchHardDeleteResult>(
    `/batch-tryon/workspaces/${workspaceId}/hard?confirmation=PERMANENT_DELETE`,
    { method: 'DELETE' },
  )
}
