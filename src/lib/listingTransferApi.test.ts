import { afterEach, describe, expect, it, vi } from 'vitest'
import { sendListingOutputToBatchTryOn } from './listingTransferApi'


describe('listing transfer API', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('sends only output and project identifiers without image URLs', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      batch_project_id: 'batch-project-1',
      batch_project_name: 'Batch project',
      model_asset_id: 'asset-1',
      listing_output_id: 'output-3',
      listing_project_id: 'listing-project-1',
      redirect_path: '/workspaces/batch-tryon?project_id=batch-project-1',
      template_replaced: false,
      created_project: true,
      replayed: false,
      warnings: [],
    }), { status: 201, headers: { 'content-type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)

    await sendListingOutputToBatchTryOn('output-3', {
      target_mode: 'create_project',
      project_name: 'Listing-批量套图',
      idempotency_key: 'listing-transfer:test-1',
    })

    expect(fetchMock).toHaveBeenCalledOnce()
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/listing/generated-outputs/output-3/send-to-batch-tryon')
    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body))
    expect(body).toMatchObject({ target_mode: 'create_project', project_name: 'Listing-批量套图' })
    expect(JSON.stringify(body)).not.toContain('image_url')
    expect(JSON.stringify(body)).not.toContain('blob:')
  })
})
