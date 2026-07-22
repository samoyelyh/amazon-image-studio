import { authenticatedFetch } from './authApi'
import type { ServerJob } from './jobsApi'

export type BatchTryOnReviewStatus = 'pending' | 'approved' | 'rejected' | 'regenerating' | 'generation_failed'
export type BatchTryOnRetryMode = 'direct' | 'with_review_notes'

export interface BatchTryOnReviewAsset {
  id: string
  filename: string
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
  review_status: BatchTryOnReviewStatus
  current_version_id: string | null
  approved_version_id: string | null
  regeneration_count: number
  garment_asset: BatchTryOnReviewAsset
  model_asset: BatchTryOnReviewAsset
  current_version: BatchTryOnReviewVersion | null
  versions: BatchTryOnReviewVersion[]
}

export interface BatchTryOnRegenerateResponse {
  review: BatchTryOnReviewDetail
  job: ServerJob
}

export function getBatchTryOnReviewDetail(itemId: string) {
  return authenticatedFetch<BatchTryOnReviewDetail>(`/batch-tryon/items/${itemId}/review-detail`)
}

export function approveBatchTryOnVersion(itemId: string, sourceVersionId: string) {
  return authenticatedFetch<BatchTryOnReviewDetail>(`/batch-tryon/items/${itemId}/approve`, {
    method: 'POST',
    body: JSON.stringify({ source_version_id: sourceVersionId }),
  })
}

export function regenerateBatchTryOnVersion(itemId: string, input: {
  source_version_id: string
  retry_mode: BatchTryOnRetryMode
  review_notes: string | null
  idempotency_key: string
}) {
  return authenticatedFetch<BatchTryOnRegenerateResponse>(`/batch-tryon/items/${itemId}/regenerate`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
}
