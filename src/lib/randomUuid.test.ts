import { afterEach, describe, expect, it, vi } from 'vitest'
import { randomUuid } from './randomUuid'

afterEach(() => vi.unstubAllGlobals())

describe('randomUuid', () => {
  it('uses the native implementation when available', () => {
    vi.stubGlobal('crypto', { randomUUID: () => 'native-uuid' })
    expect(randomUuid()).toBe('native-uuid')
  })

  it('works when randomUUID is unavailable on an HTTP LAN origin', () => {
    vi.stubGlobal('crypto', {
      getRandomValues: (bytes: Uint8Array) => {
        bytes.forEach((_, index) => { bytes[index] = index })
        return bytes
      },
    })
    expect(randomUuid()).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
  })

  it('still produces a UUID-shaped value without Web Crypto', () => {
    vi.stubGlobal('crypto', undefined)
    expect(randomUuid()).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
  })
})
