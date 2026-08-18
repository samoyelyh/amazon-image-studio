import { describe, expect, it } from 'vitest'
import { normalizeRegionBounds, normalizeRegionStrokes, regionBounds, validRegionBounds } from './batchRegionReplace'

describe('batch region replace geometry', () => {
  it('stores normalized bounds independent from pixel dimensions', () => {
    expect(regionBounds([{ action: 'paint', radius: 0.05, points: [{ x: 0.4, y: 0.3 }, { x: 0.6, y: 0.7 }] }])).toEqual({
      x: 0.35, y: 0.25, width: 0.3, height: 0.5,
    })
  })

  it('clamps serialized strokes to the unit square', () => {
    expect(normalizeRegionStrokes([{ action: 'paint', radius: 2, points: [{ x: -1, y: 4 }] }])).toEqual([
      { action: 'paint', radius: 1, points: [{ x: 0, y: 1 }] },
    ])
  })

  it('normalizes a frame drawn in reverse and keeps it in the unit square', () => {
    expect(normalizeRegionBounds({ x: 0.8, y: 0.9, width: -0.6, height: -1.2 })).toEqual({
      x: 0.2, y: 0, width: 0.6, height: 0.9,
    })
    expect(validRegionBounds({ x: 0.2, y: 0.2, width: 0.4, height: 0.3 })).toBe(true)
    expect(validRegionBounds({ x: 0.2, y: 0.2, width: 0, height: 0.3 })).toBe(false)
  })
})
