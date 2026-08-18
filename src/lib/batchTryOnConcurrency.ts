import type { BatchTryOnBatch } from '../types'

export function getBatchTryOnConcurrencyOptions(
): BatchTryOnBatch['concurrency'][] {
  return [1, 2, 3, 5, 10, 12]
}

export function normalizeBatchTryOnConcurrency(
  value: number,
): BatchTryOnBatch['concurrency'] {
  const options = getBatchTryOnConcurrencyOptions()
  return options.includes(value as BatchTryOnBatch['concurrency'])
    ? value as BatchTryOnBatch['concurrency']
    : Math.max(...options.filter((option) => option <= value), 1) as BatchTryOnBatch['concurrency']
}
