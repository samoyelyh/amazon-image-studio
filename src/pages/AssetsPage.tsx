import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useAuth } from '../app/AuthContext'
import AuthenticatedImage from '../components/AuthenticatedImage'
import { listAssets, removeAsset, type GeneratedAssetCategory } from '../lib/contentApi'

const moduleFilters: Array<{ value: GeneratedAssetCategory | ''; label: string; emptyLabel: string }> = [
  { value: '', label: '全部生成素材', emptyLabel: '还没有生成素材' },
  { value: 'listing_output', label: 'Listing 图', emptyLabel: '还没有 Listing 图生成素材' },
  { value: 'batch_tryon_output', label: '批量套图', emptyLabel: '还没有批量套图生成素材' },
  { value: 'aplus_output', label: 'A+ 图', emptyLabel: '还没有 A+ 图生成素材' },
]

const moduleLabels: Record<GeneratedAssetCategory, string> = {
  listing_output: 'Listing 图',
  batch_tryon_output: '批量套图',
  aplus_output: 'A+ 图',
}

export default function AssetsPage() {
  const auth = useAuth()
  const queryClient = useQueryClient()
  const [category, setCategory] = useState<GeneratedAssetCategory | ''>('')
  const [search, setSearch] = useState('')
  const [message, setMessage] = useState('')
  const assets = useQuery({
    queryKey: ['assets', category, search],
    queryFn: () => listAssets(category || undefined, search || undefined),
  })
  const remove = useMutation({
    mutationFn: removeAsset,
    onSuccess: () => {
      setMessage('生成素材已删除')
      void queryClient.invalidateQueries({ queryKey: ['assets'] })
    },
    onError: (error) => setMessage(error instanceof Error ? error.message : '删除失败'),
  })
  const activeFilter = moduleFilters.find((item) => item.value === category) ?? moduleFilters[0]

  return (
    <div className="mt-6 space-y-5">
      <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm dark:border-white/[0.08] dark:bg-gray-900">
        <h1 className="text-xl font-bold text-gray-950 dark:text-white">素材中心</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          这里只保存并展示 AI 生成结果。上传的模板图、参考图和服装图仅供任务使用，不会进入素材中心。
        </p>
        {message && <div className="mt-3 text-sm text-gray-600 dark:text-gray-300">{message}</div>}
      </section>

      <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm dark:border-white/[0.08] dark:bg-gray-900">
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap gap-2" role="tablist" aria-label="素材所属功能模块">
            {moduleFilters.map((item) => (
              <button
                key={item.value || 'all'}
                type="button"
                role="tab"
                aria-selected={category === item.value}
                onClick={() => setCategory(item.value)}
                className={`rounded-xl px-4 py-2 text-sm font-semibold transition-colors ${
                  category === item.value
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-100 text-gray-700 hover:bg-gray-200 dark:bg-white/[0.06] dark:text-gray-300 dark:hover:bg-white/[0.1]'
                }`}
              >
                {item.label}
              </button>
            ))}
          </div>
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="搜索生成素材文件名或哈希"
            className="min-w-0 rounded-xl border border-gray-200 px-3 py-2 text-sm dark:border-white/[0.1] dark:bg-gray-950 dark:text-white"
          />
        </div>

        {assets.isLoading && <div className="py-10 text-center text-sm text-gray-500">正在加载生成素材…</div>}
        {assets.isError && <div className="py-10 text-center text-sm text-red-500">{assets.error.message}</div>}
        {!assets.isLoading && !assets.data?.items.length && (
          <div className="mt-4 rounded-xl border border-dashed border-gray-200 py-12 text-center text-sm text-gray-500 dark:border-white/[0.08]">
            {activeFilter.emptyLabel}
          </div>
        )}
        <div className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {assets.data?.items.map((asset) => (
            <article key={asset.id} className="overflow-hidden rounded-2xl border border-gray-200 dark:border-white/[0.08]">
              <div className="aspect-square bg-gray-100 dark:bg-gray-950">
                {asset.url && <AuthenticatedImage src={asset.url} alt={asset.filename} className="h-full w-full object-contain" />}
              </div>
              <div className="p-3">
                <div className="mb-2 inline-flex rounded-full bg-blue-50 px-2 py-1 text-[11px] font-semibold text-blue-700 dark:bg-blue-500/10 dark:text-blue-300">
                  {moduleLabels[asset.category as GeneratedAssetCategory]}
                </div>
                <div className="truncate text-sm font-semibold text-gray-900 dark:text-white" title={asset.filename}>{asset.filename}</div>
                <div className="mt-1 text-xs text-gray-500">{asset.width}×{asset.height} · {(asset.size / 1024 / 1024).toFixed(2)} MB</div>
                {auth.hasPermission('assets.delete') && (
                  <button
                    type="button"
                    onClick={() => {
                      if (window.confirm('确认删除此生成素材？')) remove.mutate(asset.id)
                    }}
                    disabled={remove.isPending}
                    className="mt-3 text-xs font-semibold text-red-600 disabled:opacity-50"
                  >
                    删除
                  </button>
                )}
              </div>
            </article>
          ))}
        </div>
      </section>
    </div>
  )
}
