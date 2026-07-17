import { afterEach, describe, expect, it, vi } from 'vitest'
import { createProject, uploadAsset } from './contentApi'

afterEach(() => vi.unstubAllGlobals())

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
})
