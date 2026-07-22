import type { BatchTryOnItem } from '../types'

export function getReviewableQueueItems(items: BatchTryOnItem[]) {
  return items.filter((item) => Boolean(item.serverReviewItemId))
}

export function findNextPendingReviewItem(items: BatchTryOnItem[], currentReviewItemId: string) {
  const ordered = getReviewableQueueItems(items)
  const currentIndex = ordered.findIndex((item) => item.serverReviewItemId === currentReviewItemId)
  const start = currentIndex >= 0 ? currentIndex + 1 : 0
  const candidates = [...ordered.slice(start), ...ordered.slice(0, start)]
  return candidates.find((item) => (
    item.serverReviewItemId !== currentReviewItemId
    && item.status === 'done'
    && item.serverReviewStatus === 'pending'
  )) ?? null
}

export function findAdjacentReviewItem(items: BatchTryOnItem[], currentReviewItemId: string, direction: -1 | 1) {
  const ordered = getReviewableQueueItems(items)
  if (ordered.length < 2) return null
  const currentIndex = ordered.findIndex((item) => item.serverReviewItemId === currentReviewItemId)
  if (currentIndex < 0) return ordered[0]
  return ordered[(currentIndex + direction + ordered.length) % ordered.length]
}
