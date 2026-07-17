import { runtimeConfig } from '../app/runtimeConfig'

export interface AuthUser {
  id: string
  email: string
  display_name: string
  status: string
  auth_provider: string
  created_at: string
  updated_at: string
}

export interface AuthOrganization {
  id: string
  name: string
  slug: string
  status: string
  created_at: string
  updated_at: string
}

export interface AuthRole {
  id: string
  code: string
  name: string
  scope: string
  permissions: string[]
}

export interface AuthMembership {
  id: string
  user: AuthUser
  organization: AuthOrganization
  role: AuthRole
  status: string
  created_at: string
}

export interface CurrentIdentity {
  user: AuthUser
  organization: AuthOrganization | null
  role_codes: string[]
  permissions: string[]
  memberships: AuthMembership[]
}

export interface AuthSessionResponse {
  access_token: string
  token_type: 'bearer'
  expires_in: number
  identity: CurrentIdentity
}

interface ApiErrorPayload {
  error?: { code?: string; message?: string }
  detail?: Array<{ msg?: string }>
}

export class AuthApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message)
  }
}

const apiBaseUrl = runtimeConfig.apiBaseUrl || '/api/v1'
let accessToken: string | null = null
let refreshPromise: Promise<AuthSessionResponse> | null = null

async function parseResponse<T>(response: Response): Promise<T> {
  if (response.ok) return response.status === 204 ? undefined as T : response.json() as Promise<T>
  const payload = await response.json().catch(() => ({})) as ApiErrorPayload
  throw new AuthApiError(
    response.status,
    payload.error?.code || 'request.failed',
    payload.error?.message || payload.detail?.[0]?.msg || '请求失败，请稍后重试',
  )
}

async function sessionRequest(path: string, body?: unknown): Promise<AuthSessionResponse> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    method: 'POST',
    credentials: 'include',
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  const session = await parseResponse<AuthSessionResponse>(response)
  accessToken = session.access_token
  return session
}

export async function login(email: string, password: string): Promise<AuthSessionResponse> {
  return sessionRequest('/auth/login', { email, password })
}

export async function refreshSession(): Promise<AuthSessionResponse> {
  if (!refreshPromise) {
    refreshPromise = sessionRequest('/auth/refresh').finally(() => { refreshPromise = null })
  }
  return refreshPromise
}

export async function switchOrganization(organizationId: string): Promise<AuthSessionResponse> {
  return sessionRequest('/auth/switch-organization', { organization_id: organizationId })
}

export async function logout(): Promise<void> {
  try {
    await parseResponse(await fetch(`${apiBaseUrl}/auth/logout`, {
      method: 'POST',
      credentials: 'include',
    }))
  } finally {
    accessToken = null
  }
}

export async function authenticatedFetch<T>(path: string, init: RequestInit = {}, retry = true): Promise<T> {
  const headers = new Headers(init.headers)
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  const response = await fetch(`${apiBaseUrl}${path}`, { ...init, headers, credentials: 'include' })
  if (response.status === 401 && retry) {
    await refreshSession()
    return authenticatedFetch<T>(path, init, false)
  }
  return parseResponse<T>(response)
}

export function clearAccessToken() {
  accessToken = null
}
