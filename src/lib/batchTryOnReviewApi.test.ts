import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  analyzeBatchTryOnReviewVersion,
  batchAnalyzeAndRegenerateBatchTryOnVersions,
  approveBatchTryOnRegionReplaceVersion,
  approveBatchTryOnVersion,
  batchRegenerateBatchTryOnVersions,
  getBatchTryOnReviewDetail,
  regenerateBatchTryOnVersion,
} from './batchTryOnReviewApi'

afterEach(() => vi.unstubAllGlobals())

describe('batch try-on review API', () => {
  it('uses the dedicated approval endpoint for a region replacement candidate', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ item_id: 'item-1' }), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)
    await approveBatchTryOnRegionReplaceVersion('item-1', 'version-2')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/batch-tryon/items/item-1/region-replace/approve')
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ source_version_id: 'version-2' })
  })

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

  it('submits one current review version for Luna detailed analysis', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 'analysis-job-1' }), {
      status: 202, headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)
    await analyzeBatchTryOnReviewVersion('item-1', {
      source_version_id: 'version-1',
      focus_notes: 'Check the number and both sleeves.',
      template_type: 'stadium_scene',
      prompt_preset_id: 'preset-1',
      template_prompt_override: 'Keep the stadium composition and all garment facts unchanged.',
      idempotency_key: 'review-analysis:uuid-1',
    })
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/batch-tryon/items/item-1/detailed-analysis')
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      source_version_id: 'version-1',
      focus_notes: 'Check the number and both sleeves.',
      template_type: 'stadium_scene',
      prompt_preset_id: 'preset-1',
      template_prompt_override: 'Keep the stadium composition and all garment facts unchanged.',
      idempotency_key: 'review-analysis:uuid-1',
    })
  })

  it('passes the React Query abort signal to the detail request', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ item_id: 'item-1' }), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()
    await getBatchTryOnReviewDetail('item-1', controller.signal)
    expect(fetchMock.mock.calls[0][1].signal).toBe(controller.signal)
  })

  it('submits stable item/version pairs to the bulk regeneration endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      requested_count: 2,
      created_count: 2,
      replayed_count: 0,
      failed_count: 0,
      created_tasks: [],
      errors: [],
    }), {
      status: 202,
      headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)
    await batchRegenerateBatchTryOnVersions({
      items: [
        { item_id: 'review-item-a', version_id: 'version-a' },
        { item_id: 'review-item-b', version_id: 'version-b' },
      ],
      review_notes: 'Keep the model and background unchanged.',
      idempotency_key: 'batch-review:uuid-1',
    })
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/batch-tryon/items/batch-regenerate-with-notes')
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      items: [
        { item_id: 'review-item-a', version_id: 'version-a' },
        { item_id: 'review-item-b', version_id: 'version-b' },
      ],
      review_notes: 'Keep the model and background unchanged.',
      idempotency_key: 'batch-review:uuid-1',
    })
  })

  it('submits selected versions for durable Luna analysis and automatic regeneration', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      requested_count: 2, created_count: 2, replayed_count: 0, failed_count: 0,
      auto_regenerate: true, analysis_tasks: [], errors: [],
    }), { status: 202, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)
    await batchAnalyzeAndRegenerateBatchTryOnVersions({
      items: [
        { item_id: 'review-a', version_id: 'version-a' },
        { item_id: 'review-b', version_id: 'version-b' },
      ],
      focus_notes: 'Inspect logos and numbers.',
      template_type: null,
      prompt_preset_id: null,
      template_prompt_override: null,
      auto_regenerate: true,
      idempotency_key: 'batch-luna:uuid-1',
    })
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/batch-tryon/items/batch-detailed-analysis-auto-regenerate')
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toMatchObject({
      auto_regenerate: true,
      focus_notes: 'Inspect logos and numbers.',
      items: [{ item_id: 'review-a', version_id: 'version-a' }, { item_id: 'review-b', version_id: 'version-b' }],
    })
  })
})
