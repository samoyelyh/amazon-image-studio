import { authenticatedFetch } from './authApi'
import type { Asset } from './contentApi'

export interface AttachmentReferenceLibraryUnderstanding {
  id: string
  version_number: number
  status: string
  structured: Record<string, unknown>
  analysis_model: string | null
  error_message: string | null
}

export interface AttachmentReferenceLibraryItem {
  id: string
  name: string
  description: string
  category_key: string | null
  module_key: string
  reference_role: 'TEMPLATE' | 'SCENE' | 'PRINT' | 'OTHER'
  asset: Asset
  guidance: string
  tags: string[]
  is_featured: boolean
  is_active: boolean
  sort_order: number
  state_version: number
  understanding: AttachmentReferenceLibraryUnderstanding | null
}

export function listAttachmentReferenceLibrary(moduleKey?: string, categoryKey?: string) {
  const query = new URLSearchParams()
  if (moduleKey) query.set('module_key', moduleKey)
  if (categoryKey) query.set('category_key', categoryKey)
  const suffix = query.size ? `?${query.toString()}` : ''
  return authenticatedFetch<AttachmentReferenceLibraryItem[]>(`/attachment-reference-library${suffix}`)
}

export interface AttachmentReferenceLibraryMutation {
  name: string
  description?: string
  category_key?: string | null
  module_key: string
  reference_role: 'TEMPLATE' | 'SCENE' | 'PRINT' | 'OTHER'
  asset_id: string
  guidance?: string
  tags?: string[]
  is_featured?: boolean
  is_active?: boolean
  sort_order?: number
}

export function listAdminAttachmentReferenceLibrary(moduleKey?: string, categoryKey?: string) {
  const query = new URLSearchParams()
  if (moduleKey) query.set('module_key', moduleKey)
  if (categoryKey) query.set('category_key', categoryKey)
  const suffix = query.size ? `?${query.toString()}` : ''
  return authenticatedFetch<AttachmentReferenceLibraryItem[]>(`/admin/attachment-reference-library${suffix}`)
}

export function createAttachmentReferenceLibraryItem(input: AttachmentReferenceLibraryMutation) {
  return authenticatedFetch<AttachmentReferenceLibraryItem>('/admin/attachment-reference-library', {
    method: 'POST', body: JSON.stringify(input),
  })
}

export type AttachmentReferenceLibrarySourceMutation = Omit<AttachmentReferenceLibraryMutation, 'asset_id' | 'is_active'>

export function addAttachmentOutputToReferenceLibrary(outputId: string, input: AttachmentReferenceLibrarySourceMutation) {
  return authenticatedFetch<AttachmentReferenceLibraryItem>(`/admin/attachment-reference-library/from-output/${outputId}`, {
    method: 'POST', body: JSON.stringify(input),
  })
}

export function addAttachmentMaterialToReferenceLibrary(materialItemId: string, input: AttachmentReferenceLibrarySourceMutation) {
  return authenticatedFetch<AttachmentReferenceLibraryItem>(`/admin/attachment-reference-library/from-material-item/${materialItemId}`, {
    method: 'POST', body: JSON.stringify(input),
  })
}

export function updateAttachmentReferenceLibraryItem(itemId: string, input: Partial<Omit<AttachmentReferenceLibraryMutation, 'asset_id'>>) {
  return authenticatedFetch<AttachmentReferenceLibraryItem>(`/admin/attachment-reference-library/${itemId}`, {
    method: 'PATCH', body: JSON.stringify(input),
  })
}

export function reanalyzeAttachmentReferenceLibraryItem(itemId: string) {
  return authenticatedFetch<AttachmentReferenceLibraryItem>(`/admin/attachment-reference-library/${itemId}/reanalyze`, {
    method: 'POST',
  })
}
