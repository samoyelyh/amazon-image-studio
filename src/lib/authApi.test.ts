import { afterEach, describe, expect, it, vi } from 'vitest'
import { authenticatedFetch, clearAccessToken, login } from './authApi'

const identity = {
  user: { id: 'user-1', email: 'user@example.com', display_name: 'User', status: 'active', auth_provider: 'local', created_at: '', updated_at: '' },
  organization: null,
  role_codes: [],
  permissions: [],
  memberships: [],
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

afterEach(() => {
  clearAccessToken()
  vi.unstubAllGlobals()
})

describe('multiuser authentication API', () => {
  it('keeps the access token in memory and sends it as a bearer token', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ access_token: 'access-one', token_type: 'bearer', expires_in: 900, identity }))
      .mockResolvedValueOnce(jsonResponse({ ok: true }))
    vi.stubGlobal('fetch', fetchMock)

    await login('user@example.com', 'correct-password')
    await authenticatedFetch('/protected')

    const protectedInit = fetchMock.mock.calls[1][1] as RequestInit
    expect(new Headers(protectedInit.headers).get('Authorization')).toBe('Bearer access-one')
  })

  it('refreshes once after a protected request returns 401', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ access_token: 'old-access', token_type: 'bearer', expires_in: 900, identity }))
      .mockResolvedValueOnce(jsonResponse({ error: { code: 'auth.invalid_token', message: 'expired' } }, 401))
      .mockResolvedValueOnce(jsonResponse({ access_token: 'new-access', token_type: 'bearer', expires_in: 900, identity }))
      .mockResolvedValueOnce(jsonResponse({ ok: true }))
    vi.stubGlobal('fetch', fetchMock)

    await login('user@example.com', 'correct-password')
    const result = await authenticatedFetch<{ ok: boolean }>('/protected')

    expect(result.ok).toBe(true)
    expect(fetchMock.mock.calls[2][0]).toContain('/auth/refresh')
    const retryInit = fetchMock.mock.calls[3][1] as RequestInit
    expect(new Headers(retryInit.headers).get('Authorization')).toBe('Bearer new-access')
  })
})
