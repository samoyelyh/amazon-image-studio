import { describe, expect, it } from 'vitest'
import { createBatchTryOnFileNames, sanitizeBatchTryOnFileBase } from './batchTryOnFiles'

describe('batch try-on download file names', () => {
  it('creates safe names and never overwrites duplicates', () => {
    expect(sanitizeBatchTryOnFileBase('team:shirt?.jpg')).toBe('team_shirt_')
    expect(createBatchTryOnFileNames([
      { garmentFileName: 'team:shirt?.jpg', index: 0 },
      { garmentFileName: 'team:shirt?.jpg', index: 0 },
      { garmentFileName: 'team:shirt?.jpg', index: 1 },
    ], ['jpg', 'jpg', 'webp'])).toEqual([
      'team_shirt__tryon_001.jpg',
      'team_shirt__tryon_001_2.jpg',
      'team_shirt__tryon_002.webp',
    ])
  })
})
