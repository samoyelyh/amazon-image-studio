import { useMemo, useState } from 'react'
import type { Asset } from '../../lib/contentApi'
import type { ListingWorkflowSessionSummary } from '../../lib/listingWorkflowApi'
import type { AttachmentProductComposition } from '../../lib/attachmentPlanningApi'
import AuthenticatedImage from '../category-listing/AuthenticatedImage'

interface Props {
  composition: AttachmentProductComposition
  supportsMultiProduct: boolean
  candidates: ListingWorkflowSessionSummary[]
  candidateAssets: Record<string, Asset>
  busy?: boolean
  onModeChange: (mode: 'SINGLE' | 'MULTI') => Promise<void>
  onAdd: (sessionId: string) => Promise<void>
  onReplace: (itemId: string, sessionId: string) => Promise<void>
  onRemove: (itemId: string) => Promise<void>
}

function title(item: ListingWorkflowSessionSummary) {
  return item.listing_title_zh || item.listing_title_en || `商品 ${item.id.slice(0, 8)}`
}

export default function AttachmentProductCompositionPanel({
  composition, supportsMultiProduct, candidates, candidateAssets, busy = false,
  onModeChange, onAdd, onReplace, onRemove,
}: Props) {
  const [pickerFor, setPickerFor] = useState<'add' | string | null>(null)
  const [search, setSearch] = useState('')
  const selectedSessionIds = new Set(composition.products.map((item) => item.source_session_id))
  const filtered = useMemo(() => {
    const value = search.trim().toLowerCase()
    return candidates.filter((item) => {
      if (!item.confirmed_at || !item.primary_asset_id || selectedSessionIds.has(item.id)) return false
      if (!value) return true
      return `${title(item)} ${item.category_name}`.toLowerCase().includes(value)
    })
  }, [candidates, composition.current_version_id, search])
  const activeProducts = composition.mode === 'SINGLE'
    ? composition.products.filter((item) => item.product_role === 'PRIMARY')
    : composition.products
  const secondaryCount = composition.products.filter((item) => item.product_role === 'SECONDARY').length

  const choose = async (sessionId: string) => {
    if (pickerFor === 'add') await onAdd(sessionId)
    else if (pickerFor) await onReplace(pickerFor, sessionId)
    setPickerFor(null); setSearch('')
  }

  return <div className="space-y-3 rounded-xl border border-gray-200 p-4 dark:border-white/[0.08]">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><div className="text-xs font-semibold text-gray-600 dark:text-gray-300">商品模式</div><p className="mt-1 text-[11px] leading-5 text-gray-500">选择商品不会自动调用 AI；组合变化后需重新分析并策划。</p></div>
      <div className="inline-flex rounded-lg bg-gray-100 p-1 dark:bg-white/[0.06]">
        {(['SINGLE', 'MULTI'] as const).map((mode) => <button
          key={mode} type="button" disabled={busy || (mode === 'MULTI' && !supportsMultiProduct)}
          onClick={() => composition.mode !== mode && void onModeChange(mode)}
          className={`rounded-md px-3 py-1.5 text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-40 ${composition.mode === mode ? 'bg-white text-blue-700 shadow-sm dark:bg-gray-800' : 'text-gray-500'}`}
        >{mode === 'SINGLE' ? '单件商品' : '多件商品'}</button>)}
      </div>
    </div>
    {!supportsMultiProduct && <div className="rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-500 dark:bg-white/[0.03]">该模块按业务定义仅支持单件商品。</div>}
    {composition.mode === 'MULTI' && <div className="rounded-lg bg-blue-50 px-3 py-2 text-xs leading-5 text-blue-700">当前 {activeProducts.length} 件商品 = {activeProducts.length} 个模特。主商品会被安排在核心视觉区域；人物站位由 AI 自动策划。</div>}
    <div className="grid gap-2 sm:grid-cols-3">{activeProducts.map((item) => {
      const cover = item.assets[0]?.asset
      const primary = item.product_role === 'PRIMARY'
      return <div key={item.id} className={`rounded-xl border p-2.5 ${primary ? 'border-blue-200 bg-blue-50/40' : 'border-gray-200 bg-white dark:border-white/[0.08] dark:bg-gray-950'}`}>
        <div className="aspect-[4/3] overflow-hidden rounded-lg bg-gray-100"><AuthenticatedImage url={cover?.url || null} alt={item.display_name} className="h-full w-full object-contain" placeholderClassName="h-full w-full" allowZoom={false} /></div>
        <div className="mt-2 flex items-start justify-between gap-2"><div className="min-w-0"><div className="text-[10px] font-semibold text-blue-600">{primary ? '主商品' : `附加商品 ${item.display_order}`}</div><div className="mt-0.5 truncate text-xs font-semibold text-gray-900 dark:text-white">{item.display_name}</div><div className="mt-0.5 truncate text-[10px] text-gray-500">{item.category_name || '未标注品类'}</div></div></div>
        {!primary && <div className="mt-2 flex gap-2"><button type="button" className="text-[11px] font-semibold text-blue-600 disabled:opacity-50" disabled={busy} onClick={() => setPickerFor(item.id)}>更换</button><button type="button" className="text-[11px] font-semibold text-red-600 disabled:opacity-50" disabled={busy} onClick={() => void onRemove(item.id)}>移除</button></div>}
      </div>
    })}</div>
    {composition.mode === 'MULTI' && secondaryCount < 2 && <button type="button" className="w-full rounded-xl border border-dashed border-blue-300 px-3 py-3 text-xs font-semibold text-blue-700 disabled:opacity-50" disabled={busy} onClick={() => setPickerFor('add')}>＋ 添加附加商品</button>}
    {composition.mode === 'MULTI' && secondaryCount === 0 && <p className="text-[11px] text-amber-700">多件商品模式至少需要添加 1 件附加商品。</p>}

    {pickerFor && <div className="fixed inset-0 z-[95] flex items-center justify-center bg-black/50 p-4" role="dialog" aria-modal="true" aria-label="选择附加商品">
      <div className="max-h-[82vh] w-full max-w-2xl overflow-hidden rounded-2xl bg-white shadow-2xl dark:bg-gray-900">
        <div className="flex items-start justify-between border-b border-gray-100 p-5 dark:border-white/[0.06]"><div><h3 className="text-base font-semibold text-gray-950 dark:text-white">{pickerFor === 'add' ? '添加附加商品' : '更换附加商品'}</h3><p className="mt-1 text-xs text-gray-500">仅显示当前团队内已确认并有主图的商品，已选商品不会重复出现。</p></div><button type="button" className="text-xl text-gray-400" onClick={() => setPickerFor(null)}>×</button></div>
        <div className="p-5"><input autoFocus className="w-full rounded-xl border border-gray-200 px-3 py-2 text-sm dark:border-white/[0.1] dark:bg-gray-950" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索商品名称或品类" />
          <div className="mt-4 grid max-h-[52vh] gap-3 overflow-auto sm:grid-cols-2">{filtered.map((item) => {
            const asset = item.primary_asset_id ? candidateAssets[item.primary_asset_id] : undefined
            return <button key={item.id} type="button" className="flex gap-3 rounded-xl border border-gray-200 p-3 text-left transition hover:border-blue-300 hover:bg-blue-50/40 dark:border-white/[0.08]" onClick={() => void choose(item.id)}>
              <div className="h-16 w-16 shrink-0 overflow-hidden rounded-lg bg-gray-100"><AuthenticatedImage url={asset?.url || null} alt={title(item)} className="h-full w-full object-contain" placeholderClassName="h-full w-full" allowZoom={false} /></div>
              <div className="min-w-0"><div className="line-clamp-2 text-xs font-semibold text-gray-900 dark:text-white">{title(item)}</div><div className="mt-1 text-[11px] text-gray-500">{item.category_name}</div><div className="mt-1 text-[10px] text-emerald-600">Listing 已确认</div></div>
            </button>
          })}</div>
          {!filtered.length && <div className="py-10 text-center text-sm text-gray-500">没有可选择的其他商品</div>}
        </div>
      </div>
    </div>}
  </div>
}
