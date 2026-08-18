import { loadImage } from './canvasImage'
import type {
  BatchTryOnEraseStroke,
  BatchTryOnGarment,
  BatchTryOnGarmentReference,
  BatchTryOnGarmentView,
  BatchTryOnGarmentTransform,
  BatchTryOnNormalizedRect,
  BatchTryOnTemplate,
  BatchTryOnTemplateGarmentView,
} from '../types'

export const FULL_GARMENT_RECT: BatchTryOnNormalizedRect = { x: 0, y: 0, width: 1, height: 1 }

const ERASE_POINT_MIN_DISTANCE = 0.0025
const MAX_ERASE_POINTS_TOTAL = 2500
const MAX_ERASE_POINTS_PER_STROKE = 500

function roundNormalized(value: number) {
  return Math.round(Math.max(0, Math.min(1, value)) * 1_000_000) / 1_000_000
}

function samplePoints<T>(points: T[], limit: number): T[] {
  if (points.length <= limit) return points
  if (limit <= 1) return [points[0]]
  return Array.from({ length: limit }, (_, index) => points[
    Math.round(index * (points.length - 1) / (limit - 1))
  ])
}

/** Compact browser pointer events while preserving the reproducible erase path. */
export function compactGarmentTransform(
  transform: BatchTryOnGarmentTransform,
): BatchTryOnGarmentTransform {
  let remainingPoints = MAX_ERASE_POINTS_TOTAL
  const strokeCount = transform.eraseStrokes.length
  const eraseStrokes = transform.eraseStrokes.map((stroke, strokeIndex) => {
    const normalized = stroke.points.map((point) => ({
      x: roundNormalized(point.x),
      y: roundNormalized(point.y),
    }))
    const distanceFiltered = normalized.filter((point, index) => {
      if (index === 0 || index === normalized.length - 1) return true
      const previous = normalized[index - 1]
      return Math.hypot(point.x - previous.x, point.y - previous.y) >= ERASE_POINT_MIN_DISTANCE
    })
    const fairShare = Math.max(2, Math.floor(remainingPoints / Math.max(1, strokeCount - strokeIndex)))
    const points = samplePoints(distanceFiltered, Math.min(MAX_ERASE_POINTS_PER_STROKE, fairShare))
    remainingPoints = Math.max(0, remainingPoints - points.length)
    return {
      radius: Math.round(Math.max(0.001, Math.min(1, stroke.radius)) * 1_000_000) / 1_000_000,
      points,
    }
  }).filter((stroke) => stroke.points.length > 0)
  const crop = clampNormalizedRect(transform.crop)
  return {
    mode: transform.mode,
    crop: {
      x: roundNormalized(crop.x),
      y: roundNormalized(crop.y),
      width: roundNormalized(crop.width),
      height: roundNormalized(crop.height),
    },
    eraseStrokes,
  }
}

export interface EffectiveGarmentReferencePreview {
  imageId: string
  serverAssetId?: string
  fileName: string
  view: BatchTryOnGarmentView | 'original'
  derived: boolean
}

/** Mirrors the server-side effective garment reference selection used by Luna and image generation. */
export function resolveEffectiveGarmentReferencePreviews(
  template: BatchTryOnTemplate,
  garment: BatchTryOnGarment,
): EffectiveGarmentReferencePreview[] {
  const requested = template.garmentView || 'auto'
  const reference = (view: 'front' | 'back' | 'detail'): EffectiveGarmentReferencePreview | undefined => {
    const value: BatchTryOnGarmentReference | undefined = garment.references?.[view]
    return value ? {
      imageId: value.imageId,
      serverAssetId: value.serverAssetId,
      fileName: value.fileName,
      view,
      derived: true,
    } : undefined
  }
  const original: EffectiveGarmentReferencePreview = {
    imageId: garment.garmentImageId,
    serverAssetId: garment.serverAssetId,
    fileName: garment.garmentFileName,
    view: 'original',
    derived: false,
  }
  const front = reference('front')
  const back = reference('back')
  const detail = reference('detail')
  if (requested === 'front') return [front || original]
  if (requested === 'back') return [back || original]
  if (requested === 'detail') return [detail || front || back || original]
  if (requested === 'front_back') return [front, back].filter((item): item is EffectiveGarmentReferencePreview => Boolean(item)).length
    ? [front, back].filter((item): item is EffectiveGarmentReferencePreview => Boolean(item))
    : [original]
  return [original]
}

export function clampNormalizedRect(rect: BatchTryOnNormalizedRect): BatchTryOnNormalizedRect {
  const x = Math.max(0, Math.min(1, rect.x))
  const y = Math.max(0, Math.min(1, rect.y))
  return {
    x,
    y,
    width: Math.max(0.01, Math.min(1 - x, rect.width)),
    height: Math.max(0.01, Math.min(1 - y, rect.height)),
  }
}

export function normalizedRectFromPoints(
  start: { x: number; y: number }, end: { x: number; y: number },
): BatchTryOnNormalizedRect {
  return clampNormalizedRect({
    x: Math.min(start.x, end.x),
    y: Math.min(start.y, end.y),
    width: Math.abs(end.x - start.x),
    height: Math.abs(end.y - start.y),
  })
}

function erase(ctx: CanvasRenderingContext2D, strokes: BatchTryOnEraseStroke[], width: number, height: number) {
  ctx.save()
  ctx.globalCompositeOperation = 'destination-out'
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'
  for (const stroke of strokes) {
    if (!stroke.points.length) continue
    ctx.lineWidth = Math.max(2, stroke.radius * Math.max(width, height) * 2)
    ctx.beginPath()
    ctx.moveTo(stroke.points[0].x * width, stroke.points[0].y * height)
    for (const point of stroke.points.slice(1)) ctx.lineTo(point.x * width, point.y * height)
    if (stroke.points.length === 1) ctx.lineTo(stroke.points[0].x * width + 0.01, stroke.points[0].y * height)
    ctx.stroke()
  }
  ctx.restore()
}

export async function renderGarmentReference(
  sourceDataUrl: string, transform: BatchTryOnGarmentTransform,
): Promise<string> {
  const image = await loadImage(sourceDataUrl)
  const crop = clampNormalizedRect(transform.crop)
  const sourceWidth = image.naturalWidth
  const sourceHeight = image.naturalHeight
  const sx = Math.round(crop.x * sourceWidth)
  const sy = Math.round(crop.y * sourceHeight)
  const sw = Math.max(1, Math.round(crop.width * sourceWidth))
  const sh = Math.max(1, Math.round(crop.height * sourceHeight))
  const canvas = document.createElement('canvas')
  canvas.width = transform.mode === 'crop' ? sw : sourceWidth
  canvas.height = transform.mode === 'crop' ? sh : sourceHeight
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('当前浏览器不支持 Canvas')
  ctx.imageSmoothingEnabled = true
  ctx.imageSmoothingQuality = 'high'
  if (transform.mode === 'crop') {
    ctx.drawImage(image, sx, sy, sw, sh, 0, 0, sw, sh)
    erase(ctx, transform.eraseStrokes.map((stroke) => ({
      ...stroke,
      points: stroke.points.map((point) => ({
        x: (point.x - crop.x) / crop.width,
        y: (point.y - crop.y) / crop.height,
      })),
      radius: stroke.radius / Math.max(crop.width, crop.height),
    })), sw, sh)
  } else {
    ctx.drawImage(image, 0, 0)
    ctx.save()
    ctx.globalCompositeOperation = 'destination-out'
    ctx.fillRect(0, 0, sourceWidth, sy)
    ctx.fillRect(0, sy + sh, sourceWidth, sourceHeight - sy - sh)
    ctx.fillRect(0, sy, sx, sh)
    ctx.fillRect(sx + sw, sy, sourceWidth - sx - sw, sh)
    ctx.restore()
    erase(ctx, transform.eraseStrokes, sourceWidth, sourceHeight)
  }
  return canvas.toDataURL('image/png')
}

export function garmentTransformMetadata(transform: BatchTryOnGarmentTransform) {
  const compact = compactGarmentTransform(transform)
  return {
    coordinate_space: 'normalized_0_1',
    transform_mode: compact.mode,
    crop: compact.crop,
    keep_outside_transparent: compact.mode === 'keep',
    erase_strokes: compact.eraseStrokes,
    purpose: 'ai_reference_cleanup',
    provider_edit_mask: false,
  }
}
