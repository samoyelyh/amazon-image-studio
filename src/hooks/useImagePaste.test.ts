import { describe, expect, it } from 'vitest'
import { extractClipboardImageFiles, type ClipboardImageItemLike } from './useImagePaste'

describe('extractClipboardImageFiles', () => {
  it('extracts only images and gives pasted images stable user-friendly names', () => {
    const png = new File(['png'], 'image.png', { type: 'image/png' })
    const items: ClipboardImageItemLike[] = [
      { type: 'text/plain', getAsFile: () => null },
      { type: 'image/png', getAsFile: () => png },
    ]

    const files = extractClipboardImageFiles(items, new Date('2026-08-10T02:03:04Z').getTime())

    expect(files).toHaveLength(1)
    expect(files[0].type).toBe('image/png')
    expect(files[0].name).toMatch(/^pasted-image-\d{8}-\d{6}-1\.png$/)
  })

  it('ignores clipboard image items that do not contain a file', () => {
    expect(extractClipboardImageFiles([{ type: 'image/png', getAsFile: () => null }])).toEqual([])
  })
})
