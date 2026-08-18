import { describe, expect, it, vi } from 'vitest'
import type { BatchTryOnItem } from '../types'
import type { JobOutput, ServerJob } from './jobsApi'
import {
  activeServerJobIds,
  buildBatchTryOnServerJobPatch,
  isTerminalServerBatchStatus,
  restorableRegenerationTaskIds,
  selectCurrentBatchTryOnJobs,
} from './batchTryOnServerSync'

const output: JobOutput = {
  id: 'output-1', asset_id: 'asset-output-1', filename: 'internal.png',
  display_filename: 'model-shirt.png', download_filename: 'model-shirt.png',
  download_url: '/assets/asset-output-1/download', mime_type: 'image/png',
  width: 1024, height: 1024, size: 100, sequence_number: 0,
  url: '/signed/output', url_expires_at: null,
}

function item(patch: Partial<BatchTryOnItem> = {}): BatchTryOnItem {
  return {
    id: 'item-1', batchId: 'batch-1', templateImageId: 'template-image', garmentImageId: 'garment-image',
    garmentFileName: 'shirt.png', index: 0, status: 'queued', createdAt: 1, ...patch,
  }
}

function job(patch: Partial<ServerJob> = {}): ServerJob {
  return {
    id: 'job-1', organization_id: 'org-1', batch_id: 'batch-1', project_id: null,
    quota_reservation_id: 'reservation-1', operation_code: 'batch_tryon.generate', workspace_type: 'batch_tryon',
    queue_name: 'batch_tryon_queue', capability: 'image_edit', model_code: 'image-2', client_item_id: 'item-1',
    status: 'queued', progress: 0, result_json: null, attempts: 0, technical_retry_count: 0, max_attempts: 3,
    error_code: null, error_message: null, cancel_requested_at: null, started_at: null, heartbeat_at: null,
    next_retry_at: null, next_dispatch_at: null, finished_at: null, generation_duration_ms: null,
    requested_aspect_ratio: null, requested_width: null, requested_height: null, resolved_provider_size: null,
    actual_width: null, actual_height: null, size_mismatch: false, review_item_id: 'review-1', review_status: 'pending',
    current_version_id: 'version-1', approved_version_id: null, regeneration_count: 0,
    review_version_id: 'version-1', review_version_number: 1, is_current_review_version: true,
    created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', outputs: [],
    ...patch,
  }
}

describe('batch try-on server state synchronization', () => {
  it('selects the current review job for each stable client item id', () => {
    const oldCurrent = job({ id: 'old-current', is_current_review_version: true, created_at: '2026-01-01T00:00:00Z' })
    const newerHistory = job({ id: 'newer-history', is_current_review_version: false, created_at: '2026-01-02T00:00:00Z' })
    const selected = selectCurrentBatchTryOnJobs([oldCurrent, newerHistory])
    expect(selected.get('item-1')?.id).toBe('old-current')
  })

  it('imports a new succeeded output and preserves server review relations', async () => {
    const importOutput = vi.fn(async () => 'local-output-image')
    const patch = await buildBatchTryOnServerJobPatch(item(), job({
      status: 'succeeded', outputs: [output], finished_at: '2026-01-01T00:00:03Z',
      review_status: 'approved', approved_version_id: 'version-1', regeneration_count: 2,
    }), { mode: 'batch', importOutput })

    expect(importOutput).toHaveBeenCalledWith(output)
    expect(patch).toMatchObject({
      status: 'done', outputImageId: 'local-output-image', outputTaskId: 'job-1',
      serverOutputAssetId: 'asset-output-1', serverReviewItemId: 'review-1',
      serverReviewStatus: 'approved', serverCurrentVersionId: 'version-1',
      serverApprovedVersionId: 'version-1', regenerationCount: 2,
    })
  })

  it('does not import the same task output twice', async () => {
    const importOutput = vi.fn(async () => 'unused')
    const patch = await buildBatchTryOnServerJobPatch(item({
      outputImageId: 'cached-output', outputTaskId: 'job-1',
    }), job({ status: 'succeeded', outputs: [output] }), { mode: 'batch', importOutput })
    expect(importOutput).not.toHaveBeenCalled()
    expect(patch.outputImageId).toBe('cached-output')
  })

  it('keeps batch and regeneration failure messages behavior-compatible', async () => {
    const importOutput = async () => 'unused'
    const batchPatch = await buildBatchTryOnServerJobPatch(item(), job({ status: 'failed' }), {
      mode: 'batch', importOutput, now: () => 100,
    })
    const regenerationPatch = await buildBatchTryOnServerJobPatch(item(), job({ status: 'failed' }), {
      mode: 'regeneration', importOutput, now: () => 100,
    })
    expect(batchPatch).toMatchObject({ status: 'error', error: '生成失败', finishedAt: 100 })
    expect(regenerationPatch).toMatchObject({ status: 'error', error: '重新生成失败', finishedAt: 100 })
  })

  it('maps paused, retrying, and regenerating states without changing IDs', async () => {
    const importOutput = async () => 'unused'
    const paused = await buildBatchTryOnServerJobPatch(item(), job({ status: 'running' }), {
      mode: 'batch', paused: true, importOutput,
    })
    const retrying = await buildBatchTryOnServerJobPatch(item(), job({ status: 'retry_waiting', review_status: null }), {
      mode: 'regeneration', importOutput,
    })
    expect(paused.status).toBe('stopped')
    expect(retrying).toMatchObject({
      taskId: 'job-1', status: 'retry_waiting', serverReviewStatus: 'regenerating', finishedAt: undefined,
    })
  })

  it('returns only active job IDs and recognizes every terminal batch status', () => {
    expect(activeServerJobIds([
      job({ id: 'queued', status: 'queued' }), job({ id: 'retry', status: 'retry_waiting' }),
      job({ id: 'done', status: 'succeeded' }), job({ id: 'failed', status: 'failed' }),
    ])).toEqual(['queued', 'retry'])
    expect(['succeeded', 'failed', 'cancelled', 'partially_succeeded'].every(isTerminalServerBatchStatus)).toBe(true)
    expect(isTerminalServerBatchStatus('running')).toBe(false)
  })

  it('restores polling only for active regenerated versions', () => {
    expect(restorableRegenerationTaskIds([
      item({ id: 'running', taskId: 'job-running', status: 'running', serverReviewStatus: 'regenerating' }),
      item({ id: 'done', taskId: 'job-done', status: 'done', serverReviewStatus: 'regenerating' }),
      item({ id: 'ordinary', taskId: 'job-ordinary', status: 'running', serverReviewStatus: 'pending' }),
    ])).toEqual(['job-running'])
  })
})
