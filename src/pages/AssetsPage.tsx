import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState, type FormEvent } from 'react'
import { useAuth } from '../app/AuthContext'
import { listAssets, removeAsset, uploadAsset, type AssetCategory } from '../lib/contentApi'

const categories: Array<[AssetCategory, string]> = [
  ['product_reference', '产品参考图'], ['model_template', '模特模板'], ['garment', '服装素材'],
  ['style_reference', '风格参考'], ['listing_output', 'Listing 输出'],
  ['batch_tryon_output', '批量套图输出'], ['aplus_output', 'A+ 输出'], ['temporary', '临时素材'],
]

export default function AssetsPage() {
  const auth = useAuth()
  const queryClient = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)
  const [category, setCategory] = useState<AssetCategory | ''>('')
  const [uploadCategory, setUploadCategory] = useState<AssetCategory>('product_reference')
  const [search, setSearch] = useState('')
  const [message, setMessage] = useState('')
  const assets = useQuery({ queryKey: ['assets', category, search], queryFn: () => listAssets(category || undefined, search || undefined) })
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['assets'] })
  const upload = useMutation({
    mutationFn: ({ file }: { file: File }) => uploadAsset(file, uploadCategory),
    onSuccess: () => { setMessage('素材上传成功'); if (fileRef.current) fileRef.current.value = ''; invalidate() },
    onError: (error) => setMessage(error instanceof Error ? error.message : '上传失败'),
  })
  const remove = useMutation({
    mutationFn: removeAsset,
    onSuccess: () => { setMessage('素材已删除'); invalidate() },
    onError: (error) => setMessage(error instanceof Error ? error.message : '删除失败'),
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    const file = fileRef.current?.files?.[0]
    if (!file) return setMessage('请先选择图片')
    setMessage('')
    upload.mutate({ file })
  }

  return (
    <div className="mt-6 space-y-5">
      <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm dark:border-white/[0.08] dark:bg-gray-900">
        <h1 className="text-xl font-bold text-gray-950 dark:text-white">素材中心</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">图片存入团队私有对象存储，页面只使用短时签名链接访问。</p>
        {auth.hasPermission('assets.upload') && <form onSubmit={submit} className="mt-5 grid gap-3 sm:grid-cols-[minmax(0,1fr)_180px_auto]">
          <input ref={fileRef} type="file" accept="image/jpeg,image/png,image/webp" className="rounded-xl border border-gray-200 bg-gray-50 px-3 py-2 text-sm dark:border-white/[0.1] dark:bg-gray-950 dark:text-gray-200" />
          <select value={uploadCategory} onChange={(event) => setUploadCategory(event.target.value as AssetCategory)} className="rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm dark:border-white/[0.1] dark:bg-gray-950 dark:text-white">{categories.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
          <button disabled={upload.isPending} className="rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60">{upload.isPending ? '上传中…' : '上传素材'}</button>
        </form>}
        {message && <div className="mt-3 text-sm text-gray-600 dark:text-gray-300">{message}</div>}
      </section>
      <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm dark:border-white/[0.08] dark:bg-gray-900">
        <div className="flex flex-col gap-3 sm:flex-row">
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索文件名或哈希" className="min-w-0 flex-1 rounded-xl border border-gray-200 px-3 py-2 text-sm dark:border-white/[0.1] dark:bg-gray-950 dark:text-white" />
          <select value={category} onChange={(event) => setCategory(event.target.value as AssetCategory | '')} className="rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm dark:border-white/[0.1] dark:bg-gray-950 dark:text-white"><option value="">全部分类</option>{categories.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
        </div>
        {assets.isLoading && <div className="py-10 text-center text-sm text-gray-500">正在加载素材…</div>}
        {assets.isError && <div className="py-10 text-center text-sm text-red-500">{assets.error.message}</div>}
        {!assets.isLoading && !assets.data?.items.length && <div className="mt-4 rounded-xl border border-dashed border-gray-200 py-12 text-center text-sm text-gray-500 dark:border-white/[0.08]">当前筛选下没有素材</div>}
        <div className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {assets.data?.items.map((asset) => <article key={asset.id} className="overflow-hidden rounded-2xl border border-gray-200 dark:border-white/[0.08]">
            <div className="aspect-square bg-gray-100 dark:bg-gray-950">{asset.url && <img src={asset.url} alt={asset.filename} className="h-full w-full object-contain" />}</div>
            <div className="p-3"><div className="truncate text-sm font-semibold text-gray-900 dark:text-white" title={asset.filename}>{asset.filename}</div><div className="mt-1 text-xs text-gray-500">{asset.width}×{asset.height} · {(asset.size / 1024 / 1024).toFixed(2)} MB</div>
              {auth.hasPermission('assets.delete') && <button onClick={() => { if (window.confirm('确认删除此素材？项目正在引用的素材不会被删除。')) remove.mutate(asset.id) }} disabled={remove.isPending} className="mt-3 text-xs font-semibold text-red-600 disabled:opacity-50">删除</button>}
            </div>
          </article>)}
        </div>
      </section>
    </div>
  )
}
