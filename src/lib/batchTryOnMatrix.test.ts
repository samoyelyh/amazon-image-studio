import { describe, expect, it } from 'vitest'
import type { BatchTryOnBatch } from '../types'
import { buildBatchTryOnMatrix } from './batchTryOnMatrix'
import { DEFAULT_BATCH_TRY_ON_PRESET_SELECTION } from './batchTryOnPresets'
import { DEFAULT_PARAMS } from '../types'

function batch(): BatchTryOnBatch {
  return {
    id: 'batch-1',
    templateImageId: 'template-image-1',
    templates: Array.from({ length: 3 }, (_, index) => ({
      id: `template-${index + 1}`,
      imageId: `template-image-${index + 1}`,
      fileName: `model-${index + 1}.png`,
      displayName: `模特-${index + 1}`,
      selected: true,
      isDefault: index === 0,
    })),
    garments: Array.from({ length: 5 }, (_, index) => ({
      id: `garment-${index + 1}`,
      batchId: 'batch-1',
      garmentImageId: `garment-image-${index + 1}`,
      garmentFileName: `0${index + 1}-shirt.png`,
      index,
      selected: true,
      createdAt: 1,
    })),
    items: [],
    presetSelection: { ...DEFAULT_BATCH_TRY_ON_PRESET_SELECTION },
    extraRequirements: '',
    aspectRatio: 'template',
    concurrency: 3,
    adminTestMode: false,
    params: { ...DEFAULT_PARAMS },
    queuePaused: true,
    createdAt: 1,
    updatedAt: 1,
  }
}

describe('buildBatchTryOnMatrix', () => {
  it('builds every selected template and garment pair with stable relations', () => {
    let sequence = 0
    const items = buildBatchTryOnMatrix(batch(), () => `item-${++sequence}`)

    expect(items).toHaveLength(15)
    expect(new Set(items.map((item) => `${item.templateId}:${item.garmentId}`)).size).toBe(15)
    expect(items[0]).toMatchObject({
      templateId: 'template-1',
      garmentId: 'garment-1',
      templateName: '模特-1',
      garmentFileName: '01-shirt.png',
    })
    expect(items[14]).toMatchObject({ templateId: 'template-3', garmentId: 'garment-5', index: 14 })
  })

  it('only combines selected assets', () => {
    const input = batch()
    input.templates[1].selected = false
    input.garments[0].selected = false
    const items = buildBatchTryOnMatrix(input, () => 'item')

    expect(items).toHaveLength(8)
    expect(items.some((item) => item.templateId === 'template-2')).toBe(false)
    expect(items.some((item) => item.garmentId === 'garment-1')).toBe(false)
  })
})
