import { describe, expect, it } from 'vitest'
import type { BatchTryOnItem } from '../types'
import {
  isBatchTryOnBulkRegeneratable,
  summarizeBatchTryOnSelection,
  toSelectedBatchTryOnReviewItem,
} from './batchTryOnBulkActions'

function item(patch: Partial<BatchTryOnItem> = {}): BatchTryOnItem {
  return {
    id: 'client-item-1',
    batchId: 'batch-1',
    templateId: 'template-1',
    templateName: '模板一',
    garmentImageId: 'local-garment-1',
    garmentServerAssetId: 'garment-asset-1',
    garmentFileName: '06-shirt.png',
    serverReviewItemId: 'review-item-1',
    serverCurrentVersionId: 'version-2',
    serverOutputAssetId: 'output-asset-2',
    status: 'done',
    index: 5,
    createdAt: 1,
    ...patch,
  }
}

describe('batch try-on bulk actions', () => {
  it('uses stable business ids instead of a display index', () => {
    const selected = toSelectedBatchTryOnReviewItem(item({ index: 999 }))
    expect(selected).toMatchObject({
      itemId: 'review-item-1',
      versionId: 'version-2',
      generatedAssetId: 'output-asset-2',
      templateId: 'template-1',
      garmentAssetId: 'garment-asset-1',
    })
    expect(selected).not.toHaveProperty('index')
  })

  it('rejects queued, missing-output and missing-input selections', () => {
    expect(isBatchTryOnBulkRegeneratable(item({ status: 'queued' }))).toBe(false)
    expect(isBatchTryOnBulkRegeneratable(item({ serverOutputAssetId: undefined }))).toBe(false)
    expect(isBatchTryOnBulkRegeneratable(item({ garmentServerAssetId: undefined }))).toBe(false)
  })

  it('counts unique templates and garments in a cross-filter selection', () => {
    const first = toSelectedBatchTryOnReviewItem(item())!
    const second = toSelectedBatchTryOnReviewItem(item({
      id: 'client-item-2',
      serverReviewItemId: 'review-item-2',
      serverCurrentVersionId: 'version-1',
      serverOutputAssetId: 'output-asset-3',
      templateId: 'template-2',
    }))!
    expect(summarizeBatchTryOnSelection([first, second])).toEqual({
      itemCount: 2,
      templateCount: 2,
      garmentCount: 1,
    })
  })
})
