import type { BatchTryOnItem } from '../types'
import type { JobOutput, ServerJob } from './jobsApi'

export type BatchTryOnServerSyncMode = 'batch' | 'regeneration'

export interface BatchTryOnServerSyncOptions {
  mode: BatchTryOnServerSyncMode
  paused?: boolean
  importOutput: (output: JobOutput) => Promise<string>
  now?: () => number
}

export function selectCurrentBatchTryOnJobs(jobs: ServerJob[]) {
  const selected = new Map<string | null, ServerJob>()
  for (const job of jobs) {
    const existing = selected.get(job.client_item_id)
    if (!existing || job.is_current_review_version || (!existing.is_current_review_version && job.created_at > existing.created_at)) {
      selected.set(job.client_item_id, job)
    }
  }
  return selected
}

export async function buildBatchTryOnServerJobPatch(
  item: BatchTryOnItem,
  job: ServerJob,
  options: BatchTryOnServerSyncOptions,
): Promise<Partial<BatchTryOnItem>> {
  const now = options.now ?? Date.now
  const regeneration = options.mode === 'regeneration'

  if (job.status === 'succeeded' && job.outputs[0]) {
    let outputImageId = item.outputImageId
    if (!outputImageId || item.outputTaskId !== job.id) {
      outputImageId = await options.importOutput(job.outputs[0])
    }
    return {
      taskId: job.id,
      outputTaskId: job.id,
      outputImageId,
      serverOutputAssetId: job.outputs[0].asset_id,
      serverOutputFilename: job.outputs[0].display_filename || job.outputs[0].filename,
      serverOutputDownloadFilename: job.outputs[0].download_filename || job.outputs[0].filename,
      serverOutputDownloadUrl: job.outputs[0].download_url,
      serverVersionNumber: job.review_version_number ?? (regeneration ? item.serverVersionNumber : undefined),
      status: 'done',
      error: undefined,
      finishedAt: job.finished_at ? new Date(job.finished_at).getTime() : now(),
      serverReviewItemId: job.review_item_id ?? item.serverReviewItemId,
      serverReviewStatus: (job.review_status as BatchTryOnItem['serverReviewStatus']) ?? item.serverReviewStatus,
      serverCurrentVersionId: job.current_version_id ?? item.serverCurrentVersionId,
      serverApprovedVersionId: job.approved_version_id ?? item.serverApprovedVersionId,
      regenerationCount: job.regeneration_count,
    }
  }

  if (job.status === 'failed' || job.status === 'cancelled') {
    return {
      taskId: job.id,
      status: job.status === 'cancelled' ? 'stopped' : 'error',
      error: job.error_message || (job.status === 'cancelled'
        ? '任务已取消'
        : regeneration ? '重新生成失败' : '生成失败'),
      finishedAt: job.finished_at ? new Date(job.finished_at).getTime() : now(),
      serverReviewItemId: job.review_item_id ?? item.serverReviewItemId,
      serverReviewStatus: (job.review_status as BatchTryOnItem['serverReviewStatus']) ?? 'generation_failed',
      serverCurrentVersionId: job.current_version_id ?? item.serverCurrentVersionId,
      serverApprovedVersionId: job.approved_version_id ?? item.serverApprovedVersionId,
      regenerationCount: job.regeneration_count,
    }
  }

  return {
    taskId: job.id,
    status: options.paused
      ? 'stopped'
      : job.status === 'running'
        ? 'running'
        : job.status === 'retry_waiting'
          ? 'retry_waiting'
          : 'queued',
    error: undefined,
    startedAt: job.started_at ? new Date(job.started_at).getTime() : item.startedAt,
    ...(regeneration ? { finishedAt: undefined } : {}),
    serverReviewItemId: job.review_item_id ?? item.serverReviewItemId,
    serverReviewStatus: (job.review_status as BatchTryOnItem['serverReviewStatus'])
      ?? (regeneration ? 'regenerating' : item.serverReviewStatus),
    serverCurrentVersionId: job.current_version_id ?? item.serverCurrentVersionId,
    serverApprovedVersionId: job.approved_version_id ?? item.serverApprovedVersionId,
    regenerationCount: job.regeneration_count,
    serverVersionNumber: job.review_version_number ?? item.serverVersionNumber,
  }
}

export function activeServerJobIds(jobs: ServerJob[]) {
  return jobs
    .filter((job) => !['succeeded', 'failed', 'cancelled'].includes(job.status))
    .map((job) => job.id)
}

export function restorableRegenerationTaskIds(items: BatchTryOnItem[]) {
  return items.flatMap((item) => (
    item.taskId
    && item.serverReviewStatus === 'regenerating'
    && ['queued', 'retry_waiting', 'running'].includes(item.status)
      ? [item.taskId]
      : []
  ))
}

export function isTerminalServerBatchStatus(status: string) {
  return ['succeeded', 'failed', 'cancelled', 'partially_succeeded'].includes(status)
}
