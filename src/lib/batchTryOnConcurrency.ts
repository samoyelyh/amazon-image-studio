import type { BatchTryOnBatch } from '../types'

export function getBatchTryOnConcurrencyOptions(
  isAdmin: boolean,
  adminTestMode: boolean,
): BatchTryOnBatch['concurrency'][] {
  return isAdmin && adminTestMode ? [1, 2, 3, 5, 10] : [1, 2, 3]
}

export function normalizeBatchTryOnConcurrency(
  value: number,
  isAdmin: boolean,
  adminTestMode: boolean,
): BatchTryOnBatch['concurrency'] {
  const options = getBatchTryOnConcurrencyOptions(isAdmin, adminTestMode)
  return options.includes(value as BatchTryOnBatch['concurrency'])
    ? value as BatchTryOnBatch['concurrency']
    : Math.max(...options.filter((option) => option <= value), 1) as BatchTryOnBatch['concurrency']
}
