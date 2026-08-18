import { describe, expect, it } from 'vitest'
import {
  getBatchTryOnConcurrencyOptions,
  normalizeBatchTryOnConcurrency,
} from './batchTryOnConcurrency'

describe('batch try-on concurrency access', () => {
  it('allows every user to select the full supported range', () => {
    expect(getBatchTryOnConcurrencyOptions()).toEqual([1, 2, 3, 5, 10, 12])
    expect(normalizeBatchTryOnConcurrency(10)).toBe(10)
    expect(normalizeBatchTryOnConcurrency(12)).toBe(12)
  })
})
