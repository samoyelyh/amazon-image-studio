import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useAuth } from '../app/AuthContext'
import AuthenticatedImage from '../components/AuthenticatedImage'
import { SearchIcon } from '../components/agent-control/AgentControlIcons'
import AssetPreviewDialog from '../components/AssetPreviewDialog'
import { listAssets, removeAsset, type Asset, type GeneratedAssetCategory } from '../lib/contentApi'
import { downloadAuthenticatedFile } from '../lib/serverDownloads'

const moduleFilters: Array<{ value: GeneratedAssetCategory | ''; label: string; emptyLabel: string }> = [
  { value: '', label: '全部素材', emptyLabel: '还没有生成素材' },
  { value: 'listing_output', label: 'Listing 图', emptyLabel: '还没有 Listing 图生成素材' },
  { value: 'batch_tryon_output', label: '批量套图', emptyLabel: '还没有批量套图生成素材' },
  { value: 'aplus_output', label: 'A+ 图', emptyLabel: '还没有 A+ 图生成素材' },
  { value: 'material_extract_output', label: '素材提取', emptyLabel: '还没有提取后的透明素材' },
  { value: 'print_design_output', label: '印花编辑', emptyLabel: '还没有印花编辑输出' },
]
const moduleLabels: Record<GeneratedAssetCategory, string> = { listing_output: 'Listing 图', batch_tryon_output: '批量套图', aplus_output: 'A+ 图', material_extract_output: '素材提取', print_design_output: '印花编辑' }

export default function AssetsPage() {
  const auth = useAuth()
  const queryClient = useQueryClient()
  const [category, setCategory] = useState<GeneratedAssetCategory | ''>('')
  const [search, setSearch] = useState('')
  const [message, setMessage] = useState('')
  const [compact, setCompact] = useState(false)
  const [preview, setPreview] = useState<Asset | null>(null)
  const assets = useQuery({ queryKey: ['assets', category, search], queryFn: () => listAssets(category || undefined, search || undefined) })
  const remove = useMutation({
    mutationFn: removeAsset,
    onSuccess: () => { setMessage('生成素材已删除'); setPreview(null); void queryClient.invalidateQueries({ queryKey: ['assets'] }) },
    onError: (error) => setMessage(error instanceof Error ? error.message : '删除失败'),
  })
  const activeFilter = moduleFilters.find((item) => item.value === category) ?? moduleFilters[0]

  return <div className="studio-page mx-auto max-w-[1500px]">
    <header className="flex flex-wrap items-end justify-between gap-4"><div><p className="text-xs font-medium tracking-[0.14em] text-gray-500">MY ASSETS</p><h1 className="mt-2 text-2xl font-semibold tracking-[-0.03em] text-gray-950">我的素材</h1><p className="mt-2 text-sm text-gray-500">集中查看、预览和管理 AI 生成结果。</p>{message && <p className="mt-2 text-sm text-gray-600">{message}</p>}</div><div className="inline-flex rounded-full border border-black/[0.08] bg-white p-1"><button onClick={() => setCompact(false)} className={`rounded-full px-3 py-1.5 text-xs ${!compact ? 'bg-stone-900 text-white' : 'text-gray-500'}`}>舒适</button><button onClick={() => setCompact(true)} className={`rounded-full px-3 py-1.5 text-xs ${compact ? 'bg-stone-900 text-white' : 'text-gray-500'}`}>紧凑</button></div></header>
    <section className="mt-7 rounded-[20px] border border-black/[0.07] bg-white p-3 shadow-sm">
      <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between"><div className="flex flex-wrap gap-1.5" role="tablist" aria-label="素材所属功能模块">{moduleFilters.map((item) => <button key={item.value || 'all'} type="button" role="tab" aria-selected={category === item.value} onClick={() => setCategory(item.value)} className={`rounded-full px-3.5 py-2 text-xs font-medium transition ${category === item.value ? 'bg-stone-900 text-white' : 'text-gray-500 hover:bg-stone-100 hover:text-gray-900'}`}>{item.label}</button>)}</div><label className="flex h-10 items-center gap-2 rounded-full border border-black/[0.08] bg-stone-50 px-3.5 xl:w-72"><SearchIcon className="h-4 w-4 text-gray-500" /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索素材" className="min-w-0 flex-1 bg-transparent text-xs text-gray-800 outline-none placeholder:text-gray-400" /></label></div>
    </section>
    {assets.isLoading && <div className="py-20 text-center text-sm text-gray-500">正在加载生成素材…</div>}
    {assets.isError && <div className="mt-5 rounded-2xl bg-red-50 p-4 text-sm text-red-700">{assets.error.message}</div>}
    {!assets.isLoading && !assets.data?.items.length && <div className="mt-5 rounded-[20px] border border-dashed border-black/10 py-20 text-center text-sm text-gray-500">{activeFilter.emptyLabel}</div>}
    <div className={`mt-5 grid grid-cols-2 gap-3 sm:gap-4 ${compact ? 'md:grid-cols-4 2xl:grid-cols-5' : 'lg:grid-cols-3 2xl:grid-cols-4'}`}>
      {assets.data?.items.map((asset) => <article key={asset.id} className="lovart-image-card group">
        <button onClick={() => setPreview(asset)} aria-label={`预览 ${asset.filename}`} className="relative block aspect-square w-full overflow-hidden bg-[#f0f0ed]">{asset.url && <AuthenticatedImage src={asset.url} alt={asset.filename} className="h-full w-full object-contain" />}<span className="absolute bottom-3 left-3 rounded-full bg-black/50 px-2.5 py-1 text-[10px] text-white opacity-100 backdrop-blur sm:opacity-0 sm:group-hover:opacity-100">查看大图</span></button>
        <div className="p-3.5"><div className="flex items-center justify-between gap-2"><span className="rounded-full bg-stone-100 px-2 py-1 text-[10px] text-gray-500">{moduleLabels[asset.category as GeneratedAssetCategory]}</span><span className="text-[10px] text-gray-400">{asset.width}×{asset.height}</span></div><div className="mt-2.5 truncate text-xs font-medium text-gray-800" title={asset.filename}>{asset.filename}</div><div className="mt-1 flex items-center justify-between text-[11px] text-gray-500"><span>{(asset.size / 1024 / 1024).toFixed(2)} MB</span>{auth.hasPermission('assets.delete') && <button type="button" onClick={() => { if (window.confirm('确认删除此生成素材？')) remove.mutate(asset.id) }} disabled={remove.isPending} className="text-red-600 disabled:opacity-50">删除</button>}</div></div>
      </article>)}
    </div>
    {preview&&<AssetPreviewDialog asset={preview} categoryLabel={moduleLabels[preview.category as GeneratedAssetCategory]} canDelete={auth.hasPermission('assets.delete')} onClose={()=>setPreview(null)}
      onDownload={()=>void downloadAuthenticatedFile(preview.url!,preview.filename).catch(error=>setMessage(error.message))}
      onDelete={()=>{if(window.confirm('确认删除此生成素材？'))remove.mutate(preview.id)}}/>}
  </div>
}
