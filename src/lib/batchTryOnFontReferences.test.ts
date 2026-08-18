import { describe, expect, it } from 'vitest'
import { batchTryOnFontReferenceKey, resolveBatchTryOnFontReference } from './batchTryOnFontReferences'

describe('batch try-on font reference priority', () => {
  const garment = {
    id: 'garment-1',
    fontReference: { imageId: 'default-image', fileName: 'default.png' },
  }

  it('prefers the current combination override', () => {
    const overrides = {
      [batchTryOnFontReferenceKey('template-1', garment.id)]: {
        imageId: 'override-image', fileName: 'override.png',
      },
    }
    expect(resolveBatchTryOnFontReference('template-1', garment, overrides)).toEqual({
      reference: overrides['template-1:garment-1'], source: 'combination',
    })
  })

  it('falls back to the garment default and then to none', () => {
    expect(resolveBatchTryOnFontReference('template-1', garment, {})).toEqual({
      reference: garment.fontReference, source: 'garment',
    })
    expect(resolveBatchTryOnFontReference('template-1', { id: 'garment-2' }, {})).toEqual({
      reference: undefined, source: 'none',
    })
  })
})
