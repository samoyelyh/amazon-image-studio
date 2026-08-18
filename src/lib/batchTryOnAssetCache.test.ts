import { describe, expect, it, vi } from 'vitest'
import { resolveBatchTryOnAssetId } from './batchTryOnAssetCache'

describe('resolveBatchTryOnAssetId', () => {
  it('uploads one local template only once for a 32-item matrix', async () => {
    const cache = new Map<string, string>()
    const upload = vi.fn(async () => 'server-template-id')

    const results = []
    for (let index = 0; index < 32; index += 1) {
      results.push(await resolveBatchTryOnAssetId(cache, 'local-template-id', undefined, upload))
    }

    expect(new Set(results)).toEqual(new Set(['server-template-id']))
    expect(upload).toHaveBeenCalledTimes(1)
  })

  it('prefers an existing server asset without uploading', async () => {
    const upload = vi.fn(async () => 'unexpected')
    const result = await resolveBatchTryOnAssetId(
      new Map(), 'local-garment-id', 'existing-garment-id', upload,
    )
    expect(result).toBe('existing-garment-id')
    expect(upload).not.toHaveBeenCalled()
  })
})
