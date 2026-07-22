import { afterEach, describe, expect, it, vi } from 'vitest'
import { approveBatchTryOnVersion, getBatchTryOnReviewDetail, regenerateBatchTryOnVersion } from './batchTryOnReviewApi'

afterEach(() => vi.unstubAllGlobals())

describe('batch try-on review API', () => {
  it('uses stable review item and version ids for detail and approval', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => new Response(JSON.stringify({ item_id: 'item-1' }), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)
    await getBatchTryOnReviewDetail('item-1')
    await approveBatchTryOnVersion('item-1', 'version-2')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/batch-tryon/items/item-1/review-detail')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/v1/batch-tryon/items/item-1/approve')
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ source_version_id: 'version-2' })
  })

  it('submits additive notes and an idempotency key for regeneration', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ review: {}, job: {} }), {
      status: 202, headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)
    await regenerateBatchTryOnVersion('item-1', {
      source_version_id: 'version-1', retry_mode: 'with_review_notes',
      review_notes: 'Keep 06.', idempotency_key: 'review:uuid-1',
    })
    const input = JSON.parse(fetchMock.mock.calls[0][1].body)
    expect(input).toMatchObject({ source_version_id: 'version-1', retry_mode: 'with_review_notes', review_notes: 'Keep 06.' })
    expect(input.idempotency_key).toBe('review:uuid-1')
  })
})
