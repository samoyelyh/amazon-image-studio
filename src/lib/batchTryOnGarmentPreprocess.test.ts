import { describe, expect, it } from 'vitest'
import {
  buildMissingGarmentReferenceMessage,
  clampNormalizedRect,
  compactGarmentTransform,
  garmentTransformMetadata,
  getMissingRequiredGarmentReferenceViews,
  normalizedRectFromPoints,
  resolveEffectiveGarmentReferencePreviews,
} from './batchTryOnGarmentPreprocess'
import type { BatchTryOnGarment, BatchTryOnTemplate } from '../types'

describe('batch try-on garment preprocessing', () => {
  it('stores crop regions in normalized coordinates', () => {
    expect(normalizedRectFromPoints({ x: 0.75, y: 0.8 }, { x: 0.25, y: 0.2 })).toEqual({
      x: 0.25, y: 0.2, width: 0.5, height: 0.6000000000000001,
    })
  })

  it('keeps the rectangle inside the source image', () => {
    expect(clampNormalizedRect({ x: -1, y: 0.8, width: 5, height: 0.9 })).toEqual({
      x: 0, y: 0.8, width: 1, height: 0.19999999999999996,
    })
  })

  it('lets Luna and image generation preview switch between front, back and both references', () => {
    const template = { id: 'template', imageId: 'template-image', fileName: 'template.png' } as BatchTryOnTemplate
    const garment = {
      id: 'garment', garmentImageId: 'original', garmentFileName: 'shirt.png',
      references: {
        front: { imageId: 'front', serverAssetId: 'front-asset', fileName: 'shirt-front.png', garmentView: 'front' },
        back: { imageId: 'back', serverAssetId: 'back-asset', fileName: 'shirt-back.png', garmentView: 'back' },
      },
    } as BatchTryOnGarment

    template.garmentView = 'front'
    expect(resolveEffectiveGarmentReferencePreviews(template, garment).map((item) => item.imageId)).toEqual(['front'])
    template.garmentView = 'back'
    expect(resolveEffectiveGarmentReferencePreviews(template, garment).map((item) => item.imageId)).toEqual(['back'])
    template.garmentView = 'front_back'
    expect(resolveEffectiveGarmentReferencePreviews(template, garment).map((item) => item.imageId)).toEqual(['front', 'back'])
    expect(resolveEffectiveGarmentReferencePreviews(template, garment).map((item) => item.serverAssetId)).toEqual(['front-asset', 'back-asset'])
  })

  it('falls back to the original garment when the requested reference is missing', () => {
    const template = { id: 'template', imageId: 'template-image', fileName: 'template.png', garmentView: 'back' } as BatchTryOnTemplate
    const garment = { id: 'garment', garmentImageId: 'original', garmentFileName: 'shirt.png' } as BatchTryOnGarment
    expect(resolveEffectiveGarmentReferencePreviews(template, garment)).toEqual([{
      imageId: 'original', fileName: 'shirt.png', view: 'original', derived: false,
    }])
  })

  it('reports a missing explicit back reference instead of treating the original as valid', () => {
    const template = {
      id: 'template', imageId: 'template-image', fileName: 'gift.png', displayName: '礼品场景图', garmentView: 'back',
    } as BatchTryOnTemplate
    const garment = {
      id: 'garment', garmentImageId: 'original', garmentFileName: 'shirt.png',
    } as BatchTryOnGarment

    expect(getMissingRequiredGarmentReferenceViews(template, garment)).toEqual(['back'])
    expect(buildMissingGarmentReferenceMessage(template, garment)).toContain('尚未保存背面参考图')
    garment.references = {
      back: { imageId: 'back', fileName: 'shirt-back.png', garmentView: 'back' } as never,
    }
    expect(getMissingRequiredGarmentReferenceViews(template, garment)).toEqual([])
    expect(getMissingRequiredGarmentReferenceViews(template, garment, true)).toEqual(['back'])
  })

  it('requires both clean references when front and back are selected explicitly', () => {
    const template = {
      id: 'template', imageId: 'template-image', fileName: 'flow.png', garmentView: 'front_back',
    } as BatchTryOnTemplate
    const garment = {
      id: 'garment', garmentImageId: 'original', garmentFileName: 'shirt.png',
      references: {
        front: { imageId: 'front', serverAssetId: 'front-asset', fileName: 'shirt-front.png', garmentView: 'front' },
      },
    } as BatchTryOnGarment

    expect(getMissingRequiredGarmentReferenceViews(template, garment, true)).toEqual(['back'])
  })

  it('compacts dense erase paths before storing transform metadata', () => {
    const transform = compactGarmentTransform({
      mode: 'crop', crop: { x: 0, y: 0, width: 1, height: 1 },
      eraseStrokes: [{
        radius: 0.025,
        points: Array.from({ length: 12000 }, (_, index) => ({
          x: index / 12000,
          y: 0.5 + Math.sin(index / 100) * 0.1,
        })),
      }],
    })
    expect(transform.eraseStrokes[0].points.length).toBeLessThanOrEqual(500)
    const metadata = garmentTransformMetadata(transform)
    expect(JSON.stringify(metadata).length).toBeLessThan(20000)
    expect(metadata).not.toHaveProperty('transform')
  })
})
