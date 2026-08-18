import type { BatchTryOnItem } from '../types'

export interface SelectedBatchTryOnReviewItem {
  itemId: string
  versionId: string
  generatedAssetId: string
  templateId: string
  garmentAssetId: string
  clientItemId: string
  templateName: string
  garmentFileName: string
}

export function isBatchTryOnBulkRegeneratable(item: BatchTryOnItem): boolean {
  return Boolean(
    item.serverReviewItemId
    && item.serverCurrentVersionId
    && item.serverOutputAssetId
    && item.templateId
    && item.garmentServerAssetId
    && item.status === 'done',
  )
}

export function toSelectedBatchTryOnReviewItem(
  item: BatchTryOnItem,
): SelectedBatchTryOnReviewItem | null {
  if (!isBatchTryOnBulkRegeneratable(item)) return null
  return {
    itemId: item.serverReviewItemId!,
    versionId: item.serverCurrentVersionId!,
    generatedAssetId: item.serverOutputAssetId!,
    templateId: item.templateId!,
    garmentAssetId: item.garmentServerAssetId!,
    clientItemId: item.id,
    templateName: item.templateName || '默认模板',
    garmentFileName: item.garmentFileName,
  }
}

export function summarizeBatchTryOnSelection(
  selected: Iterable<SelectedBatchTryOnReviewItem>,
) {
  const items = [...selected]
  return {
    itemCount: items.length,
    templateCount: new Set(items.map((item) => item.templateId)).size,
    garmentCount: new Set(items.map((item) => item.garmentAssetId)).size,
  }
}
