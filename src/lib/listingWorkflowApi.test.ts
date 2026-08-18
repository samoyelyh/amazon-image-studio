import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  buildListingImagePrompts, confirmListingWorkflowSession, createCategoryOutputProject,
  cancelListingImageTaskGroup, generateCategoryListingImages, getListingOutputOptions,
  getQuickListingOptions, getQuickListingStatus, listListingImageTaskGroups,
  listListingWorkflowSessions,
  buildImageVariationPrompts, generateImageVariations, getImageVariationOptions,
  buildFreeVariationPrompt, createFreeVariationProject, generateFreeVariations,
  getFreeVariationRecommendations, updateFreeVariationProject,
  retryFailedListingImageTaskGroup, startCategoryRecommendation, startQuickListingGeneration,
} from './listingWorkflowApi'
import { clearAccessToken } from './authApi'


afterEach(() => { clearAccessToken(); vi.unstubAllGlobals() })

function ok(body: unknown = {}) {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

describe('category listing workflow API', () => {
  it('submits advisory category recommendation with server asset ids', async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok({ job_id: 'job-1', status: 'queued' }))
    vi.stubGlobal('fetch', fetchMock)

    await startCategoryRecommendation(['asset-1', 'asset-2'], 'category-recommend:test')

    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/listing-workbench/recommend-category')
    const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string)
    expect(body.product_image_asset_ids).toEqual(['asset-1', 'asset-2'])
  })

  it('keeps the user prompt as a separate prompt-builder input', async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok({ session_id: 'session-1', prompts: {} }))
    vi.stubGlobal('fetch', fetchMock)

    await buildListingImagePrompts({
      session_id: 'session-1', selected_image_types: ['main', 'scene'],
      user_prompt_override: 'Use game-day lighting.',
    })

    const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string)
    expect(body.selected_image_types).toEqual(['main', 'scene'])
    expect(body.user_prompt_override).toBe('Use game-day lighting.')
  })

  it('submits one category batch request while retaining one item per image type on the server', async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok({ batch_id: 'batch-1', job_ids: ['a', 'b'] }))
    vi.stubGlobal('fetch', fetchMock)

    await generateCategoryListingImages({
      session_id: 'session-1', selected_image_types: ['main', 'detail'],
      idempotency_key: 'category-images:test', concurrency: 2,
    })

    expect(fetchMock.mock.calls).toHaveLength(1)
    const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string)
    expect(body.selected_image_types).toEqual(['main', 'detail'])
    expect(body.concurrency).toBe(2)
  })

  it('uses distinct confirmation and output selection endpoints', async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(ok({})))
    vi.stubGlobal('fetch', fetchMock)
    await confirmListingWorkflowSession('session-1', { listing_content: {
      title: { en: 'Jersey', zh: '球衣' },
      bullet_points: [{ id: 'bullet-1', en: 'One', zh: '卖点一' }],
      description: { en: '', zh: '' }, search_terms: { en: [], zh: [] },
      selling_points: { en: '', zh: '' }, usage_scenarios: { en: '', zh: '' },
      customization_notes: { en: '', zh: '' }, cautions: { en: '', zh: '' },
    } })
    await getListingOutputOptions('session-1')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/listing-workbench/sessions/session-1/confirm')
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe('POST')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/v1/listing-workbench/sessions/session-1/output-options')
  })

  it('lists existing Listing sessions for the smart variation navigation hub', async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok([]))
    vi.stubGlobal('fetch', fetchMock)
    await listListingWorkflowSessions(25)
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/listing-workbench/sessions?limit=25')
  })

  it('creates Listing image and A+ projects through isolated endpoints', async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(ok({})))
    vi.stubGlobal('fetch', fetchMock)
    await createCategoryOutputProject('listing-image', 'session-1')
    await createCategoryOutputProject('a-plus', 'session-1')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/listing-image-projects')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/v1/a-plus-projects')
  })

  it('lists, cancels and retries persisted Listing image task groups', async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(ok({ items: [] })))
    vi.stubGlobal('fetch', fetchMock)
    await listListingImageTaskGroups('project-1')
    await cancelListingImageTaskGroup('group-1')
    await retryFailedListingImageTaskGroup('group-1', 'retry-group:test')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/listing-image-projects/project-1/task-groups')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/v1/listing-image-task-groups/group-1/cancel')
    expect((fetchMock.mock.calls[1][1] as RequestInit).method).toBe('POST')
    const retryBody = JSON.parse((fetchMock.mock.calls[2][1] as RequestInit).body as string)
    expect(retryBody.idempotency_key).toBe('retry-group:test')
  })

  it('starts quick generation with one orchestration request and polls one status endpoint', async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(ok({})))
    vi.stubGlobal('fetch', fetchMock)

    await getQuickListingOptions('football jersey')
    await startQuickListingGeneration({
      product_image_asset_ids: ['asset-1'],
      primary_asset_id: 'asset-1',
      selected_category_id: 'category-1',
      selected_image_types: ['main'],
      idempotency_key: 'quick-listing:test',
    })
    await getQuickListingStatus('session-1')

    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/listing-workbench/quick-options?category_id=football%20jersey')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/v1/listing-workbench/quick-generate')
    expect((fetchMock.mock.calls[1][1] as RequestInit).method).toBe('POST')
    const body = JSON.parse((fetchMock.mock.calls[1][1] as RequestInit).body as string)
    expect(body.selected_image_types).toEqual(['main'])
    expect(fetchMock.mock.calls[2][0]).toBe('/api/v1/listing-workbench/quick-generations/session-1')
  })

  it('uses the existing Listing image project for Skill-driven variation prompts and task groups', async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(ok({})))
    vi.stubGlobal('fetch', fetchMock)
    await getImageVariationOptions('project-1')
    await buildImageVariationPrompts('project-1', [{
      type_code: 'scene', plan_code: 'stadium', plan_key: 'stadium', name: '球场',
      custom: false, chinese_instruction: '', count: 2,
    }])
    await generateImageVariations('project-1', {
      plans: [{ item_code: 'variation:scene:stadium', count: 2 }],
      idempotency_key: 'variation:test', concurrency: 2,
    })
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/listing-image-projects/project-1/variation-options')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/v1/listing-image-projects/project-1/variation-prompts')
    expect(fetchMock.mock.calls[2][0]).toBe('/api/v1/listing-image-projects/project-1/variations/generate')
    const body = JSON.parse((fetchMock.mock.calls[2][1] as RequestInit).body as string)
    expect(body.plans).toEqual([{ item_code: 'variation:scene:stadium', count: 2 }])
  })

  it('uses free-variation endpoints without requiring a category or Skill', async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(ok({})))
    vi.stubGlobal('fetch', fetchMock)
    await createFreeVariationProject({ asset_ids: ['asset-1'], primary_asset_id: 'asset-1' })
    await updateFreeVariationProject('project-1', { asset_ids: ['asset-1', 'asset-2'], primary_asset_id: 'asset-2' })
    await getFreeVariationRecommendations()
    await buildFreeVariationPrompt('project-1', {
      chinese_prompt: '保持角色不变，更换背景为橄榄球场',
      template_fragments: ['保持角色不变', '更换背景为橄榄球场'],
    })
    await generateFreeVariations('project-1', {
      count: 2, idempotency_key: 'free-variation:test', concurrency: 2,
      size: '2048x2048', aspect_ratio: '1:1', requested_width: 2048,
      requested_height: 2048, quality: 'high', output_format: 'png',
    })
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      '/api/v1/listing-workbench/free-variation-projects',
      '/api/v1/listing-workbench/free-variation-projects/project-1',
      '/api/v1/listing-workbench/free-variation-recommendations',
      '/api/v1/listing-image-projects/project-1/free-variation-prompt',
      '/api/v1/listing-image-projects/project-1/free-variations/generate',
    ])
    const generated = JSON.parse((fetchMock.mock.calls[4][1] as RequestInit).body as string)
    expect(generated.count).toBe(2)
    expect(generated.aspect_ratio).toBe('1:1')
  })
})
