import { describe, expect, it } from 'vitest'
import { scaleSelectionBounds, scaleStrokes, workingImageSize } from './materialExtractCanvas'

describe('material extraction canvas coordinates', () => {
  it('keeps small images at native resolution', () => {
    expect(workingImageSize(800, 600)).toEqual({ width: 800, height: 600 })
  })

  it('scales large images without changing aspect ratio', () => {
    expect(workingImageSize(4000, 2000)).toEqual({ width: 1600, height: 800 })
  })

  it('maps the working selection and brush strokes back to source pixels', () => {
    expect(scaleSelectionBounds({ x: 10, y: 20, width: 50, height: 60 }, 3200, 1600, 1600, 800))
      .toEqual({ x: 20, y: 40, width: 100, height: 120 })
    expect(scaleStrokes([{ tool: 'select', size: 10, points: [{ x: 4, y: 6 }] }], 3200, 1600, 1600, 800))
      .toEqual([{ tool: 'select', size: 20, points: [{ x: 8, y: 12 }] }])
  })
})

