import { formatImageRatio, parseRatio, type SizeTier } from './size'

const SIZE_PATTERN = /^(\d+)x(\d+)$/
const TIER_LONG_EDGE: Record<SizeTier, number> = { '1K': 1024, '2K': 2048, '4K': 4096 }
export const MAX_DELIVERY_EDGE = 10_000
export const MAX_DELIVERY_PIXELS = 40_000_000

export interface ResolvedImageSize {
  aspectRatio: string
  width: number | null
  height: number | null
  providerSize: string
}

export function resolveImageSize(size: string, aspectRatio = 'auto'): ResolvedImageSize {
  const providerSize = size === 'auto' ? 'auto' : normalizeDeliverySize(size)
  const normalizedAspectRatio = normalizeAspectRatio(aspectRatio)
  if (providerSize === 'auto') {
    // Old drafts may contain display-only values such as `≈3:4`, `4 × 3`, or
    // `template`. Do not let those values block a new request.
    return { aspectRatio: normalizedAspectRatio || 'auto', width: null, height: null, providerSize }
  }

  const match = providerSize.match(SIZE_PATTERN)
  if (!match) throw new Error('图片尺寸格式无效，请重新选择尺寸。')
  const width = Number(match[1])
  const height = Number(match[2])
  const resolvedAspectRatio = normalizedAspectRatio === 'auto' || !normalizedAspectRatio
    ? inferAspectRatio(width, height)
    : normalizedAspectRatio
  return { aspectRatio: resolvedAspectRatio, width, height, providerSize }
}

/** Converts UI/display ratios into the canonical width:height API format. */
export function normalizeAspectRatio(value: string): string | null {
  const normalized = value
    .trim()
    .toLowerCase()
    .replace(/^≈\s*/, '')
    .replace(/\s+/g, '')
    .replace(/[x×]/g, ':')

  if (!normalized || normalized === 'auto' || normalized === 'template') return normalized === 'auto' ? 'auto' : null
  const parsed = parseRatio(normalized)
  if (!parsed) return null
  if (Number.isInteger(parsed.width) && Number.isInteger(parsed.height)) {
    const divisor = greatestCommonDivisor(parsed.width, parsed.height)
    return `${parsed.width / divisor}:${parsed.height / divisor}`
  }
  return `${formatRatioNumber(parsed.width)}:${formatRatioNumber(parsed.height)}`
}

export function inferAspectRatio(width: number, height: number): string {
  const displayRatio = formatImageRatio(width, height)
  const normalizedDisplayRatio = normalizeAspectRatio(displayRatio)
  if (normalizedDisplayRatio) return normalizedDisplayRatio

  const divisor = greatestCommonDivisor(Math.round(width), Math.round(height))
  return `${Math.round(width) / divisor}:${Math.round(height) / divisor}`
}

export function normalizeDeliverySize(size: string): string {
  const match = size.trim().toLowerCase().replace(/\s+/g, '').replace(/[×]/g, 'x').match(SIZE_PATTERN)
  if (!match) return size.trim()
  return `${Number(match[1])}x${Number(match[2])}`
}

function formatRatioNumber(value: number): string {
  return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(6)))
}

function greatestCommonDivisor(a: number, b: number): number {
  return b === 0 ? Math.abs(a) || 1 : greatestCommonDivisor(b, a % b)
}

export function validateDeliverySize(size: string): { width: number; height: number } | null {
  const match = normalizeDeliverySize(size).match(SIZE_PATTERN)
  if (!match) return null
  const width = Number(match[1])
  const height = Number(match[2])
  if (width < 1 || height < 1 || width > MAX_DELIVERY_EDGE || height > MAX_DELIVERY_EDGE) return null
  if (width * height > MAX_DELIVERY_PIXELS) return null
  return { width, height }
}

export function calculateDeliverySize(tier: SizeTier, ratio: string): string | null {
  const parsed = parseRatio(ratio)
  if (!parsed) return null
  const target = parsed.width / parsed.height
  const longEdge = TIER_LONG_EDGE[tier]
  const width = target >= 1 ? longEdge : Math.max(1, Math.round(longEdge * target))
  const height = target >= 1 ? Math.max(1, Math.round(longEdge / target)) : longEdge
  return `${width}x${height}`
}
