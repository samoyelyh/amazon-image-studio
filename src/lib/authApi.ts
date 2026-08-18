import { runtimeConfig } from '../app/runtimeConfig'

export interface AuthUser {
  id: string
  email: string
  display_name: string
  status: string
  auth_provider: string
  must_change_password: boolean
  password_changed_at: string | null
  temporary_password_created_at: string | null
  created_by: string | null
  last_login_at: string | null
  created_at: string
  updated_at: string
}

export interface AuthOrganization {
  id: string
  name: string
  slug: string
  status: string
  invited_by: string | null
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
let currentSession: AuthSessionResponse | null = null
let refreshPromise: Promise<AuthSessionResponse> | null = null
let sessionMutationTail: Promise<void> = Promise.resolve()

const AUTH_CHANNEL_NAME = 'amazon-image-studio-auth-session-v1'
const AUTH_LOCK_NAME = 'amazon-image-studio-auth-mutation-v1'
const AUTH_LOCK_STORAGE_KEY = 'amazon-image-studio:auth-mutation-lock:v1'
const AUTH_LOCK_LEASE_MS = 15_000
const AUTH_LOCK_RENEW_MS = 5_000
const tabId = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`

export type AuthSessionChange =
  | { type: 'session'; session: AuthSessionResponse }
  | { type: 'logout' }

type AuthChannelMessage = AuthSessionChange & { source: string }
type AuthSessionChangeListener = (change: AuthSessionChange) => void

const sessionChangeListeners = new Set<AuthSessionChangeListener>()
let authChannel: BroadcastChannel | null = null

function emitSessionChange(change: AuthSessionChange) {
  sessionChangeListeners.forEach((listener) => listener(change))
}

function getAuthChannel(): BroadcastChannel | null {
  if (typeof window === 'undefined' || typeof BroadcastChannel === 'undefined') return null
  if (authChannel) return authChannel
  authChannel = new BroadcastChannel(AUTH_CHANNEL_NAME)
  authChannel.addEventListener('message', (event: MessageEvent<AuthChannelMessage>) => {
    const message = event.data
    if (!message || message.source === tabId) return
    if (message.type === 'session' && message.session?.access_token) {
      currentSession = message.session
      accessToken = message.session.access_token
      emitSessionChange({ type: 'session', session: message.session })
    } else if (message.type === 'logout') {
      currentSession = null
      accessToken = null
      emitSessionChange({ type: 'logout' })
    }
  })
  return authChannel
}

function publishSessionChange(change: AuthSessionChange) {
  getAuthChannel()?.postMessage({ ...change, source: tabId } satisfies AuthChannelMessage)
}

function applySession(session: AuthSessionResponse, broadcast = true) {
  currentSession = session
  accessToken = session.access_token
  if (broadcast) publishSessionChange({ type: 'session', session })
}

function sleep(milliseconds: number) {
  return new Promise<void>((resolve) => {
    if (typeof window === 'undefined') setTimeout(resolve, milliseconds)
    else window.setTimeout(resolve, milliseconds)
  })
}

interface AuthLockLease {
  owner: string
  expires_at: number
}

function readAuthLockLease(): AuthLockLease | null {
  try {
    const raw = window.localStorage.getItem(AUTH_LOCK_STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<AuthLockLease>
    return typeof parsed.owner === 'string' && typeof parsed.expires_at === 'number'
      ? parsed as AuthLockLease
      : null
  } catch {
    return null
  }
}

async function withStorageAuthLock<T>(action: () => Promise<T>): Promise<T> {
  const owner = `${tabId}-${Math.random().toString(36).slice(2)}`
  while (true) {
    const now = Date.now()
    const lease = readAuthLockLease()
    if (!lease || lease.expires_at <= now) {
      try {
        window.localStorage.setItem(AUTH_LOCK_STORAGE_KEY, JSON.stringify({
          owner,
          expires_at: now + AUTH_LOCK_LEASE_MS,
        } satisfies AuthLockLease))
        // Give competing tabs a chance to publish their lease, then verify ownership.
        await sleep(25)
        if (readAuthLockLease()?.owner === owner) {
          const renewLease = window.setInterval(() => {
            if (readAuthLockLease()?.owner !== owner) return
            window.localStorage.setItem(AUTH_LOCK_STORAGE_KEY, JSON.stringify({
              owner,
              expires_at: Date.now() + AUTH_LOCK_LEASE_MS,
            } satisfies AuthLockLease))
          }, AUTH_LOCK_RENEW_MS)
          try {
            return await action()
          } finally {
            window.clearInterval(renewLease)
            if (readAuthLockLease()?.owner === owner) window.localStorage.removeItem(AUTH_LOCK_STORAGE_KEY)
          }
        }
      } catch {
        return action()
      }
    }
    const waitUntil = readAuthLockLease()?.expires_at ?? (Date.now() + 100)
    await sleep(Math.min(1_000, Math.max(50, waitUntil - Date.now() + 25)))
  }
}

async function withCrossTabAuthLock<T>(action: () => Promise<T>): Promise<T> {
  if (typeof window === 'undefined') return action()
  if (typeof navigator !== 'undefined' && navigator.locks) {
    return navigator.locks.request(AUTH_LOCK_NAME, action)
  }
  return withStorageAuthLock(action)
}

function enqueueSessionMutation<T>(action: () => Promise<T>): Promise<T> {
  const pending = sessionMutationTail.catch(() => undefined).then(() => withCrossTabAuthLock(action))
  sessionMutationTail = pending.then(() => undefined, () => undefined)
  return pending
}

// Initialize cross-tab listening as soon as the browser loads this module.
getAuthChannel()

async function parseResponse<T>(response: Response): Promise<T> {
  if (response.ok) return response.status === 204 ? undefined as T : response.json() as Promise<T>
  const payload = await response.json().catch(() => ({})) as ApiErrorPayload
  throw new AuthApiError(
    response.status,
    payload.error?.code || 'request.failed',
    payload.error?.message || payload.detail?.[0]?.msg || '请求失败，请稍后重试',
  )
}

function resolveApiRequestUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) return path
  if (path.startsWith(apiBaseUrl)) return path
  return `${apiBaseUrl}${path.startsWith('/') ? path : `/${path}`}`
}

async function parseErrorResponse(response: Response): Promise<never> {
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
  applySession(session)
  return session
}

export async function login(email: string, password: string): Promise<AuthSessionResponse> {
  return enqueueSessionMutation(() => sessionRequest('/auth/login', { email, password }))
}

export async function refreshSession(expectedAccessToken = accessToken): Promise<AuthSessionResponse> {
  if (!refreshPromise) {
    refreshPromise = enqueueSessionMutation(async () => {
      // Another tab may already have refreshed while this tab was waiting for the lock.
      if (currentSession && accessToken && accessToken !== expectedAccessToken) return currentSession
      for (let attempt = 0; attempt < 3; attempt += 1) {
        try {
          return await sessionRequest('/auth/refresh')
        } catch (error) {
          if (!(error instanceof AuthApiError) || error.code !== 'auth.refresh_race' || attempt === 2) throw error
          await sleep(100 * (attempt + 1))
        }
      }
      throw new Error('unreachable')
    }).finally(() => { refreshPromise = null })
  }
  return refreshPromise
}

export async function switchOrganization(organizationId: string): Promise<AuthSessionResponse> {
  return enqueueSessionMutation(() => sessionRequest('/auth/switch-organization', { organization_id: organizationId }))
}

export async function changePassword(currentPassword: string, newPassword: string, retry = true): Promise<AuthSessionResponse> {
  const requestAccessToken = accessToken
  const headers = new Headers({ 'Content-Type': 'application/json' })
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
  const response = await fetch(`${apiBaseUrl}/auth/change-password`, {
    method: 'POST',
    credentials: 'include',
    headers,
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  })
  if (response.status === 401 && retry) {
    await refreshSession(requestAccessToken)
    return changePassword(currentPassword, newPassword, false)
  }
  const session = await parseResponse<AuthSessionResponse>(response)
  applySession(session)
  return session
}

export async function logout(): Promise<void> {
  await enqueueSessionMutation(async () => {
    try {
      await parseResponse(await fetch(`${apiBaseUrl}/auth/logout`, {
        method: 'POST',
        credentials: 'include',
      }))
    } finally {
      currentSession = null
      accessToken = null
      publishSessionChange({ type: 'logout' })
    }
  })
}

export async function authenticatedFetch<T>(path: string, init: RequestInit = {}, retry = true): Promise<T> {
  const response = await authenticatedFetchResponse(path, init, retry)
  return response.status === 204 ? undefined as T : response.json() as Promise<T>
}

export async function authenticatedFetchResponse(path: string, init: RequestInit = {}, retry = true): Promise<Response> {
  const headers = new Headers(init.headers)
  const requestUrl = resolveApiRequestUrl(path)
  const isExternal = /^https?:\/\//i.test(requestUrl)
    && typeof window !== 'undefined'
    && new URL(requestUrl, window.location.href).origin !== window.location.origin
  const requestAccessToken = accessToken
  if (requestAccessToken && !isExternal) headers.set('Authorization', `Bearer ${requestAccessToken}`)
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  const response = await fetch(requestUrl, { ...init, headers, credentials: isExternal ? 'omit' : 'include' })
  if (response.status === 401 && retry) {
    await refreshSession(requestAccessToken)
    return authenticatedFetchResponse(path, init, false)
  }
  if (!response.ok) return parseErrorResponse(response)
  return response
}

export function clearAccessToken() {
  accessToken = null
  currentSession = null
}

export function subscribeAuthSessionChanges(listener: AuthSessionChangeListener) {
  sessionChangeListeners.add(listener)
  getAuthChannel()
  return () => { sessionChangeListeners.delete(listener) }
}
