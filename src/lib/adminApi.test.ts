import { afterEach, describe, expect, it, vi } from 'vitest'
import { adjustAdminQuota, createApiKey, getAdminResources, testAdminProvider, toggleAdminResource } from './adminApi'
import { clearAccessToken } from './authApi'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

afterEach(() => {
  clearAccessToken()
  vi.unstubAllGlobals()
})

describe('admin API', () => {
  it('submits a new API key only to the protected key endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ id: 'key-1' }, 201))
    vi.stubGlobal('fetch', fetchMock)

    await createApiKey({ provider_id: 'provider-1', label: '主账号', secret: 'sk-private-secret', max_concurrency: 2 })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(String(fetchMock.mock.calls[0][0])).toContain('/resource-pools/keys')
    const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string)
    expect(body.secret).toBe('sk-private-secret')
    expect(body.max_concurrency).toBe(2)
  })

  it('reads inventory without adding credentials to the request', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ providers: [], models: [], pools: [], keys: [] }))
    vi.stubGlobal('fetch', fetchMock)

    await getAdminResources()

    const init = fetchMock.mock.calls[0][1] as RequestInit
    expect(init.method).toBeUndefined()
    expect(init.body).toBeUndefined()
  })

  it('targets quota adjustments and resource toggles by id', async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse({ ok: true })))
    vi.stubGlobal('fetch', fetchMock)

    await adjustAdminQuota('org-1', { transaction_type: 'adjust', amount: 50, reason: '验收', idempotency_key: 'admin:test' })
    await toggleAdminResource('api-keys', 'key-1', false)

    expect(String(fetchMock.mock.calls[0][0])).toContain('/admin/organizations/org-1/quota-adjustments')
    expect(String(fetchMock.mock.calls[1][0])).toContain('/admin/api-keys/key-1')
    expect(JSON.parse((fetchMock.mock.calls[1][1] as RequestInit).body as string)).toEqual({ enabled: false })
  })

  it('tests a provider without placing any key in the browser request', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ provider_id: 'provider-1', success: true, models: [] }))
    vi.stubGlobal('fetch', fetchMock)

    await testAdminProvider('provider-1')

    expect(String(fetchMock.mock.calls[0][0])).toContain('/admin/providers/provider-1/test')
    const init = fetchMock.mock.calls[0][1] as RequestInit
    expect(init.method).toBe('POST')
    expect(init.body).toBe(JSON.stringify({ test_type: 'base' }))
    expect(String(init.body)).not.toContain('api_key')
    expect(String(init.body)).not.toContain('Authorization')
  })
})
