import { afterEach, describe, expect, it, vi } from 'vitest'
import { createProject, fetchAssetBlob, listAssets, uploadAsset } from './contentApi'
import { clearAccessToken, login } from './authApi'

afterEach(() => { clearAccessToken(); vi.unstubAllGlobals() })

describe('content API', () => {
  it('uploads images as multipart data without overriding the browser boundary', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 'asset-1' }), {
      status: 201,
      headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)
    await uploadAsset(new File(['image'], 'product.png', { type: 'image/png' }), 'product_reference')
    const init = fetchMock.mock.calls[0][1] as RequestInit
    expect(init.body).toBeInstanceOf(FormData)
    expect(new Headers(init.headers).has('Content-Type')).toBe(false)
  })

  it('sends project drafts as JSON', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 'project-1' }), {
      status: 201,
      headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)
    await createProject({ project_type: 'listing', name: 'Project', draft: { title: 'Draft' } })
    const init = fetchMock.mock.calls[0][1] as RequestInit
    expect(new Headers(init.headers).get('Content-Type')).toBe('application/json')
    expect(JSON.parse(init.body as string).draft).toEqual({ title: 'Draft' })
  })

  it('filters the asset center by generated workspace category', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      items: [], total: 0, limit: 30, offset: 0,
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)

    await listAssets('batch_tryon_output', 'summer shirt')

    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/assets?category=batch_tryon_output&search=summer+shirt')
  })

  it('loads private image content from a same-origin path with auth credentials', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        access_token: 'test-access-token', token_type: 'bearer', expires_in: 900,
        identity: { user: {}, organization: null, role_codes: [], permissions: [], memberships: [] },
      }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      .mockResolvedValueOnce(new Response(new Blob(['image-bytes'], { type: 'image/png' }), {
        status: 200, headers: { 'Content-Type': 'image/png' },
      }))
    vi.stubGlobal('fetch', fetchMock)

    await login('user@example.com', 'password')
    const blob = await fetchAssetBlob('/api/v1/assets/asset-1/content')

    expect(blob.type).toBe('image/png')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/v1/assets/asset-1/content')
    const init = fetchMock.mock.calls[1][1] as RequestInit
    expect(init.credentials).toBe('include')
    expect(new Headers(init.headers).get('Authorization')).toBe('Bearer test-access-token')
  })
})
