import { describe, expect, it } from 'vitest'
import { createBatchTryOnFileNames, sanitizeBatchTryOnFileBase } from './batchTryOnFiles'

describe('batch try-on output filenames', () => {
  it('keeps source stems, Chinese and leading zeroes', () => {
    expect(createBatchTryOnFileNames([
      { garmentFileName: 'A001-front.jpg', index: 8 },
      { garmentFileName: '中文款式.jpeg', index: 2 },
      { garmentFileName: '06-blue-jersey.webp', index: 0 },
    ], ['png', 'png', 'png'])).toEqual([
      'A001-front.png',
      '中文款式.png',
      '06-blue-jersey.png',
    ])
  })

  it('sanitizes unsafe names and resolves duplicate stems', () => {
    expect(sanitizeBatchTryOnFileBase('  A/\\:*?"<>| shirt.jpg')).toBe('A-shirt')
    expect(sanitizeBatchTryOnFileBase('CON.png')).toBe('CON-file')
    expect(createBatchTryOnFileNames([
      { garmentFileName: 'shirt.png', index: 0 },
      { garmentFileName: 'shirt.jpg', index: 1 },
      { garmentFileName: 'shirt.webp', index: 2 },
    ], ['png', 'png', 'png'])).toEqual(['shirt.png', 'shirt-2.png', 'shirt-3.png'])
  })
})
