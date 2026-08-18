import { authenticatedFetch } from './authApi'
import type { Asset } from './contentApi'

export interface PrintAssetGroup {
  id: string
  code: string
  name: string
  product_type: string | null
  remark: string | null
  created_at: string
  updated_at: string
}

export interface PrintAssetItem {
  id: string
  asset_group_id: string | null
  asset_code: string
  asset_name: string
  asset_type: 'print' | 'logo' | 'number' | 'name' | 'graphic'
  category: string | null
  tags: string[]
  default_position: Record<string, unknown> | null
  allow_rotate: boolean
  allow_stretch: boolean
  keep_ratio_default: boolean
  version: number
  status: string
  created_at: string
  updated_at: string
  asset: Asset
}

export interface PrintAssetPage { items: PrintAssetItem[]; total: number }

export function listPrintAssetGroups() {
  return authenticatedFetch<PrintAssetGroup[]>('/print-design/asset-groups')
}

export function createPrintAssetGroup(input: { code: string; name: string; product_type?: string; remark?: string }) {
  return authenticatedFetch<PrintAssetGroup>('/print-design/asset-groups', { method: 'POST', body: JSON.stringify(input) })
}

export function updatePrintAssetGroup(groupId: string, input: { name?: string; product_type?: string | null; remark?: string | null }) {
  return authenticatedFetch<PrintAssetGroup>(`/print-design/asset-groups/${groupId}`, { method: 'PATCH', body: JSON.stringify(input) })
}

export function listPrintAssets(search = '', groupId = '') {
  const query = new URLSearchParams()
  if (search.trim()) query.set('search', search.trim())
  if (groupId) query.set('group_id', groupId)
  return authenticatedFetch<PrintAssetPage>(`/print-design/assets${query.size ? `?${query}` : ''}`)
}

export function registerPrintAsset(input: {
  asset_id: string
  asset_group_id?: string
  asset_code: string
  asset_name: string
  asset_type?: PrintAssetItem['asset_type']
  category?: string
  tags?: string[]
  default_position?: Record<string, unknown>
  allow_rotate?: boolean
  allow_stretch?: boolean
  keep_ratio_default?: boolean
  version?: number
}) {
  return authenticatedFetch<PrintAssetItem>('/print-design/assets', { method: 'POST', body: JSON.stringify(input) })
}

export function updatePrintAsset(itemId: string, input: Partial<{
  asset_group_id: string | null
  asset_name: string
  asset_type: PrintAssetItem['asset_type']
  category: string | null
  tags: string[]
  default_position: Record<string, unknown> | null
  allow_rotate: boolean
  allow_stretch: boolean
  keep_ratio_default: boolean
  status: 'active' | 'archived'
}>) {
  return authenticatedFetch<PrintAssetItem>(`/print-design/assets/${itemId}`, { method: 'PATCH', body: JSON.stringify(input) })
}

export function archivePrintAsset(itemId: string) {
  return authenticatedFetch<void>(`/print-design/assets/${itemId}`, { method: 'DELETE' })
}

export function listProductPrintMappings(sku = '') {
  const query = sku ? `?sku=${encodeURIComponent(sku)}` : ''
  return authenticatedFetch<Array<{ id: string; sku: string; asset_group_id: string }>>(`/print-design/product-mappings${query}`)
}

export function findProductPrintMappings(code: string) {
  return authenticatedFetch<Array<{ id: string; sku: string; asset_group_id: string }>>(`/print-design/product-mappings?code=${encodeURIComponent(code)}`)
}

export function createProductPrintMapping(input: { sku: string; asset_group_id: string; product_code?: string; style_code?: string; template_code?: string }) {
  return authenticatedFetch<{ id: string; sku: string; asset_group_id: string }>('/print-design/product-mappings', {
    method: 'POST', body: JSON.stringify(input),
  })
}

export function deleteProductPrintMapping(mappingId: string) {
  return authenticatedFetch<void>(`/print-design/product-mappings/${mappingId}`, { method: 'DELETE' })
}
