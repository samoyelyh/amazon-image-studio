import { authenticatedFetch } from './authApi'

export type JobWorkspace = 'listing' | 'batch_tryon' | 'aplus'
export type JobCapability = 'text_generation' | 'image_generation' | 'image_edit' | 'multi_image_reference' | 'mask_edit'

export interface JobOutput {
  id: string
  asset_id: string
  filename: string
  mime_type: string
  width: number
  height: number
  size: number
  sequence_number: number
  url: string
  url_expires_at: string
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
  max_attempts: number
  error_code: string | null
  error_message: string | null
  cancel_requested_at: string | null
  started_at: string | null
  heartbeat_at: string | null
  finished_at: string | null
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
  model_code: string | null
  capability: JobCapability | null
  status: string
  concurrency: number
  total_jobs: number
  succeeded_jobs: number
  failed_jobs: number
  cancelled_jobs: number
  error_message: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
  updated_at: string
  jobs: ServerJob[]
}

export interface ServerJobBatchPage { items: ServerJobBatch[]; total: number; limit: number; offset: number }

export interface ResourcePoolSummary {
  id: string
  model_code: string
  code: string
  name: string
  capabilities: string[]
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
  items: Array<{
    client_item_id: string
    prompt: string
    reference_asset_ids: string[]
    mask_asset_id?: string
    size: string
    quality?: string
    output_format: 'png' | 'jpeg' | 'webp'
    metadata?: Record<string, unknown>
  }>
}

function query(values: Record<string, string | number | undefined>) {
  const params = new URLSearchParams()
  Object.entries(values).forEach(([key, value]) => { if (value !== undefined && value !== '') params.set(key, String(value)) })
  const encoded = params.toString()
  return encoded ? `?${encoded}` : ''
}

export function listResourcePools() {
  return authenticatedFetch<ResourcePoolSummary[]>('/resource-pools')
}

export async function resolveModelCode(capability: JobCapability): Promise<string> {
  const pools = await listResourcePools()
  const pool = pools.find((item) => item.key_count > 0 && item.capabilities.includes(capability))
    ?? pools.find((item) => item.capabilities.includes(capability))
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

export function cancelServerJob(jobId: string) {
  return authenticatedFetch<ServerJob>(`/jobs/${jobId}/cancel`, { method: 'POST' })
}

export function submitServerBatch(input: JobBatchSubmitInput) {
  return authenticatedFetch<ServerJobBatch>('/job-batches', { method: 'POST', body: JSON.stringify(input) })
}

export function listServerBatches(options: { status?: string; limit?: number; offset?: number } = {}) {
  return authenticatedFetch<ServerJobBatchPage>(`/job-batches${query(options)}`)
}

export function getServerBatch(batchId: string) {
  return authenticatedFetch<ServerJobBatch>(`/job-batches/${batchId}`)
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
