import { describe, expect, it } from 'vitest'
import { extractFontReferenceIdentifiers, matchFontReferencesByIdentifier } from './batchTryOnFontReferenceMatching'

describe('font reference filename matching', () => {
  it('preserves leading zeros and matches the requested FOTJ identifier', () => {
    expect(extractFontReferenceIdentifiers('Arizona Cardinals FOTJ-NF0000532 拷贝.jpg')).toEqual(['0000532'])
    const result = matchFontReferencesByIdentifier(
      [{ id: 'garment-532', garmentFileName: 'Arizona Cardinals FOTJ-NF0000532 拷贝.jpg' }],
      [{ value: 'font-532', name: 'custom-font-0000532.png' }],
    )
    expect(result.assignments).toMatchObject([{
      garmentId: 'garment-532', matchedIdentifier: '0000532',
      reference: { value: 'font-532' },
    }])
  })

  it('does not confuse different identifiers or silently choose duplicate garments', () => {
    const result = matchFontReferencesByIdentifier(
      [
        { id: 'a', garmentFileName: 'team-NF0000532.jpg' },
        { id: 'b', garmentFileName: 'copy-NF0000532.jpg' },
        { id: 'c', garmentFileName: 'team-NF0000533.jpg' },
      ],
      [
        { value: 'ambiguous', name: 'font-0000532.png' },
        { value: 'matched', name: 'font-0000533.png' },
        { value: 'missing', name: 'font-0000999.png' },
      ],
    )
    expect(result.assignments.map((item) => item.garmentId)).toEqual(['c'])
    expect(result.ambiguous).toHaveLength(1)
    expect(result.unmatched.map((item) => item.value)).toEqual(['missing'])
  })

  it('rejects two reference files targeting the same garment', () => {
    const result = matchFontReferencesByIdentifier(
      [{ id: 'a', garmentFileName: 'team-NF0000532.jpg' }],
      [
        { value: 'first', name: 'font-0000532-front.png' },
        { value: 'second', name: 'font-0000532-back.png' },
      ],
    )
    expect(result.assignments).toHaveLength(0)
    expect(result.duplicateGarmentMatches).toHaveLength(1)
  })
})
