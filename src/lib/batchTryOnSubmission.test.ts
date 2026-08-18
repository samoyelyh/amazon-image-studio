import { describe, expect, it } from 'vitest'
import { DEFAULT_PARAMS, type BatchGarmentStyleProfile, type BatchTryOnBatch, type BatchTryOnItem } from '../types'
import type { ServerJob } from './jobsApi'
import { DEFAULT_BATCH_TRY_ON_PRESET_SELECTION } from './batchTryOnPresets'
import {
  applySubmittedBatchTryOnJobs,
  buildBatchTryOnSubmissionItems,
  collectPreparedBatchTryOnGarments,
  type PreparedBatchTryOnSubmissionItem,
} from './batchTryOnSubmission'

function batch(): BatchTryOnBatch {
  return {
    id: 'batch-1', templateImageId: 'template-image', templates: [], garments: [], styleProfiles: [], items: [],
    presetSelection: { ...DEFAULT_BATCH_TRY_ON_PRESET_SELECTION }, extraRequirements: 'Keep exact product details.',
    aspectRatio: 'template', concurrency: 2, adminTestMode: false,
    params: { ...DEFAULT_PARAMS, quality: 'high', output_format: 'png', output_compression: 90 },
    queuePaused: true, createdAt: 1, updatedAt: 1,
  }
}

function item(id: string, garmentId: string, garmentAssetId: string): BatchTryOnItem {
  return {
    id, batchId: 'batch-1', templateId: 'template-1', templateImageId: 'template-image',
    templateName: 'model-front', templateOrder: 1, templateCount: 1,
    garmentId, garmentImageId: `${garmentId}-image`, garmentServerAssetId: garmentAssetId,
    garmentFileName: `${garmentId}.png`, presetSelection: { ...DEFAULT_BATCH_TRY_ON_PRESET_SELECTION },
    presetSummary: 'strict', index: Number(garmentId.slice(-1)) - 1, status: 'pending', createdAt: 1,
  }
}

function profile(coveredGarmentIds: string[]): BatchGarmentStyleProfile {
  return {
    profileKey: 'profile-1', sourceGarmentId: coveredGarmentIds[0], sourceSampleAssetId: 'garment-asset-1',
    category: 'jersey', garmentStructure: { neckline: 'v-neck' },
    viewRules: { supportsFront: true, supportsBack: true, frontBackMustNotSwap: true },
    designRules: {
      preserveText: true, preserveNumbers: true, preserveNames: true,
      preserveGraphics: true, preserveFontStyle: true, preserveElementPosition: true,
    },
    structureRules: {
      preserveNeckline: true, preserveSleeves: true, preserveGarmentLength: true, preserveSilhouette: true,
    },
    firstSampleObservation: { color: 'red' }, analysisModel: 'gpt', analysisVersion: 'v1', coveredGarmentIds,
  }
}

function prepared(source: BatchTryOnItem, garmentAssetId: string): PreparedBatchTryOnSubmissionItem {
  return {
    item: source, size: '2048x2048', aspectRatio: '1:1', templateAssetId: 'template-asset-1',
    garmentAssetId, presetSelection: { ...DEFAULT_BATCH_TRY_ON_PRESET_SELECTION }, presetSummary: 'strict',
  }
}

describe('batch try-on submission contract', () => {
  it('deduplicates garments by stable garment ID for one batch-level analysis', () => {
    const garment = item('item-1', 'garment-1', 'garment-asset-1')
    const preparedItems = [prepared(garment, 'garment-asset-1'), prepared({ ...garment, id: 'item-2', templateId: 'template-2' }, 'garment-asset-1')]
    expect(collectPreparedBatchTryOnGarments(preparedItems)).toEqual([
      { garmentId: 'garment-1', assetId: 'garment-asset-1', filename: 'garment-1.png' },
    ])
  })

  it('keeps template first and the current garment second in every job request', () => {
    const first = item('item-1', 'garment-1', 'garment-asset-1')
    const second = item('item-2', 'garment-2', 'garment-asset-2')
    const requests = buildBatchTryOnSubmissionItems(
      batch(),
      [prepared(first, 'garment-asset-1'), prepared(second, 'garment-asset-2')],
      [profile(['garment-1', 'garment-2'])],
    )
    expect(requests).toHaveLength(2)
    expect(requests[0].reference_asset_ids).toEqual(['template-asset-1', 'garment-asset-1'])
    expect(requests[1].reference_asset_ids).toEqual(['template-asset-1', 'garment-asset-2'])
    expect(requests[0].metadata).toMatchObject({
      garment_id: 'garment-1', garment_asset_id: 'garment-asset-1', qc_reference_asset_id: 'garment-asset-1',
      template_id: 'template-1', template_name: 'model-front', index: 0,
    })
    expect(requests[1].metadata).toMatchObject({
      garment_id: 'garment-2', garment_asset_id: 'garment-asset-2', qc_reference_asset_id: 'garment-asset-2',
      template_id: 'template-1', template_name: 'model-front', index: 1,
    })
    expect(requests.every((request) => request.prompt.includes('Keep exact product details.'))).toBe(true)
  })

  it('fails closed when an item has no matching batch style profile', () => {
    const source = item('item-1', 'garment-1', 'garment-asset-1')
    expect(() => buildBatchTryOnSubmissionItems(batch(), [prepared(source, 'garment-asset-1')], [])).toThrow(
      'garment-1.png 没有匹配到批次款式结构，请重新分析。',
    )
  })

  it('writes returned stable server relations only to submitted items', () => {
    const submitted = { ...item('item-1', 'garment-1', 'garment-asset-1'), status: 'done' as const, outputImageId: 'old-output' }
    const untouched = item('item-2', 'garment-2', 'garment-asset-2')
    const serverJob = {
      id: 'job-1', client_item_id: 'item-1', review_item_id: 'review-1', review_status: 'pending',
      current_version_id: 'version-1', approved_version_id: null, review_version_number: 1, regeneration_count: 0,
    } as ServerJob
    const result = applySubmittedBatchTryOnJobs([submitted, untouched], ['item-1'], [serverJob])
    expect(result[0]).toMatchObject({
      id: 'item-1', taskId: 'job-1', serverBatchId: serverJob.batch_id, status: 'queued', outputImageId: undefined,
      serverReviewItemId: 'review-1', serverCurrentVersionId: 'version-1', serverVersionNumber: 1,
    })
    expect(result[1]).toBe(untouched)
  })
})
