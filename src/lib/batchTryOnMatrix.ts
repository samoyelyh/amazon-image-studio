import type { BatchTryOnBatch, BatchTryOnItem } from '../types'
import { randomUuid } from './randomUuid'
import {
  resolveBatchTryOnPresetSelection,
  summarizeBatchTryOnPresets,
} from './batchTryOnPresets'

export function buildBatchTryOnMatrix(
  batch: BatchTryOnBatch,
  createItemId: () => string = randomUuid,
): BatchTryOnItem[] {
  const templates = batch.templates.filter((item) => item.selected)
  const garments = batch.garments.filter((item) => item.selected)
  const presetSelection = resolveBatchTryOnPresetSelection(batch.presetSelection)
  const presetSummary = summarizeBatchTryOnPresets(presetSelection)
  const createdAt = Date.now()

  return templates.flatMap((template, templateIndex) => garments.map((garment, garmentIndex) => ({
    id: createItemId(),
    batchId: batch.id,
    templateId: template.id,
    templateImageId: template.imageId,
    templateServerAssetId: template.serverAssetId,
    templateName: template.displayName.trim() || stripExtension(template.fileName),
    garmentId: garment.id,
    garmentImageId: garment.garmentImageId,
    garmentServerAssetId: garment.serverAssetId,
    garmentFileName: garment.garmentFileName,
    presetSelection: { ...presetSelection },
    presetSummary,
    index: templateIndex * garments.length + garmentIndex,
    status: 'pending' as const,
    createdAt,
  })))
}

function stripExtension(filename: string) {
  return filename.replace(/\.[^.]+$/, '').trim() || '未命名模板'
}
