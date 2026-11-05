import { authenticatedFetch } from './authApi'

export interface QueueWaitEstimate {
  minimum_seconds: number | null
  maximum_seconds: number | null
  sample_count: number
  reason: string
}
export interface SharedQueueEntry {
  id: string; name: string; creator_name: string; created_at: string; status: string
  total_count: number; completed_count: number; processed_count: number
  archived?: boolean; archived_at?: string | null
  running_count: number; waiting_count: number; failed_count: number; cancelled_count: number
  retrying_count: number; analysis_running: number; auxiliary_running: number
  ahead_count: number | null; progress_percent: number; can_open: boolean
  navigation: { project_id: string | null; workspace_id: string | null; batch_id: string | null } | null
  estimate: QueueWaitEstimate
}
export interface SharedQueueBoard {
  snapshot_at: string; entries: SharedQueueEntry[]; truncated: boolean
  running_count: number; waiting_count: number; failed_count: number; analysis_running: number
  capacity: { configured: number; effective: number; in_use: number; source: string; reason: string }
}
export function getSharedBatchTryOnQueue(signal?: AbortSignal, includeArchived = false) {
  return authenticatedFetch<SharedQueueBoard>(`/batch-tryon/queue?include_archived=${includeArchived}`, { signal, cache: 'no-store' })
}

export interface RetentionRule {
  enabled: boolean; days: number; age_basis: 'created_at' | 'last_activity'; action: 'archive' | 'pause_archive' | 'delete'
}
export interface RetentionSettings extends RetentionRule {
  revision: number; can_manage: boolean; last_run_at: string | null; last_run_summary: Record<string, number>; pending_storage_count: number
}
export interface RetentionPreview {
  eligible_count: number; batch_count: number; job_count: number; skipped: Record<string, number>
  samples: Array<{ id: string; name: string; reference_at: string }>; preview_token: string; per_run_limit: number
}
export const getRetentionSettings = () => authenticatedFetch<RetentionSettings>('/batch-tryon/queue/retention', { cache: 'no-store' })
export const previewRetention = (rule: RetentionRule) => authenticatedFetch<RetentionPreview>('/batch-tryon/queue/retention/preview', { method: 'POST', body: JSON.stringify(rule) })
export const saveRetention = (rule: RetentionRule, revision: number, confirmation: string) => authenticatedFetch<RetentionSettings>(
  '/batch-tryon/queue/retention', { method: 'PUT', body: JSON.stringify({ ...rule, expected_revision: revision, confirmation }) })
export const runRetention = (revision: number, token: string, confirmation: string) => authenticatedFetch<Record<string, number>>(
  '/batch-tryon/queue/retention/run', { method: 'POST', body: JSON.stringify({ expected_revision: revision, preview_token: token, confirmation }) })
export const restoreQueueBatch = (id: string) => authenticatedFetch(`/batch-tryon/queue/${encodeURIComponent(id)}/restore`, { method: 'POST' })
export function formatQueueWait(estimate: QueueWaitEstimate): string {
  if (estimate.minimum_seconds == null || estimate.maximum_seconds == null) return '暂无可靠估计'
  if (estimate.maximum_seconds <= 15) return '预计即将调度'
  return `约 ${Math.floor(estimate.minimum_seconds / 60)}–${Math.ceil(estimate.maximum_seconds / 60)} 分钟`
}
