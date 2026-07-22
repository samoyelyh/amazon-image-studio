import { describe, expect, it } from 'vitest'
import { calculateDeliverySize, normalizeAspectRatio, resolveImageSize, validateDeliverySize } from './imageSizeResolver'

describe('image size resolver', () => {
  it.each([
    ['1024x1024', '1:1', false, false],
    ['1024x1536', '3:4', true, false],
    ['1536x1024', '4:3', false, true],
    ['1536x864', '16:9', false, true],
    ['864x1536', '9:16', true, false],
  ])('keeps width and height orientation for %s', (size, ratio, portrait, landscape) => {
    const resolved = resolveImageSize(size, ratio)
    expect(resolved.width! < resolved.height!).toBe(portrait)
    expect(resolved.width! > resolved.height!).toBe(landscape)
    expect(resolved.aspectRatio).toBe(ratio)
  })

  it('keeps auto separate from concrete dimensions', () => {
    expect(resolveImageSize('auto')).toEqual({ aspectRatio: 'auto', width: null, height: null, providerSize: 'auto' })
  })

  it('converts approximate display ratios into canonical API ratios', () => {
    expect(resolveImageSize('1088x1440', 'auto').aspectRatio).toBe('3:4')
    expect(resolveImageSize('1088x1440', '≈3:4').aspectRatio).toBe('3:4')
    expect(normalizeAspectRatio(' 4 × 3 ')).toBe('4:3')
    expect(normalizeAspectRatio('3840:1280')).toBe('3:1')
    expect(resolveImageSize('3840x1280', 'auto')).toMatchObject({
      aspectRatio: '3:1',
      providerSize: '3840x1280',
    })
  })

  it('recovers stale template and malformed ratio values from concrete dimensions', () => {
    expect(resolveImageSize('1088 × 1440', 'template')).toMatchObject({
      aspectRatio: '3:4',
      providerSize: '1088x1440',
    })
    expect(resolveImageSize('4096x2304', 'invalid').aspectRatio).toBe('16:9')
  })

  it('rejects unsupported field formats instead of silently defaulting', () => {
    expect(() => resolveImageSize('3:4', '3:4')).toThrow('图片尺寸格式无效')
  })

  it.each([
    ['2K', '1:1', '2048x2048'],
    ['2K', '3:4', '1536x2048'],
    ['4K', '16:9', '4096x2304'],
    ['4K', '9:16', '2304x4096'],
  ] as const)('creates exact %s delivery dimensions for %s', (tier, ratio, expected) => {
    expect(calculateDeliverySize(tier, ratio)).toBe(expected)
  })

  it('preserves custom delivery dimensions instead of clamping them to provider limits', () => {
    expect(resolveImageSize('4096x3072', '4:3')).toMatchObject({
      width: 4096,
      height: 3072,
      providerSize: '4096x3072',
    })
    expect(validateDeliverySize('4096x3072')).toEqual({ width: 4096, height: 3072 })
  })
})
