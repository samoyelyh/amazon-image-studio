import type { BatchTryOnBatch, BatchTryOnGarment, BatchTryOnItem, BatchTryOnTemplate } from '../types'
import { randomUuid } from './randomUuid'
import {
  resolveBatchTryOnPresetSelection,
  summarizeBatchTryOnPresets,
} from './batchTryOnPresets'

export function buildBatchTryOnMatrix(
  batch: BatchTryOnBatch,
  createItemId: () => string = randomUuid,
): BatchTryOnItem[] {
  const pairs = getBatchTryOnCombinationPairs(batch)
  const presetSelection = resolveBatchTryOnPresetSelection(batch.presetSelection)
  const presetSummary = summarizeBatchTryOnPresets(presetSelection)
  const createdAt = Date.now()

  return pairs.map(({ template, garment, templateIndex }, index) => ({
    id: createItemId(),
    batchId: batch.id,
    templateId: template.id,
    templateImageId: template.imageId,
    templateServerAssetId: template.serverAssetId,
    templateName: template.displayName.trim() || stripExtension(template.fileName),
    templateOrder: templateIndex + 1,
    templateCount: batch.templates.filter((item) => item.selected).length,
    garmentId: garment.id,
    garmentImageId: garment.garmentImageId,
    garmentServerAssetId: garment.serverAssetId,
    garmentFileName: garment.garmentFileName,
    presetSelection: { ...presetSelection },
    presetSummary,
    index,
    status: 'pending' as const,
    createdAt,
  }))
}

export interface BatchTryOnCombinationPair {
  template: BatchTryOnTemplate
  garment: BatchTryOnGarment
  templateIndex: number
  garmentIndex: number
}

export function batchTryOnCombinationKey(templateId?: string, garmentId?: string) {
  return templateId && garmentId ? `${templateId}:${garmentId}` : null
}

/**
 * Returns only production combinations that have not already been submitted in
 * the current workspace queue. Validation samples intentionally do not reserve
 * a production combination.
 */
export function getUnsubmittedBatchTryOnCombinationPairs(
  batch: BatchTryOnBatch,
  existingItems: BatchTryOnItem[] = batch.items,
): BatchTryOnCombinationPair[] {
  const submittedKeys = new Set(existingItems.flatMap((item) => {
    if (item.id.startsWith('validation:')) return []
    const key = batchTryOnCombinationKey(item.templateId, item.garmentId)
    return key ? [key] : []
  }))
  return getBatchTryOnCombinationPairs(batch).filter(({ template, garment }) => (
    !submittedKeys.has(batchTryOnCombinationKey(template.id, garment.id)!)
  ))
}

export function buildUnsubmittedBatchTryOnMatrix(
  batch: BatchTryOnBatch,
  existingItems: BatchTryOnItem[] = batch.items,
  createItemId: () => string = randomUuid,
): BatchTryOnItem[] {
  const pendingKeys = new Set(getUnsubmittedBatchTryOnCombinationPairs(batch, existingItems).map(
    ({ template, garment }) => batchTryOnCombinationKey(template.id, garment.id)!,
  ))
  return buildBatchTryOnMatrix(batch, createItemId).filter((item) => {
    const key = batchTryOnCombinationKey(item.templateId, item.garmentId)
    return Boolean(key && pendingKeys.has(key))
  })
}

export function getBatchTryOnCombinationPairs(batch: BatchTryOnBatch): BatchTryOnCombinationPair[] {
  const templates = batch.templates.filter((item) => item.selected)
  const garments = batch.garments.filter((item) => item.selected)
  if ((batch.combinationMode || 'cartesian') === 'one_to_one') {
    if (templates.length !== garments.length) return []
    return templates.map((template, index) => ({
      template,
      garment: garments[index],
      templateIndex: index,
      garmentIndex: index,
    }))
  }
  return templates.flatMap((template, templateIndex) => garments.map((garment, garmentIndex) => ({
    template,
    garment,
    templateIndex,
    garmentIndex,
  })))
}

export function estimateBatchTryOnGenerationCount(batch: BatchTryOnBatch) {
  const templateCount = batch.templates.filter((item) => item.selected).length
  const garmentCount = batch.garments.filter((item) => item.selected).length
  return (batch.combinationMode || 'cartesian') === 'one_to_one'
    ? Math.min(templateCount, garmentCount)
    : templateCount * garmentCount
}

export function getBatchTryOnCombinationError(batch: BatchTryOnBatch) {
  if ((batch.combinationMode || 'cartesian') !== 'one_to_one') return ''
  const templateCount = batch.templates.filter((item) => item.selected).length
  const garmentCount = batch.garments.filter((item) => item.selected).length
  return templateCount === garmentCount
    ? ''
    : `一一对应模式要求模板和服装数量相同；当前模板 ${templateCount} 张，服装 ${garmentCount} 件`
}

export function buildBatchTryOnTemplateMatrix(
  batch: BatchTryOnBatch,
  templateId: string,
  createItemId: () => string = randomUuid,
): BatchTryOnItem[] {
  if (!batch.templates.some((template) => template.id === templateId && template.selected)) return []
  const pairs = getBatchTryOnCombinationPairs(batch).filter((pair) => pair.template.id === templateId)
  if (!pairs.length) return []
  const allowedGarmentIds = new Set(pairs.map((pair) => pair.garment.id))
  return buildBatchTryOnMatrix({
    ...batch,
    combinationMode: 'cartesian',
    templates: batch.templates.map((template) => ({ ...template, selected: template.id === templateId })),
    garments: batch.garments.map((garment) => ({ ...garment, selected: allowedGarmentIds.has(garment.id) })),
  }, createItemId)
}

function stripExtension(filename: string) {
  return filename.replace(/\.[^.]+$/, '').trim() || '未命名模板'
}
