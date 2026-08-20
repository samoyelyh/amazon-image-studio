import { afterEach, describe, expect, it, vi } from 'vitest'
import { clearAccessToken } from './authApi'
import {
  getAttachmentMaterialSaveContext,
  getAttachmentMaterialSet,
  listAttachmentMaterialSets,
  saveAttachmentMaterialOutput,
  saveAttachmentMaterialSet,
} from './attachmentMaterialApi'

afterEach(() => {
  clearAccessToken()
  vi.unstubAllGlobals()
})

function ok(body: unknown = {}) {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

describe('attachment material API', () => {
  it('keeps full-set and single-output saves on the same versioned resource', async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(ok({})))
    vi.stubGlobal('fetch', fetchMock)
    const payload = { display_name: '球衣套图', tags: ['橄榄球衣'], note: '', save_mode: 'new' as const }

    await getAttachmentMaterialSaveContext('project-1')
    await saveAttachmentMaterialSet('project-1', payload)
    await saveAttachmentMaterialOutput('project-1', 'output-1', payload)

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      '/api/v1/attachment-materials/projects/project-1/save-context',
      '/api/v1/attachment-materials/projects/project-1/save',
      '/api/v1/attachment-materials/projects/project-1/outputs/output-1/save',
    ])
    expect((fetchMock.mock.calls[1][1] as RequestInit).method).toBe('POST')
    expect(JSON.parse(String((fetchMock.mock.calls[1][1] as RequestInit).body))).toEqual(payload)
  })

  it('builds personal search filters and detail URL', async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(ok({ items: [], total: 0 })))
    vi.stubGlobal('fetch', fetchMock)

    await listAttachmentMaterialSets({ search: '球衣', category_key: 'football_jersey', completion: 'complete' })
    await getAttachmentMaterialSet('set-1')

    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/attachment-materials?search=%E7%90%83%E8%A1%A3&category_key=football_jersey&completion=complete')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/v1/attachment-materials/set-1')
  })
})
