import type {
  BatchGarmentStyleProfile,
  BatchTryOnBatch,
  BatchTryOnGarment,
  BatchTryOnItem,
  BatchTryOnTemplate,
  TaskParams,
} from '../types'
import { calculateDeliverySize, resolveImageSize } from './imageSizeResolver'
import type { ServerJobBatch } from './jobsApi'
import { randomUuid } from './randomUuid'
import {
  DEFAULT_BATCH_TRY_ON_PRESET_SELECTION,
  resolveBatchTryOnPresetSelection,
  summarizeBatchTryOnPresets,
} from './batchTryOnPresets'

export function createEmptyBatch(globalParams: TaskParams, createId: () => string = randomUuid): BatchTryOnBatch {
  const now = Date.now()
  return {
    id: createId(),
    generationMode: 'normal_tryon',
    combinationMode: 'cartesian',
    templateImageId: null,
    templates: [],
    garments: [],
    sampleGarmentId: undefined,
    fontReferenceOverrides: {},
    styleProfiles: [],
    items: [],
    presetSelection: { ...DEFAULT_BATCH_TRY_ON_PRESET_SELECTION },
    extraRequirements: '',
    aspectRatio: 'template',
    concurrency: 12,
    adminTestMode: false,
    params: { ...globalParams, quality: 'high', n: 1 },
    queuePaused: true,
    createdAt: now,
    updatedAt: now,
  }
}

/** Multiuser jobs run from immutable server snapshots, so the next batch can be edited while they run. */
export function isBatchTryOnConfigurationLocked(
  isStandalone: boolean,
  isRunning: boolean,
  matrixSubmitting: boolean,
) {
  return matrixSubmitting || (isStandalone && isRunning)
}

export function appendTrackedServerBatchId(batchIds: string[] | undefined, batchId: string | undefined) {
  if (!batchId) return batchIds || []
  return [...new Set([...(batchIds || []), batchId])]
}

export function appendBatchTryOnSubmissionItems(existing: BatchTryOnItem[], next: BatchTryOnItem[]) {
  const nextIds = new Set(next.map((item) => item.id))
  return [...existing.filter((item) => !nextIds.has(item.id)), ...next]
}

export function clearBatchTryOnQueueState(batch: BatchTryOnBatch, clearedAt = Date.now()): BatchTryOnBatch {
  return {
    ...batch,
    items: [],
    serverBatchId: undefined,
    serverBatchIds: [],
    serverWorkflowId: undefined,
    queueClearedAt: clearedAt,
    queuePaused: true,
    updatedAt: clearedAt,
  }
}

export function shouldRestoreBatchTryOnWorkflow(createdAt: string, queueClearedAt?: number) {
  if (!queueClearedAt) return true
  const workflowCreatedAt = Date.parse(createdAt)
  return !Number.isFinite(workflowCreatedAt) || workflowCreatedAt > queueClearedAt
}

export function resolveOutputSize(batch: BatchTryOnBatch) {
  if (batch.aspectRatio !== 'template' && batch.params.size && batch.params.size !== 'auto') return batch.params.size
  const ratio = batch.aspectRatio === 'template'
    ? batch.templateWidth && batch.templateHeight ? `${batch.templateWidth}:${batch.templateHeight}` : '1:1'
    : batch.aspectRatio
  return calculateDeliverySize('2K', ratio) || '2048x2048'
}

export function resolveOutputSizeForTemplate(batch: BatchTryOnBatch, template?: BatchTryOnTemplate) {
  if (batch.aspectRatio !== 'template') return resolveOutputSize(batch)
  const ratio = template?.width && template.height ? `${template.width}:${template.height}` : '1:1'
  return calculateDeliverySize('2K', ratio) || '2048x2048'
}

export function resolveOutputAspectRatio(batch: BatchTryOnBatch) {
  if (batch.aspectRatio !== 'template') return batch.aspectRatio
  if (!batch.templateWidth || !batch.templateHeight) return '1:1'
  return resolveImageSize(`${batch.templateWidth}x${batch.templateHeight}`, 'auto').aspectRatio
}

export function resolveOutputAspectRatioForTemplate(batch: BatchTryOnBatch, template?: BatchTryOnTemplate) {
  if (batch.aspectRatio !== 'template') return resolveOutputAspectRatio(batch)
  if (!template?.width || !template.height) return '1:1'
  return resolveImageSize(`${template.width}x${template.height}`, 'auto').aspectRatio
}

export function normalizeBatchTryOnBatch(batch: BatchTryOnBatch): BatchTryOnBatch {
  const raw = batch as BatchTryOnBatch & {
    templates?: BatchTryOnTemplate[]
    garments?: BatchTryOnGarment[]
    fontReferenceOverrides?: BatchTryOnBatch['fontReferenceOverrides']
    presetSelection?: BatchTryOnBatch['presetSelection']
    adminTestMode?: boolean
  }
  const templates = (Array.isArray(raw.templates) ? raw.templates : batch.templateImageId ? [{
    id: `legacy-template-${batch.templateImageId}`,
    imageId: batch.templateImageId,
    serverAssetId: batch.templateServerAssetId,
    fileName: batch.templateFileName || 'model-template.png',
    displayName: stripExtension(batch.templateFileName || '默认模板'),
    width: batch.templateWidth,
    height: batch.templateHeight,
    selected: true,
    isDefault: true,
    sourceType: batch.templateSourceType,
    sourceId: batch.templateSourceId,
  }] : []).map((template) => ({
    ...template,
    promptStrategy: template.promptStrategy || 'luna_per_image',
    validationStatus: template.validationStatus || 'not_generated',
  }))
  const defaultTemplate = templates.find((item) => item.isDefault) || templates[0]
  const garments = Array.isArray(raw.garments) ? raw.garments : Array.from(
    new Map(batch.items.map((item) => [
      item.garmentId || item.garmentImageId,
      {
        id: item.garmentId || item.id,
        batchId: batch.id,
        garmentImageId: item.garmentImageId,
        serverAssetId: item.garmentServerAssetId,
        garmentFileName: item.garmentFileName,
        index: item.index,
        selected: true,
        createdAt: item.createdAt,
      } satisfies BatchTryOnGarment,
    ])).values(),
  )
  const presetSelection = resolveBatchTryOnPresetSelection({
    ...DEFAULT_BATCH_TRY_ON_PRESET_SELECTION,
    ...(raw.presetSelection || {}),
  })
  return syncLegacyTemplateFields({
    ...batch,
    templates,
    garments,
    sampleGarmentId: garments.some((item) => item.id === batch.sampleGarmentId)
      ? batch.sampleGarmentId
      : garments[0]?.id,
    fontReferenceOverrides: raw.fontReferenceOverrides && typeof raw.fontReferenceOverrides === 'object'
      ? raw.fontReferenceOverrides
      : {},
    styleProfiles: Array.isArray(raw.styleProfiles) ? raw.styleProfiles : [],
    items: batch.items.map((item) => ({
      ...item,
      templateId: item.templateId || defaultTemplate?.id,
      templateImageId: item.templateImageId || defaultTemplate?.imageId,
      templateServerAssetId: item.templateServerAssetId || defaultTemplate?.serverAssetId,
      templateName: item.templateName || defaultTemplate?.displayName,
      garmentId: item.garmentId || garments.find((garment) => garment.garmentImageId === item.garmentImageId)?.id,
      presetSelection: item.presetSelection || presetSelection,
      presetSummary: item.presetSummary || summarizeBatchTryOnPresets(item.presetSelection || presetSelection),
    })),
    presetSelection,
    adminTestMode: false,
    combinationMode: raw.combinationMode === 'one_to_one' ? 'one_to_one' : 'cartesian',
    concurrency: ([1, 2, 3, 5, 10, 12].includes(Number(batch.concurrency)) ? batch.concurrency : 12),
  })
}

export function syncLegacyTemplateFields(batch: BatchTryOnBatch): BatchTryOnBatch {
  const defaultTemplate = batch.templates.find((item) => item.isDefault) || batch.templates[0]
  return {
    ...batch,
    templateImageId: defaultTemplate?.imageId || null,
    templateServerAssetId: defaultTemplate?.serverAssetId,
    templateSourceType: defaultTemplate?.sourceType,
    templateSourceId: defaultTemplate?.sourceId,
    templateFileName: defaultTemplate?.fileName,
    templateWidth: defaultTemplate?.width,
    templateHeight: defaultTemplate?.height,
  }
}

export function withTemplateFilenameInfo(batch: BatchTryOnBatch, item: BatchTryOnItem) {
  const selectedTemplates = batch.templates.filter((template) => template.selected)
  const derivedIndex = item.templateId
    ? selectedTemplates.findIndex((template) => template.id === item.templateId) + 1
    : 0
  return {
    garmentFileName: item.garmentFileName,
    templateName: item.templateName,
    templateIndex: item.templateOrder || (derivedIndex > 0 ? derivedIndex : undefined),
    templateCount: item.templateCount || selectedTemplates.length,
    index: item.index,
  }
}

export function resetItemForNewRun(item: BatchTryOnItem): BatchTryOnItem {
  return {
    ...item,
    status: 'pending',
    taskId: undefined,
    outputImageId: undefined,
    outputTaskId: undefined,
    serverReviewItemId: undefined,
    serverReviewStatus: undefined,
    serverCurrentVersionId: undefined,
    serverApprovedVersionId: undefined,
    regenerationCount: undefined,
    error: undefined,
    startedAt: undefined,
    finishedAt: undefined,
  }
}

export function summarizeItems(items: BatchTryOnItem[]) {
  return items.reduce((summary, item) => {
    summary[item.status]++
    return summary
  }, { pending: 0, queued: 0, retry_waiting: 0, running: 0, done: 0, error: 0, stopped: 0 })
}

export function restoreServerStyleProfiles(
  profiles: NonNullable<ServerJobBatch['style_profiles']>,
  garments: BatchTryOnGarment[],
): BatchGarmentStyleProfile[] {
  return profiles.map((profile) => {
    const structure = profile.structure_json || {}
    const view = profile.view_rules_json || {}
    const preservation = profile.preservation_rules_json || {}
    const design = (preservation.design_rules && typeof preservation.design_rules === 'object')
      ? preservation.design_rules as Record<string, unknown>
      : {}
    const rules = (preservation.structure_rules && typeof preservation.structure_rules === 'object')
      ? preservation.structure_rules as Record<string, unknown>
      : {}
    const coveredAssets = new Set(profile.covered_garment_asset_ids_json || [])
    const coveredGarments = garments.filter((garment) => garment.serverAssetId && coveredAssets.has(garment.serverAssetId))
    const sourceGarment = garments.find((garment) => garment.serverAssetId === profile.source_sample_asset_id)
    return {
      profileKey: profile.profile_key,
      sourceSampleAssetId: profile.source_sample_asset_id,
      sourceGarmentId: sourceGarment?.id || profile.source_sample_asset_id,
      category: profile.category,
      garmentStructure: {
        neckline: typeof structure.neckline === 'string' ? structure.neckline : undefined,
        sleeveType: typeof structure.sleeve_type === 'string' ? structure.sleeve_type : undefined,
        fit: typeof structure.fit === 'string' ? structure.fit : undefined,
        closure: typeof structure.closure === 'string' ? structure.closure : undefined,
        hemType: typeof structure.hem_type === 'string' ? structure.hem_type : undefined,
      },
      viewRules: {
        supportsFront: view.supports_front !== false,
        supportsBack: view.supports_back !== false,
        frontBackMustNotSwap: view.front_back_must_not_swap !== false,
      },
      designRules: {
        preserveText: design.preserve_text !== false,
        preserveNumbers: design.preserve_numbers !== false,
        preserveNames: design.preserve_names !== false,
        preserveGraphics: design.preserve_graphics !== false,
        preserveFontStyle: design.preserve_font_style !== false,
        preserveElementPosition: design.preserve_element_position !== false,
      },
      structureRules: {
        preserveNeckline: rules.preserve_neckline !== false,
        preserveSleeves: rules.preserve_sleeves !== false,
        preserveGarmentLength: rules.preserve_garment_length !== false,
        preserveSilhouette: rules.preserve_silhouette !== false,
      },
      firstSampleObservation: profile.first_sample_observation_json || undefined,
      analysisModel: profile.analysis_model || '',
      analysisVersion: profile.analysis_version,
      coveredGarmentIds: coveredGarments.map((garment) => garment.id),
    }
  })
}

function stripExtension(filename: string) {
  return filename.replace(/\.[^.]+$/, '').trim() || '未命名模板'
}
