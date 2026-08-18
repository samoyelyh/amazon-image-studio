import type { BatchGarmentStyleProfile, BatchTryOnBatch, BatchTryOnItem } from '../types'
import { buildBatchTryOnPrompt } from './batchTryOnPrompt'
import type { JobBatchSubmitInput, ServerJob } from './jobsApi'
import { findStyleProfileForGarment } from './batchTryOnStyleAnalysisApi'
import { batchStyleProfileSnapshot } from './batchTryOnStyleProfile'

export interface PreparedBatchTryOnSubmissionItem {
  item: BatchTryOnItem
  size: string
  aspectRatio: string
  templateAssetId: string
  garmentAssetId: string
  presetSelection: BatchTryOnBatch['presetSelection']
  presetSummary: string
}

export function collectPreparedBatchTryOnGarments(preparedItems: PreparedBatchTryOnSubmissionItem[]) {
  return Array.from(new Map(preparedItems.map((prepared) => [
    prepared.item.garmentId || prepared.item.garmentImageId,
    {
      garmentId: prepared.item.garmentId || prepared.item.garmentImageId,
      assetId: prepared.garmentAssetId,
      filename: prepared.item.garmentFileName,
    },
  ])).values())
}

export function buildBatchTryOnSubmissionItems(
  batch: BatchTryOnBatch,
  preparedItems: PreparedBatchTryOnSubmissionItem[],
  styleProfiles: BatchGarmentStyleProfile[],
): JobBatchSubmitInput['items'] {
  return preparedItems.map((prepared) => {
    const profile = findStyleProfileForGarment(
      styleProfiles,
      prepared.item.garmentId || prepared.item.garmentImageId,
    )
    if (!profile) throw new Error(`${prepared.item.garmentFileName} 没有匹配到批次款式结构，请重新分析。`)
    return {
      client_item_id: prepared.item.id,
      prompt: buildBatchTryOnPrompt({
        garmentFileName: prepared.item.garmentFileName,
        templateName: prepared.item.templateName,
        outputSize: prepared.size,
        presetSelection: prepared.presetSelection,
        extraRequirements: batch.extraRequirements,
        batchStyleProfile: profile,
      }),
      reference_asset_ids: [prepared.templateAssetId, prepared.garmentAssetId],
      size: prepared.size,
      aspect_ratio: prepared.aspectRatio,
      quality: batch.params.quality,
      output_format: batch.params.output_format,
      output_compression: batch.params.output_compression,
      metadata: {
        garment_filename: prepared.item.garmentFileName,
        garment_id: prepared.item.garmentId,
        garment_asset_id: prepared.garmentAssetId,
        qc_reference_asset_id: prepared.garmentAssetId,
        template_id: prepared.item.templateId,
        template_name: prepared.item.templateName,
        template_index: prepared.item.templateOrder,
        template_count: prepared.item.templateCount,
        preset_codes: prepared.presetSelection,
        preset_summary: prepared.presetSummary,
        batch_style_profile: batchStyleProfileSnapshot(profile),
        first_sample_observation: profile.firstSampleObservation || null,
        index: prepared.item.index,
      },
    }
  })
}

export function applySubmittedBatchTryOnJobs(
  items: BatchTryOnItem[],
  submittedItemIds: string[],
  jobs: ServerJob[],
) {
  const submittedIds = new Set(submittedItemIds)
  const jobByItem = new Map(jobs.map((job) => [job.client_item_id, job]))
  return items.map((item) => {
    if (!submittedIds.has(item.id)) return item
    const job = jobByItem.get(item.id)
    return {
      ...item,
      taskId: job?.id,
      serverBatchId: job?.batch_id || item.serverBatchId,
      status: 'queued' as const,
      error: undefined,
      outputImageId: undefined,
      outputTaskId: undefined,
      serverOutputAssetId: undefined,
      serverOutputFilename: undefined,
      serverOutputDownloadFilename: undefined,
      serverOutputDownloadUrl: undefined,
      serverVersionNumber: job?.review_version_number ?? undefined,
      startedAt: undefined,
      finishedAt: undefined,
      serverReviewItemId: job?.review_item_id ?? undefined,
      serverReviewStatus: (job?.review_status as BatchTryOnItem['serverReviewStatus']) ?? 'pending',
      serverCurrentVersionId: job?.current_version_id ?? undefined,
      serverApprovedVersionId: job?.approved_version_id ?? undefined,
      regenerationCount: job?.regeneration_count ?? 0,
    }
  })
}
