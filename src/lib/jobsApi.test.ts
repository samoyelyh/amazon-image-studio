import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  getServerJobsByIds, hardDeleteServerBatch, isServerBatchCancelling, isWorkspaceShellBatch,
  resolveModelCode, submitServerBatch, submitServerJob,
} from './jobsApi'

afterEach(() => vi.unstubAllGlobals())

function jsonResponse(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('server jobs API', () => {
  it('distinguishes workspace shells from cancellable task batches', () => {
    expect(isWorkspaceShellBatch({ batch_kind: 'workspace' })).toBe(true)
    expect(isWorkspaceShellBatch({ batch_kind: 'production' })).toBe(false)
    expect(isServerBatchCancelling({ status: 'running', cancel_requested_jobs: 1 })).toBe(true)
    expect(isServerBatchCancelling({ status: 'cancelled', cancel_requested_jobs: 1 })).toBe(false)
  })
  it('selects a server-side model pool without exposing any API key', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse([{
      id: 'pool-1', model_code: 'image-standard', code: 'default', name: 'Default',
      capabilities: ['image_generation'], key_count: 2,
    }]))
    vi.stubGlobal('fetch', fetchMock)
    await expect(resolveModelCode('image_generation')).resolves.toBe('image-standard')
    expect(JSON.stringify(fetchMock.mock.calls)).not.toMatch(/api[_-]?key|authorization.*sk-/i)
  })

  it('submits one job with only asset IDs and platform model code', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ id: 'job-1' }, 202))
    vi.stubGlobal('fetch', fetchMock)
    await submitServerJob({
      operation_code: 'listing.generate', workspace_type: 'listing', queue_name: 'listing_queue',
      capability: 'image_edit', model_code: 'image-standard', idempotency_key: 'web:test-job-1',
      input: { prompt: 'Product on white', reference_asset_ids: ['asset-1'] },
    })
    const body = JSON.parse(fetchMock.mock.calls[0][1].body as string)
    expect(body.input.reference_asset_ids).toEqual(['asset-1'])
    expect(JSON.stringify(body)).not.toMatch(/api[_-]?key|bearer|secret/i)
  })

  it('submits a batch as one server request instead of looping over provider calls', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ id: 'batch-1', jobs: [] }, 202))
    vi.stubGlobal('fetch', fetchMock)
    await submitServerBatch({
      name: 'Try-on', workspace_type: 'batch_tryon', operation_code: 'batch_tryon.generate',
      capability: 'multi_image_reference', model_code: 'image-edit', idempotency_key: 'batch:test-1', concurrency: 2,
      items: [{ client_item_id: 'item-1', prompt: 'Dress model', reference_asset_ids: ['model', 'garment'], size: '1024x1024', output_format: 'png' }],
    })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(String(fetchMock.mock.calls[0][0])).toContain('/job-batches')
  })

  it('polls regenerated jobs by stable task ids instead of the latest batch id', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse([
      { id: 'job-old-batch-1', batch_id: 'historical-batch', status: 'running' },
      { id: 'job-old-batch-2', batch_id: 'historical-batch', status: 'queued' },
    ]))
    vi.stubGlobal('fetch', fetchMock)
    await getServerJobsByIds(['job-old-batch-1', 'job-old-batch-2'])
    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toContain('/jobs/batch-status')
    expect(JSON.parse(init.body as string)).toEqual({
      job_ids: ['job-old-batch-1', 'job-old-batch-2'],
    })
  })

  it('requires the explicit permanent-delete confirmation in the hard-delete request', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      deleted_batches: 1, deleted_jobs: 3, deleted_outputs: 3, deleted_assets: 3,
      retained_shared_assets: 0, storage_delete_failures: 0,
    }))
    vi.stubGlobal('fetch', fetchMock)
    await hardDeleteServerBatch('batch-1')
    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toContain('/job-batches/batch-1/hard?confirmation=PERMANENT_DELETE')
    expect(init.method).toBe('DELETE')
  })
})
