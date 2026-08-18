import { describe, expect, it } from 'vitest'
import type { BatchTryOnBatch } from '../types'
import {
  buildBatchTryOnMatrix,
  buildBatchTryOnTemplateMatrix,
  buildUnsubmittedBatchTryOnMatrix,
  estimateBatchTryOnGenerationCount,
  getBatchTryOnCombinationError,
  getUnsubmittedBatchTryOnCombinationPairs,
} from './batchTryOnMatrix'
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
      templateOrder: 1,
      templateCount: 3,
      garmentFileName: '01-shirt.png',
    })
    expect(items[14]).toMatchObject({
      templateId: 'template-3',
      templateOrder: 3,
      templateCount: 3,
      garmentId: 'garment-5',
      index: 14,
    })
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

  it('pairs selected templates and garments one-to-one in their current order', () => {
    const input = batch()
    input.combinationMode = 'one_to_one'
    input.garments = input.garments.slice(0, 3).map((garment, index) => ({
      ...garment,
      fontReference: {
        imageId: `font-image-${index + 1}`,
        fileName: `font-000053${index + 1}.png`,
      },
    }))
    let sequence = 0
    const items = buildBatchTryOnMatrix(input, () => `pair-${++sequence}`)

    expect(items).toHaveLength(3)
    expect(items.map((item) => `${item.templateId}:${item.garmentId}`)).toEqual([
      'template-1:garment-1',
      'template-2:garment-2',
      'template-3:garment-3',
    ])
    expect(estimateBatchTryOnGenerationCount(input)).toBe(3)
    expect(getBatchTryOnCombinationError(input)).toBe('')
  })

  it('rejects one-to-one submission when selected counts differ', () => {
    const input = batch()
    input.combinationMode = 'one_to_one'

    expect(buildBatchTryOnMatrix(input, () => 'unused')).toEqual([])
    expect(estimateBatchTryOnGenerationCount(input)).toBe(3)
    expect(getBatchTryOnCombinationError(input)).toContain('模板 3 张，服装 5 件')
  })

  it('builds a new analysis matrix for only the requested template', () => {
    const input = batch()
    input.garments[0].selected = false
    let sequence = 0
    const items = buildBatchTryOnTemplateMatrix(input, 'template-2', () => `analysis-${++sequence}`)

    expect(items).toHaveLength(4)
    expect(new Set(items.map((item) => item.templateId))).toEqual(new Set(['template-2']))
    expect(items.some((item) => item.garmentId === 'garment-1')).toBe(false)
    expect(items.every((item) => item.templateCount === 1)).toBe(true)
  })

  it('does not resubmit combinations from an earlier production batch', () => {
    const input = batch()
    input.templates[1].selected = false
    input.templates[2].selected = false
    let firstSequence = 0
    const firstSubmission = buildBatchTryOnMatrix(input, () => `first-${++firstSequence}`)

    input.templates[1].selected = true
    input.items = [
      {
        ...firstSubmission[0],
        id: 'validation:template-2:sample',
        templateId: 'template-2',
        status: 'done',
      },
      ...firstSubmission,
    ]
    let secondSequence = 0
    const secondSubmission = buildUnsubmittedBatchTryOnMatrix(input, input.items, () => `second-${++secondSequence}`)

    expect(getUnsubmittedBatchTryOnCombinationPairs(input)).toHaveLength(5)
    expect(secondSubmission).toHaveLength(5)
    expect(new Set(secondSubmission.map((item) => item.templateId))).toEqual(new Set(['template-2']))
    expect(secondSubmission.some((item) => item.templateId === 'template-1')).toBe(false)
  })

  it('treats running and failed production items as submitted combinations', () => {
    const input = batch()
    input.templates = input.templates.slice(0, 1)
    input.garments = input.garments.slice(0, 2)
    const existing = buildBatchTryOnMatrix(input, () => 'existing').map((item, index) => ({
      ...item,
      id: `existing-${index}`,
      status: index === 0 ? 'running' as const : 'error' as const,
    }))

    expect(buildUnsubmittedBatchTryOnMatrix(input, existing, () => 'duplicate')).toEqual([])
  })

  it('analyzes only the garment paired with a template in one-to-one mode', () => {
    const input = batch()
    input.combinationMode = 'one_to_one'
    input.garments = input.garments.slice(0, 3)

    const items = buildBatchTryOnTemplateMatrix(input, 'template-2', () => 'analysis-pair')

    expect(items).toHaveLength(1)
    expect(items[0]).toMatchObject({ templateId: 'template-2', garmentId: 'garment-2' })
  })

  it('keeps the current garment as each matrix item source of truth', () => {
    const input = batch()
    input.templates = input.templates.slice(0, 2).map((template, index) => ({
      ...template,
      serverAssetId: `template-server-${index + 1}`,
    }))
    input.garments = input.garments.slice(0, 3).map((garment, index) => ({
      ...garment,
      serverAssetId: `garment-server-${index + 1}`,
    }))

    let sequence = 0
    const items = buildBatchTryOnMatrix(input, () => `contract-item-${++sequence}`)

    expect(items.map((item) => ({
      templateId: item.templateId,
      templateImageId: item.templateImageId,
      templateServerAssetId: item.templateServerAssetId,
      garmentId: item.garmentId,
      garmentImageId: item.garmentImageId,
      garmentServerAssetId: item.garmentServerAssetId,
      garmentFileName: item.garmentFileName,
    }))).toEqual([
      {
        templateId: 'template-1', templateImageId: 'template-image-1', templateServerAssetId: 'template-server-1',
        garmentId: 'garment-1', garmentImageId: 'garment-image-1', garmentServerAssetId: 'garment-server-1', garmentFileName: '01-shirt.png',
      },
      {
        templateId: 'template-1', templateImageId: 'template-image-1', templateServerAssetId: 'template-server-1',
        garmentId: 'garment-2', garmentImageId: 'garment-image-2', garmentServerAssetId: 'garment-server-2', garmentFileName: '02-shirt.png',
      },
      {
        templateId: 'template-1', templateImageId: 'template-image-1', templateServerAssetId: 'template-server-1',
        garmentId: 'garment-3', garmentImageId: 'garment-image-3', garmentServerAssetId: 'garment-server-3', garmentFileName: '03-shirt.png',
      },
      {
        templateId: 'template-2', templateImageId: 'template-image-2', templateServerAssetId: 'template-server-2',
        garmentId: 'garment-1', garmentImageId: 'garment-image-1', garmentServerAssetId: 'garment-server-1', garmentFileName: '01-shirt.png',
      },
      {
        templateId: 'template-2', templateImageId: 'template-image-2', templateServerAssetId: 'template-server-2',
        garmentId: 'garment-2', garmentImageId: 'garment-image-2', garmentServerAssetId: 'garment-server-2', garmentFileName: '02-shirt.png',
      },
      {
        templateId: 'template-2', templateImageId: 'template-image-2', templateServerAssetId: 'template-server-2',
        garmentId: 'garment-3', garmentImageId: 'garment-image-3', garmentServerAssetId: 'garment-server-3', garmentFileName: '03-shirt.png',
      },
    ])
  })
})
