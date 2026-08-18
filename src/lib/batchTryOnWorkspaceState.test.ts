import { describe, expect, it } from 'vitest'
import { DEFAULT_PARAMS, type BatchTryOnBatch, type BatchTryOnItem } from '../types'
import {
  appendBatchTryOnSubmissionItems,
  appendTrackedServerBatchId,
  clearBatchTryOnQueueState,
  createEmptyBatch,
  isBatchTryOnConfigurationLocked,
  normalizeBatchTryOnBatch,
  resetItemForNewRun,
  resolveOutputAspectRatioForTemplate,
  resolveOutputSizeForTemplate,
  restoreServerStyleProfiles,
  shouldRestoreBatchTryOnWorkflow,
  summarizeItems,
  withTemplateFilenameInfo,
} from './batchTryOnWorkspaceState'

function legacyBatch(): BatchTryOnBatch {
  return {
    id: 'legacy-batch', templateImageId: 'template-image', templateServerAssetId: 'template-asset',
    templateFileName: 'model-front.png', templateWidth: 1600, templateHeight: 900,
    items: [{
      id: 'item-1', batchId: 'legacy-batch', templateImageId: 'template-image',
      garmentImageId: 'garment-image', garmentServerAssetId: 'garment-asset', garmentFileName: '01-shirt.png',
      index: 0, status: 'done', taskId: 'job-1', outputImageId: 'output-1', createdAt: 1,
    }],
    extraRequirements: '', aspectRatio: 'template', concurrency: 4,
    params: { ...DEFAULT_PARAMS }, queuePaused: true, createdAt: 1, updatedAt: 1,
  } as unknown as BatchTryOnBatch
}

describe('batch try-on workspace state', () => {
  it('keeps multiuser configuration editable after submitting a server batch', () => {
    expect(isBatchTryOnConfigurationLocked(false, true, false)).toBe(false)
    expect(isBatchTryOnConfigurationLocked(true, true, false)).toBe(true)
    expect(isBatchTryOnConfigurationLocked(false, true, true)).toBe(true)
  })

  it('keeps previous queue items and tracks every submitted server batch', () => {
    const source = normalizeBatchTryOnBatch(legacyBatch()).items[0]
    const next = { ...source, id: 'item-2', taskId: 'job-2', status: 'queued' as const }
    expect(appendBatchTryOnSubmissionItems([source], [next]).map((item) => item.id)).toEqual(['item-1', 'item-2'])
    expect(appendTrackedServerBatchId(['batch-1'], 'batch-2')).toEqual(['batch-1', 'batch-2'])
    expect(appendTrackedServerBatchId(['batch-1', 'batch-2'], 'batch-2')).toEqual(['batch-1', 'batch-2'])
  })

  it('clears only the current page queue and does not restore older workflows', () => {
    const source = normalizeBatchTryOnBatch(legacyBatch())
    source.serverWorkflowId = 'workflow-1'
    source.serverBatchId = 'batch-1'
    source.serverBatchIds = ['batch-1', 'batch-2']
    const cleared = clearBatchTryOnQueueState(source, Date.parse('2026-08-17T12:00:00Z'))
    expect(cleared).toMatchObject({
      templates: source.templates,
      garments: source.garments,
      items: [],
      serverBatchIds: [],
      queuePaused: true,
    })
    expect(cleared.serverWorkflowId).toBeUndefined()
    expect(cleared.serverBatchId).toBeUndefined()
    expect(shouldRestoreBatchTryOnWorkflow('2026-08-17T11:59:59Z', cleared.queueClearedAt)).toBe(false)
    expect(shouldRestoreBatchTryOnWorkflow('2026-08-17T12:00:01Z', cleared.queueClearedAt)).toBe(true)
  })

  it('creates the current normal try-on defaults without sharing IDs', () => {
    const created = createEmptyBatch(DEFAULT_PARAMS, () => 'batch-id')
    expect(created).toMatchObject({
      id: 'batch-id', templates: [], garments: [], items: [], styleProfiles: [],
      aspectRatio: 'template', concurrency: 12, adminTestMode: false, queuePaused: true,
      params: { quality: 'high', n: 1 },
    })
  })

  it('normalizes legacy template and garment fields while preserving task history', () => {
    const normalized = normalizeBatchTryOnBatch(legacyBatch())
    expect(normalized.concurrency).toBe(12)
    expect(normalized.sampleGarmentId).toBe('item-1')
    expect(normalized.templates[0]).toMatchObject({
      id: 'legacy-template-template-image', imageId: 'template-image', serverAssetId: 'template-asset',
      displayName: 'model-front', selected: true, isDefault: true,
    })
    expect(normalized.garments[0]).toMatchObject({
      garmentImageId: 'garment-image', serverAssetId: 'garment-asset', garmentFileName: '01-shirt.png',
    })
    expect(normalized.items[0]).toMatchObject({
      taskId: 'job-1', outputImageId: 'output-1', templateId: 'legacy-template-template-image',
      garmentId: 'item-1', templateName: 'model-front',
    })
  })

  it('preserves an existing valid sample garment selection', () => {
    const source = legacyBatch()
    source.sampleGarmentId = 'item-1'
    expect(normalizeBatchTryOnBatch(source).sampleGarmentId).toBe('item-1')
  })

  it('resolves delivery dimensions per template without changing the batch selection', () => {
    const batch = normalizeBatchTryOnBatch(legacyBatch())
    expect(resolveOutputAspectRatioForTemplate(batch, { ...batch.templates[0], width: 1600, height: 900 })).toBe('16:9')
    expect(resolveOutputSizeForTemplate(batch, { ...batch.templates[0], width: 1600, height: 900 })).toBe('2048x1152')
  })

  it('resets only execution fields and summarizes every queue status', () => {
    const source = normalizeBatchTryOnBatch(legacyBatch()).items[0]
    expect(resetItemForNewRun(source)).toMatchObject({
      id: 'item-1', garmentFileName: '01-shirt.png', status: 'pending',
      taskId: undefined, outputImageId: undefined,
    })
    const statuses = ['pending', 'queued', 'retry_waiting', 'running', 'done', 'error', 'stopped'] as const
    const items = statuses.map((status, index) => ({ ...source, id: `item-${index}`, status }))
    expect(summarizeItems(items)).toEqual({
      pending: 1, queued: 1, retry_waiting: 1, running: 1, done: 1, error: 1, stopped: 1,
    })
  })

  it('derives filename metadata from stable template relations', () => {
    const batch = normalizeBatchTryOnBatch(legacyBatch())
    expect(withTemplateFilenameInfo(batch, batch.items[0])).toEqual({
      garmentFileName: '01-shirt.png', templateName: 'model-front',
      templateIndex: 1, templateCount: 1, index: 0,
    })
  })

  it('restores server style profiles by asset IDs instead of array positions', () => {
    const profiles = restoreServerStyleProfiles([{
      id: 'profile-id', batch_id: 'batch-id', source_sample_asset_id: 'garment-asset-2',
      profile_key: 'jersey', category: 'sports_jersey',
      structure_json: { neckline: 'v-neck', sleeve_type: 'short' },
      view_rules_json: { supports_front: true, supports_back: false, front_back_must_not_swap: true },
      preservation_rules_json: {
        design_rules: { preserve_text: true, preserve_numbers: true },
        structure_rules: { preserve_neckline: true, preserve_sleeves: false },
      },
      covered_garment_asset_ids_json: ['garment-asset-2'], first_sample_observation_json: null,
      analysis_model: 'gpt', analysis_version: 'v1',
    }], [
      { id: 'garment-1', batchId: 'batch-id', garmentImageId: 'image-1', serverAssetId: 'garment-asset-1', garmentFileName: 'one.png', index: 0, selected: true, createdAt: 1 },
      { id: 'garment-2', batchId: 'batch-id', garmentImageId: 'image-2', serverAssetId: 'garment-asset-2', garmentFileName: 'two.png', index: 1, selected: true, createdAt: 1 },
    ])
    expect(profiles[0]).toMatchObject({
      sourceGarmentId: 'garment-2', coveredGarmentIds: ['garment-2'], category: 'sports_jersey',
      garmentStructure: { neckline: 'v-neck', sleeveType: 'short' },
      viewRules: { supportsFront: true, supportsBack: false, frontBackMustNotSwap: true },
      structureRules: { preserveNeckline: true, preserveSleeves: false },
    })
  })
})
