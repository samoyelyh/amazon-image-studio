import { authenticatedFetch } from './authApi'

export type JobWorkspace = 'listing' | 'batch_tryon' | 'aplus' | 'material_extract' | 'print_design'
export type JobCapability = 'text_generation' | 'image_generation' | 'image_edit' | 'multi_image_reference' | 'mask_edit'

export interface JobOutput {
  id: string
  asset_id: string
  filename: string
  display_filename: string
  download_filename: string
  download_url: string
  mime_type: string
  width: number
  height: number
  size: number
  sequence_number: number
  url: string
  url_expires_at: string | null
}

export interface ServerJob {
  id: string
  organization_id: string
  batch_id: string | null
  project_id: string | null
  quota_reservation_id: string
  operation_code: string
  workspace_type: JobWorkspace
  queue_name: string
  capability: JobCapability
  model_code: string
  client_item_id: string | null
  status: string
  progress: number
  result_json: Record<string, unknown> | null
  attempts: number
  technical_retry_count: number
  max_attempts: number
  error_code: string | null
  error_message: string | null
  cancel_requested_at: string | null
  started_at: string | null
  heartbeat_at: string | null
  next_retry_at: string | null
  next_dispatch_at: string | null
  finished_at: string | null
  generation_duration_ms: number | null
  requested_aspect_ratio: string | null
  requested_width: number | null
  requested_height: number | null
  resolved_provider_size: string | null
  actual_width: number | null
  actual_height: number | null
  size_mismatch: boolean
  review_item_id: string | null
  review_status: string | null
  current_version_id: string | null
  approved_version_id: string | null
  regeneration_count: number
  review_version_id: string | null
  review_version_number: number | null
  is_current_review_version: boolean
  created_at: string
  updated_at: string
  outputs: JobOutput[]
}

export interface ServerJobPage { items: ServerJob[]; total: number; limit: number; offset: number }

export interface ServerJobBatch {
  id: string
  organization_id: string
  project_id: string | null
  workspace_type: JobWorkspace
  operation_code: string
  name: string | null
  parent_batch_id?: string | null
  batch_kind?: string | null
  model_code: string | null
  capability: JobCapability | null
  status: string
  concurrency: number
  admin_test_mode: boolean
  total_jobs: number
  succeeded_jobs: number
  failed_jobs: number
  cancelled_jobs: number
  cancel_requested_jobs?: number
  error_message: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
  updated_at: string
  jobs: ServerJob[]
  style_profiles?: Array<{
    id: string
    batch_id: string
    source_sample_asset_id: string
    profile_key: string
    category: string
    structure_json: Record<string, unknown>
    view_rules_json: Record<string, unknown>
    preservation_rules_json: Record<string, unknown>
    covered_garment_asset_ids_json: string[]
    first_sample_observation_json: Record<string, unknown> | null
    analysis_model: string | null
    analysis_version: string
  }>
}

export interface JobBatchHardDeleteResult {
  deleted_batches: number
  deleted_jobs: number
  deleted_outputs: number
  deleted_assets: number
  retained_shared_assets: number
  storage_delete_failures: number
}

export interface ServerJobBatchPage { items: ServerJobBatch[]; total: number; limit: number; offset: number }

export interface ServerJobBatchDiagnostics {
  batch_id: string
  status_counts: Record<string, number>
  configured_concurrency: number
  effective_concurrency: number
  actual_max_concurrency: number
  worker_concurrency: number
  active_jobs: number
  stale_jobs: number
  queue_name: string
  broker_queue_length: number
  online_workers: string[]
  resource_pool_ids: string[]
  resource_key_capacity: number
  resource_available_capacity: number
  attempts: number
  retries: number
  http_status_counts: Record<string, number>
  error_code_counts: Record<string, number>
  average_queue_wait_ms: number | null
  average_generation_ms: number | null
  latest_completed_at: string | null
  latest_error_code: string | null
  latest_error_message: string | null
  limitation_reasons: string[]
  availability_reasons: string[]
  resource_channels: Array<{
    provider_id: string
    provider_name: string
    provider_code: string
    key_id: string
    key_label: string
    recovery_state: 'healthy' | 'cooling' | 'waiting_probe' | 'probing' | 'disabled'
    configured_capacity: number
    effective_capacity: number
    active: number
    consecutive_failures: number
    cooldown_until: string | null
    cooldown_remaining_seconds: number
    probe_active: boolean
  }>
}

export interface ResourcePoolSummary {
  id: string
  model_code: string
  code: string
  name: string
  capabilities: string[]
  operation_bindings: Record<string, string[]>
  key_count: number
}

export interface JobSubmitInput {
  operation_code: string
  workspace_type: JobWorkspace
  queue_name: 'listing_queue' | 'batch_tryon_queue' | 'aplus_queue' | 'planning_queue'
  capability: JobCapability
  model_code: string
  idempotency_key: string
  project_id?: string
  input: Record<string, unknown>
  billing_factors?: Record<string, string>
  client_item_id?: string
}

export interface JobBatchSubmitInput {
  name: string
  workspace_type: JobWorkspace
  operation_code: string
  capability: JobCapability
  model_code: string
  idempotency_key: string
  project_id?: string
  concurrency: number
  admin_test_mode?: boolean
  items: Array<{
    client_item_id: string
    prompt: string
    reference_asset_ids: string[]
    mask_asset_id?: string
    size: string
    aspect_ratio?: string
    requested_width?: number
    requested_height?: number
    quality?: string
    output_format: 'png' | 'jpeg' | 'webp'
    output_compression?: number | null
    metadata?: Record<string, unknown>
  }>
}

function query(values: Record<string, string | number | boolean | undefined>) {
  const params = new URLSearchParams()
  Object.entries(values).forEach(([key, value]) => { if (value !== undefined && value !== '') params.set(key, String(value)) })
  const encoded = params.toString()
  return encoded ? `?${encoded}` : ''
}

export function listResourcePools() {
  return authenticatedFetch<ResourcePoolSummary[]>('/resource-pools')
}

export async function resolveModelCode(capability: JobCapability, operationCode?: string): Promise<string> {
  const pools = await listResourcePools()
  const matches = (item: ResourcePoolSummary) => item.capabilities.includes(capability)
    && (!operationCode || item.operation_bindings?.[operationCode]?.includes(capability))
  const pool = pools.find((item) => item.key_count > 0 && matches(item))
    ?? pools.find(matches)
  if (!pool) throw new Error(`平台暂未配置支持 ${capability} 的模型资源池，请联系管理员。`)
  if (pool.key_count < 1) throw new Error(`模型资源池「${pool.name}」尚未绑定可用 API Key，请联系管理员。`)
  return pool.model_code
}

export function submitServerJob(input: JobSubmitInput) {
  return authenticatedFetch<ServerJob>('/jobs', { method: 'POST', body: JSON.stringify(input) })
}

export function listServerJobs(options: { status?: string; limit?: number; offset?: number } = {}) {
  return authenticatedFetch<ServerJobPage>(`/jobs${query(options)}`)
}

export function getServerJob(jobId: string) {
  return authenticatedFetch<ServerJob>(`/jobs/${jobId}`)
}

export function getServerJobsByIds(jobIds: string[]) {
  return authenticatedFetch<ServerJob[]>('/jobs/batch-status', {
    method: 'POST',
    body: JSON.stringify({ job_ids: jobIds }),
  })
}

export function cancelServerJob(jobId: string) {
  return authenticatedFetch<ServerJob>(`/jobs/${jobId}/cancel`, { method: 'POST' })
}

export function submitServerBatch(input: JobBatchSubmitInput) {
  return authenticatedFetch<ServerJobBatch>('/job-batches', { method: 'POST', body: JSON.stringify(input) })
}

export function listServerBatches(options: {
  status?: string
  workspace_type?: JobWorkspace
  operation_code?: string
  project_id?: string
  include_jobs?: boolean
  limit?: number
  offset?: number
} = {}) {
  return authenticatedFetch<ServerJobBatchPage>(`/job-batches${query(options)}`)
}

export function getServerBatch(batchId: string) {
  return authenticatedFetch<ServerJobBatch>(`/job-batches/${batchId}`)
}

export function getServerBatchDiagnostics(batchId: string) {
  return authenticatedFetch<ServerJobBatchDiagnostics>(`/job-batches/${batchId}/diagnostics`)
}

export function cancelServerBatch(batchId: string) {
  return authenticatedFetch<ServerJobBatch>(`/job-batches/${batchId}/cancel`, { method: 'POST' })
}

export function pauseServerBatch(batchId: string) {
  return authenticatedFetch<ServerJobBatch>(`/job-batches/${batchId}/pause`, { method: 'POST' })
}

export function resumeServerBatch(batchId: string) {
  return authenticatedFetch<ServerJobBatch>(`/job-batches/${batchId}/resume`, { method: 'POST' })
}

export function isServerJobTerminal(status: string) {
  return status === 'succeeded' || status === 'failed' || status === 'cancelled'
}

export function hardDeleteServerBatch(batchId: string) {
  return authenticatedFetch<JobBatchHardDeleteResult>(
    `/job-batches/${batchId}/hard?confirmation=PERMANENT_DELETE`,
    { method: 'DELETE' },
  )
}

export function isWorkspaceShellBatch(batch: Pick<ServerJobBatch, 'batch_kind'>) {
  return batch.batch_kind === 'workspace'
}

export function isServerBatchCancelling(
  batch: Pick<ServerJobBatch, 'status' | 'cancel_requested_jobs'>,
) {
  return !isServerJobTerminal(batch.status) && Number(batch.cancel_requested_jobs || 0) > 0
}
