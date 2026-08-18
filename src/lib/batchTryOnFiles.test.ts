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

  it('combines template names and garment names for Cartesian combinations', () => {
    expect(createBatchTryOnFileNames([
      {
        garmentFileName: '06-blue-jersey.webp',
        templateName: '一个非常冗长的第一个模板名称',
        templateIndex: 1,
        templateCount: 2,
        index: 0,
      },
      {
        garmentFileName: '06-blue-jersey.webp',
        templateName: '另一个非常冗长的第二个模板名称',
        templateIndex: 2,
        templateCount: 2,
        index: 1,
      },
    ], ['png', 'png'])).toEqual([
      '一个非常冗长的第一个模板名称-06-blue-jersey.png',
      '另一个非常冗长的第二个模板名称-06-blue-jersey.png',
    ])
  })

  it('includes the template name when only one template participates', () => {
    expect(createBatchTryOnFileNames([{
      garmentFileName: 'A001-front.jpg',
      templateName: '唯一模板',
      templateIndex: 1,
      templateCount: 1,
      index: 0,
    }], ['png'])).toEqual(['唯一模板-A001-front.png'])
  })
})
