import { authenticatedFetch } from './authApi'


export interface AdminOverview {
  users_total: number
  users_active: number
  organizations_total: number
  organizations_active: number
  jobs_total: number
  jobs_active: number
  jobs_failed: number
  jobs_succeeded: number
  quota_balance_total: number
  quota_reserved_total: number
  providers_enabled: number
  pools_enabled: number
  keys_enabled: number
}

export interface AdminMembership {
  id: string
  organization_id: string
  organization_name: string
  role_code: string
  status: string
  invited_by: string | null
}

export interface AdminUser {
  id: string
  email: string
  display_name: string
  status: string
  auth_provider: string
  platform_role: string | null
  memberships: AdminMembership[]
  must_change_password: boolean
  password_changed_at: string | null
  temporary_password_created_at: string | null
  created_by: string | null
  last_login_at: string | null
  created_at: string
  updated_at: string
}

export interface AdminOrganization {
  id: string
  name: string
  slug: string
  status: string
  member_count: number
  job_count: number
  active_job_count: number
  quota_balance: number
  quota_reserved: number
  created_at: string
  updated_at: string
}

export interface AdminProvider {
  id: string
  code: string
  name: string
  provider_type: 'openai_compatible' | 'new_api' | 'custom'
  base_url: string
  enabled: boolean
  model_count: number
  key_count: number
}

export interface AdminProviderTest {
  provider_id: string
  test_type: 'base' | 'text_generation' | 'image_generation' | 'image_edit' | 'multi_image_reference'
  model_id: string | null
  success: boolean
  status_code: number | null
  error_code: string | null
  message: string
  models: string[]
  checked_at: string
}

export interface AdminModel {
  id: string
  provider_id: string
  code: string
  upstream_model: string
  name: string
  enabled: boolean
  capabilities: string[]
}

export interface AdminPool {
  id: string
  organization_id: string | null
  organization_name: string | null
  model_id: string
  model_code: string
  code: string
  name: string
  enabled: boolean
  priority: number
  weight: number
  key_ids: string[]
  operation_bindings: Record<string, string[]>
}

export interface AdminApiKey {
  id: string
  provider_id: string
  organization_id: string | null
  organization_name: string | null
  label: string
  masked_secret: string
  fingerprint: string
  enabled: boolean
  status: string
  max_concurrency: number
  rpm_limit: number | null
  daily_limit: number | null
  current_concurrency: number
  consecutive_failures: number
  cooldown_until: string | null
  last_used_at: string | null
}

export interface AdminResources {
  providers: AdminProvider[]
  models: AdminModel[]
  pools: AdminPool[]
  keys: AdminApiKey[]
}

export interface AdminJob {
  id: string
  organization_id: string
  organization_name: string
  operation_code: string
  workspace_type: string
  queue_name: string
  capability: string
  model_code: string
  status: string
  progress: number
  attempts: number
  max_attempts: number
  error_code: string | null
  error_message: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  generation_duration_ms: number
  requested_aspect_ratio: string | null
  requested_width: number | null
  requested_height: number | null
  resolved_provider_size: string | null
  submitted_dimension_field: string | null
  submitted_dimension_value: string | null
  actual_width: number | null
  actual_height: number | null
  size_mismatch: boolean
  resource_pool_id: string | null
  provider_id: string | null
  provider_model_id: string | null
  worker_name: string | null
  upstream_request_id: string | null
}

export interface AdminQueue {
  name: string
  broker_depth: number
  queued_jobs: number
  waiting_for_resource_jobs: number
  running_jobs: number
  retry_waiting_jobs: number
  failed_jobs: number
}

export interface GenerationResourceMetric {
  requests: number
  successes: number
  failures: number
  success_rate: number | null
  average_latency_ms: number | null
  p90_latency_ms: number | null
  hourly_successes: number
  http_429: number
  http_524: number
  http_5xx: number
  timeouts: number
  auth_errors: number
  last_success_at: string | null
  last_failure_at: string | null
  latest_error: string | null
}

export interface GenerationResourceDiagnostics {
  checked_at: string
  system: {
    configured_concurrency: number
    true_active_requests: number
    database_running: number
    database_dispatching: number
    redis_inflight: number
    worker_active_estimate: number
    worker_names: string[]
    queued: number
    waiting_for_resource: number
    retry_waiting: number
    recent_hour_successes: number
    remaining_jobs: number
    eta_minutes: number | null
    slot_mismatch: boolean
  }
  resource_pools: Array<GenerationResourceMetric & {
    id: string
    name: string
    code: string
    operation_codes: string[]
    model_code: string | null
    configured_capacity: number
    active: number
    idle: number
    waiting_jobs: number
    enabled: boolean
    health: string
  }>
  providers: Array<GenerationResourceMetric & {
    id: string
    name: string
    code: string
    base_url: string
    enabled: boolean
    configured_capacity: number
    effective_capacity: number
    active: number
    redis_active: number
    idle: number
    cooling_keys: number
    recovering_keys: number
    probe_active: number
    recovery_state: ResourceRecoveryState
    next_probe_at: string | null
    cooldown_remaining_seconds: number
    account_visibility: string
  }>
  keys: Array<GenerationResourceMetric & {
    id: string
    provider_id: string
    provider_name: string | null
    label: string
    masked_secret: string
    enabled: boolean
    status: string
    configured_capacity: number
    effective_capacity: number
    active: number
    redis_active: number
    cooldown_until: string | null
    cooldown_remaining_seconds: number
    next_probe_at: string | null
    consecutive_failures: number
    recovery_state: ResourceRecoveryState
    probe_active: boolean
    last_used_at: string | null
  }>
}

export type ResourceRecoveryState = 'healthy' | 'cooling' | 'waiting_probe' | 'probing' | 'disabled'

export interface AdminAudit {
  id: string
  organization_id: string | null
  actor_user_id: string | null
  action: string
  resource_type: string
  resource_id: string | null
  request_id: string | null
  ip_address: string | null
  metadata_json: Record<string, unknown> | null
  created_at: string
}

export interface AdminLoginAudit {
  id: string
  user_id: string | null
  organization_id: string | null
  email: string | null
  event: string
  outcome: string
  ip_address: string | null
  user_agent: string | null
  detail: string | null
  created_at: string
}

interface Page<T> { items: T[]; total: number; limit: number; offset: number }


export const getAdminOverview = () => authenticatedFetch<AdminOverview>('/admin/overview')
export const getAdminUsers = () => authenticatedFetch<Page<AdminUser>>('/admin/users?limit=200')
export const getAdminOrganizations = () => authenticatedFetch<Page<AdminOrganization>>('/admin/organizations?limit=200')
export const getAdminResources = () => authenticatedFetch<AdminResources>('/admin/resources')
export const getAdminJobs = () => authenticatedFetch<Page<AdminJob>>('/admin/jobs?limit=100')
export const getAdminQueues = () => authenticatedFetch<{ items: AdminQueue[]; redis_ok: boolean; checked_at: string }>('/admin/queues')
export const getGenerationResourceDiagnostics = () =>
  authenticatedFetch<GenerationResourceDiagnostics>('/admin/generation-resources')
export const getAdminAudits = () => authenticatedFetch<Page<AdminAudit>>('/admin/audit-logs?limit=100')
export const getAdminLoginAudits = () => authenticatedFetch<Page<AdminLoginAudit>>('/admin/login-audits?limit=100')

export const updateAdminUser = (id: string, input: { status?: 'active' | 'disabled'; platform_admin?: boolean; display_name?: string }) =>
  authenticatedFetch<AdminUser>(`/admin/users/${id}`, { method: 'PATCH', body: JSON.stringify(input) })

export const updateAdminOrganization = (id: string, input: { status?: 'active' | 'disabled'; name?: string }) =>
  authenticatedFetch<AdminOrganization>(`/admin/organizations/${id}`, { method: 'PATCH', body: JSON.stringify(input) })

export const adjustAdminQuota = (organizationId: string, input: { transaction_type: 'grant' | 'recharge' | 'adjust' | 'expire'; amount: number; idempotency_key: string; reason: string }) =>
  authenticatedFetch(`/admin/organizations/${organizationId}/quota-adjustments`, { method: 'POST', body: JSON.stringify(input) })

export const createAdminOrganization = (input: { name: string; slug: string }) =>
  authenticatedFetch('/organizations', { method: 'POST', body: JSON.stringify(input) })

export const createProvider = (input: { code: string; name: string; provider_type: string; base_url: string; config: Record<string, unknown> }) =>
  authenticatedFetch<AdminProvider>('/resource-pools/providers', { method: 'POST', body: JSON.stringify(input) })

export const createProviderModel = (providerId: string, input: { code: string; upstream_model: string; name: string; capabilities: string[]; config: Record<string, unknown> }) =>
  authenticatedFetch<AdminModel>(`/resource-pools/providers/${providerId}/models`, { method: 'POST', body: JSON.stringify(input) })

export const createResourcePool = (input: { model_id: string; code: string; name: string; organization_id?: string; priority: number; weight: number }) =>
  authenticatedFetch<AdminPool>('/resource-pools', { method: 'POST', body: JSON.stringify(input) })

export const createApiKey = (input: { provider_id: string; label: string; secret: string; organization_id?: string; max_concurrency: number; rpm_limit?: number; daily_limit?: number }) =>
  authenticatedFetch<AdminApiKey>('/resource-pools/keys', { method: 'POST', body: JSON.stringify(input) })

export const attachApiKey = (poolId: string, apiKeyId: string) =>
  authenticatedFetch<void>(`/resource-pools/${poolId}/keys`, { method: 'POST', body: JSON.stringify({ api_key_id: apiKeyId, priority: 100, weight: 100 }) })

export const attachOperation = (poolId: string, input: { operation_code: string; required_capability: string; organization_id?: string }) =>
  authenticatedFetch<void>(`/resource-pools/${poolId}/operations`, { method: 'POST', body: JSON.stringify({ ...input, priority: 100 }) })

export const toggleAdminResource = (type: 'providers' | 'models' | 'resource-pools' | 'api-keys', id: string, enabled: boolean) =>
  authenticatedFetch(`/admin/${type}/${id}`, { method: 'PATCH', body: JSON.stringify({ enabled }) })

export const testAdminProvider = (
  id: string,
  testType: AdminProviderTest['test_type'] = 'base',
  modelId?: string,
) => authenticatedFetch<AdminProviderTest>(`/admin/providers/${id}/test`, {
  method: 'POST',
  body: JSON.stringify({ test_type: testType, model_id: modelId }),
})
