import type { BatchTryOnFontReference, BatchTryOnGarment } from '../types'

export function batchTryOnFontReferenceKey(templateId: string, garmentId: string) {
  return `${templateId}:${garmentId}`
}

export function resolveBatchTryOnFontReference(
  templateId: string,
  garment: Pick<BatchTryOnGarment, 'id' | 'fontReference'>,
  overrides: Record<string, BatchTryOnFontReference> | undefined,
) {
  const override = overrides?.[batchTryOnFontReferenceKey(templateId, garment.id)]
  return {
    reference: override || garment.fontReference,
    source: override ? 'combination' as const : garment.fontReference ? 'garment' as const : 'none' as const,
  }
}
