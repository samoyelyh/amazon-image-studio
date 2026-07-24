import { afterEach, describe, expect, it, vi } from 'vitest'
import { adjustQuota, estimateQuota } from './quotaApi'

afterEach(() => vi.unstubAllGlobals())

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('quota API', () => {
  it('sends estimate inputs to the server without accepting a client cost', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({ estimated_cost: 20 }))
    vi.stubGlobal('fetch', fetchMock)
    await estimateQuota({ operation_code: 'listing.generate', quantity: 2, quality: 'high' })
    const input = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string)
    expect(input).toEqual({ operation_code: 'listing.generate', quantity: 2, quality: 'high' })
    expect(input).not.toHaveProperty('estimated_cost')
  })

  it('includes an explicit idempotency key for adjustments', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({ account: {}, transaction: {} }, 201))
    vi.stubGlobal('fetch', fetchMock)
    await adjustQuota({ transaction_type: 'adjust', amount: 100, idempotency_key: 'manual:test-001', reason: 'test' })
    const input = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string)
    expect(input.idempotency_key).toBe('manual:test-001')
  })
})
