import { describe, expect, it } from 'vitest'
import type { BatchTryOnItem } from '../types'
import { findAdjacentReviewItem, findNextPendingReviewItem } from './batchTryOnReviewQueue'

function item(id: string, status: BatchTryOnItem['status'], review: BatchTryOnItem['serverReviewStatus']): BatchTryOnItem {
  return {
    id: `client-${id}`, batchId: 'batch', garmentImageId: `garment-${id}`,
    garmentFileName: `${id}.png`, index: Number(id), status, createdAt: 1,
    serverReviewItemId: `review-${id}`, serverReviewStatus: review,
  }
}

describe('batch try-on review queue navigation', () => {
  it('selects the next succeeded pending item in actual queue order and wraps', () => {
    const items = [item('1', 'done', 'approved'), item('2', 'running', 'regenerating'), item('3', 'done', 'pending'), item('4', 'done', 'pending')]
    expect(findNextPendingReviewItem(items, 'review-1')?.serverReviewItemId).toBe('review-3')
    expect(findNextPendingReviewItem(items, 'review-4')?.serverReviewItemId).toBe('review-3')
  })

  it('returns null after the last pending item is handled', () => {
    const items = [item('1', 'done', 'approved'), item('2', 'running', 'regenerating')]
    expect(findNextPendingReviewItem(items, 'review-1')).toBeNull()
  })

  it('moves manually without changing review state', () => {
    const items = [item('1', 'done', 'approved'), item('2', 'error', 'generation_failed'), item('3', 'done', 'pending')]
    expect(findAdjacentReviewItem(items, 'review-2', -1)?.serverReviewItemId).toBe('review-1')
    expect(findAdjacentReviewItem(items, 'review-2', 1)?.serverReviewItemId).toBe('review-3')
    expect(items[1].serverReviewStatus).toBe('generation_failed')
  })
})
