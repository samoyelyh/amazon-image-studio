import { authenticatedFetch } from './authApi'
import type { ServerJob } from './jobsApi'

export type BatchTryOnReviewStatus = 'pending' | 'approved' | 'rejected' | 'regenerating' | 'generation_failed'
export type BatchTryOnRetryMode = 'direct' | 'with_review_notes' | 'with_detailed_prompt'
export type BatchTryOnManualErrorCode = 'left_right_sleeve' | 'front_back' | 'text_number' | 'color' | 'detail_composition'
export type BatchTryOnRegionReplaceType = 'back_name' | 'back_number' | 'wearer_left_shoulder_number' | 'wearer_right_shoulder_number' | 'custom_region'

export interface BatchTryOnReviewAsset {
  id: string
  filename: string
  display_filename: string
  download_filename: string
  download_url: string
  preview_url: string
  width: number
  height: number
  mime_type: string
  size: number
}

export interface BatchTryOnReviewVersion {
  id: string
  version_number: number
  parent_version_id: string | null
  generated_asset_id: string | null
  task_id: string | null
  source_filename: string | null
  display_filename: string | null
  download_filename: string | null
  output_format: string | null
  prompt_snapshot: string
  review_notes: string | null
  retry_mode: string
  generation_status: string
  review_status: string
  generated_asset: BatchTryOnReviewAsset | null
  created_at: string
  completed_at: string | null
  reviewed_by: string | null
  reviewed_at: string | null
  generation_duration_ms: number | null
}

export interface BatchTryOnReviewDetail {
  item_id: string
  batch_id: string
  client_item_id: string
  template_id: string | null
  review_status: BatchTryOnReviewStatus
  current_version_id: string | null
  approved_version_id: string | null
  regeneration_count: number
  template_name: string | null
  preset_summary: string | null
  preset_codes: Record<string, unknown> | null
  template_type: string | null
  template_prompt_id: string | null
  prompt_version: number | null
  effective_prompt_snapshot: string | null
  garment_asset: BatchTryOnReviewAsset
  model_asset: BatchTryOnReviewAsset
  image_c_asset: BatchTryOnReviewAsset | null
  current_version: BatchTryOnReviewVersion | null
  versions: BatchTryOnReviewVersion[]
}

export interface BatchTryOnRegenerateResponse {
  review: BatchTryOnReviewDetail
  job: ServerJob
}

export interface BatchTryOnRegionReplaceResponse {
  review: BatchTryOnReviewDetail
  job: ServerJob
}

export interface BatchTryOnBatchRegenerateSelection {
  item_id: string
  version_id: string
}

export interface BatchTryOnBatchRegenerateTask {
  item_id: string
  source_version_id: string
  version_id: string
  task_id: string
  client_item_id: string
  template_id: string | null
  garment_asset_id: string
  created: boolean
}

export interface BatchTryOnBatchRegenerateError {
  item_id: string
  version_id: string
  code: string
  message: string
}

export interface BatchTryOnBatchRegenerateResponse {
  requested_count: number
  created_count: number
  replayed_count: number
  failed_count: number
  created_tasks: BatchTryOnBatchRegenerateTask[]
  errors: BatchTryOnBatchRegenerateError[]
}

export interface BatchTryOnBatchDetailedAnalysisResponse {
  requested_count: number
  created_count: number
  replayed_count: number
  failed_count: number
  auto_regenerate: boolean
  analysis_tasks: Array<{
    item_id: string
    source_version_id: string
    analysis_job_id: string
    client_item_id: string
    created: boolean
    auto_regenerate: boolean
  }>
  errors: Array<{ item_id: string; version_id: string; code: string; message: string }>
}

export function getBatchTryOnReviewDetail(itemId: string, signal?: AbortSignal) {
  return authenticatedFetch<BatchTryOnReviewDetail>(`/batch-tryon/items/${itemId}/review-detail`, { signal })
}

export function listBatchTryOnReviewDetails(batchId: string, signal?: AbortSignal) {
  return authenticatedFetch<BatchTryOnReviewDetail[]>(`/batch-tryon/batches/${batchId}/review-items`, { signal })
}

export function approveBatchTryOnVersion(itemId: string, sourceVersionId: string) {
  return authenticatedFetch<BatchTryOnReviewDetail>(`/batch-tryon/items/${itemId}/approve`, {
    method: 'POST',
    body: JSON.stringify({ source_version_id: sourceVersionId }),
  })
}

export function discardBatchTryOnVersion(itemId: string, sourceVersionId: string) {
  return authenticatedFetch<BatchTryOnReviewDetail>(`/batch-tryon/items/${itemId}/discard`, {
    method: 'POST',
    body: JSON.stringify({ source_version_id: sourceVersionId }),
  })
}

export function regenerateBatchTryOnVersion(itemId: string, input: {
  source_version_id: string
  retry_mode: BatchTryOnRetryMode
  review_notes: string | null
  error_codes?: BatchTryOnManualErrorCode[]
  idempotency_key: string
}) {
  return authenticatedFetch<BatchTryOnRegenerateResponse>(`/batch-tryon/items/${itemId}/regenerate`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function analyzeBatchTryOnReviewVersion(itemId: string, input: {
  source_version_id: string
  focus_notes: string | null
  template_type: string | null
  prompt_preset_id: string | null
  template_prompt_override: string | null
  idempotency_key: string
}) {
  return authenticatedFetch<ServerJob>(`/batch-tryon/items/${itemId}/detailed-analysis`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function batchAnalyzeAndRegenerateBatchTryOnVersions(input: {
  items: Array<{ item_id: string; version_id: string }>
  focus_notes: string | null
  template_type: string | null
  prompt_preset_id: string | null
  template_prompt_override: string | null
  auto_regenerate: boolean
  idempotency_key: string
}) {
  return authenticatedFetch<BatchTryOnBatchDetailedAnalysisResponse>(
    '/batch-tryon/items/batch-detailed-analysis-auto-regenerate',
    { method: 'POST', body: JSON.stringify(input) },
  )
}

export function regionReplaceBatchTryOnVersion(itemId: string, input: {
  source_version_id: string
  target_mask_asset_id: string
  image_c_asset_id: string
  source_reference_mask_asset_id: string | null
  reference_patch_asset_id: string
  edit_region_type: BatchTryOnRegionReplaceType
  edit_prompt: string
  target_mask_metadata: Record<string, unknown>
  source_reference_metadata: Record<string, unknown>
  idempotency_key: string
}) {
  return authenticatedFetch<BatchTryOnRegionReplaceResponse>(`/batch-tryon/items/${itemId}/region-replace`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function approveBatchTryOnRegionReplaceVersion(itemId: string, versionId: string) {
  return authenticatedFetch<BatchTryOnReviewDetail>(`/batch-tryon/items/${itemId}/region-replace/approve`, {
    method: 'POST',
    body: JSON.stringify({ source_version_id: versionId }),
  })
}

export function discardBatchTryOnRegionReplaceVersion(itemId: string, versionId: string) {
  return authenticatedFetch<BatchTryOnReviewDetail>(`/batch-tryon/items/${itemId}/region-replace/discard`, {
    method: 'POST',
    body: JSON.stringify({ source_version_id: versionId }),
  })
}

export function selectBatchTryOnReviewVersion(itemId: string, versionId: string) {
  return authenticatedFetch<BatchTryOnReviewDetail>(`/batch-tryon/items/${itemId}/select-version`, {
    method: 'POST',
    body: JSON.stringify({ version_id: versionId }),
  })
}

export function batchRegenerateBatchTryOnVersions(input: {
  items: BatchTryOnBatchRegenerateSelection[]
  review_notes: string
  idempotency_key: string
}) {
  return authenticatedFetch<BatchTryOnBatchRegenerateResponse>(
    '/batch-tryon/items/batch-regenerate-with-notes',
    {
      method: 'POST',
      body: JSON.stringify(input),
    },
  )
}
