import { describe, expect, it } from 'vitest'
import {
  getBatchTryOnConcurrencyOptions,
  normalizeBatchTryOnConcurrency,
} from './batchTryOnConcurrency'

describe('batch try-on concurrency access', () => {
  it('keeps ordinary users at three or below', () => {
    expect(getBatchTryOnConcurrencyOptions(false, false)).toEqual([1, 2, 3])
    expect(getBatchTryOnConcurrencyOptions(false, true)).toEqual([1, 2, 3])
    expect(normalizeBatchTryOnConcurrency(10, false, true)).toBe(3)
  })

  it('allows administrators to select ten only in test mode', () => {
    expect(getBatchTryOnConcurrencyOptions(true, false)).toEqual([1, 2, 3])
    expect(getBatchTryOnConcurrencyOptions(true, true)).toEqual([1, 2, 3, 5, 10])
    expect(normalizeBatchTryOnConcurrency(10, true, true)).toBe(10)
  })
})
