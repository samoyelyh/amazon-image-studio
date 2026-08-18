import { afterEach, describe, expect, it, vi } from 'vitest'
import { hardDeleteBatchTryOnWorkspace } from './batchTryOnWorkspaceApi'

afterEach(() => vi.unstubAllGlobals())

describe('batch try-on workspace API', () => {
  it('uses the dedicated workspace hard-delete endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      deleted_batches: 2,
      deleted_jobs: 4,
      deleted_outputs: 4,
      deleted_assets: 4,
      retained_shared_assets: 0,
      storage_delete_failures: 0,
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)

    await hardDeleteBatchTryOnWorkspace('workspace-1')

    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toContain('/batch-tryon/workspaces/workspace-1/hard?confirmation=PERMANENT_DELETE')
    expect(init.method).toBe('DELETE')
  })
})
