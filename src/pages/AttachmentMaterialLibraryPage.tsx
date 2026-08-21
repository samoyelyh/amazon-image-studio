import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import AuthenticatedImage from '../components/category-listing/AuthenticatedImage'
import {
  archiveAttachmentMaterialSet,
  downloadAttachmentMaterialVersion,
  getAttachmentMaterialSet,
  listAttachmentMaterialSets,
  updateAttachmentMaterialSet,
  type AttachmentMaterialSetDetail,
  type AttachmentMaterialSetSummary,
} from '../lib/attachmentMaterialApi'
import {
  attachmentMaterialCompletionLabel,
  attachmentMaterialModuleLabels,
  attachmentMaterialModuleOrder,
  attachmentMaterialVersionLabel,
  materialVersionByNumber,
} from '../lib/attachmentMaterialLibrary'
import { addAttachmentMaterialToReferenceLibrary } from '../lib/attachmentReferenceLibraryApi'
import { useAuth } from '../app/AuthContext'

const input = 'rounded-xl border border-gray-200 bg-white px-3.5 py-2.5 text-sm outline-none focus:border-blue-500 dark:border-white/[0.1] dark:bg-gray-950'
const secondary = 'rounded-lg border border-gray-200 bg-white px-3.5 py-2 text-sm font-semibold text-gray-700 disabled:opacity-50 dark:border-white/[0.1] dark:bg-gray-900 dark:text-gray-200'

function formatDate(value: string) {
  return new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })
}

function MaterialCard({ item }: { item: AttachmentMaterialSetSummary }) {
  return <Link to={`/materials/${item.id}`} className="group overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm transition hover:-translate-y-0.5 hover:border-blue-200 hover:shadow-lg dark:border-white/[0.08] dark:bg-gray-900">
    <div className="relative aspect-[4/3] overflow-hidden bg-gray-100 dark:bg-white/[0.03]">
      {item.cover_asset?.url ? <AuthenticatedImage allowZoom={false} url={item.cover_asset.url} alt={item.display_name} className="h-full w-full object-contain transition duration-300 group-hover:scale-[1.02]" placeholderClassName="h-full w-full" /> : <div className="flex h-full items-center justify-center text-sm text-gray-400">暂无封面</div>}
      <div className="absolute left-3 top-3 flex gap-2"><span className="rounded-full bg-gray-950/75 px-2.5 py-1 text-[11px] font-semibold text-white">V{item.current_version_number}</span><span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${item.is_complete ? 'bg-emerald-600 text-white' : 'bg-amber-100 text-amber-800'}`}>{item.is_complete ? '完整套图' : '未完整'}</span></div>
    </div>
    <div className="p-4"><h3 className="truncate text-base font-semibold text-gray-950 dark:text-white">{item.display_name}</h3><p className="mt-1 truncate text-sm text-gray-500">{item.product_name} · {item.category_name}</p><div className="mt-3 flex items-center justify-between text-xs text-gray-500"><span>{attachmentMaterialCompletionLabel(item.module_count, item.target_module_count, item.is_complete)}</span><span>{formatDate(item.updated_at)}</span></div>{item.tags.length > 0 && <div className="mt-3 flex flex-wrap gap-1.5">{item.tags.slice(0, 4).map((tag) => <span key={tag} className="rounded-full bg-gray-100 px-2 py-1 text-[11px] text-gray-600 dark:bg-white/[0.05] dark:text-gray-300">{tag}</span>)}</div>}</div>
  </Link>
}

function MaterialList() {
  const [items, setItems] = useState<AttachmentMaterialSetSummary[]>([])
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('')
  const [completion, setCompletion] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const page = await listAttachmentMaterialSets({
        search: search.trim() || undefined,
        category_key: category || undefined,
        completion: completion as 'complete' | 'incomplete' || undefined,
      })
      setItems(page.items)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '素材库加载失败')
    } finally { setLoading(false) }
  }, [category, completion, search])

  useEffect(() => { const timer = window.setTimeout(() => void load(), 180); return () => window.clearTimeout(timer) }, [load])
  const categories = useMemo(() => [...new Map(items.map((item) => [item.category_key, item.category_name])).entries()], [items])

  return <div className="mx-auto max-w-[1500px] space-y-6 p-5 sm:p-6">
    <header className="rounded-3xl border border-gray-200 bg-gradient-to-br from-white to-blue-50/70 p-6 shadow-sm dark:border-white/[0.08] dark:from-gray-900 dark:to-blue-950/20">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-blue-600">Personal Material Library</p><h1 className="mt-2 text-2xl font-semibold text-gray-950 dark:text-white">个人素材库</h1><p className="mt-2 max-w-2xl text-sm leading-6 text-gray-500">保存附图工作台的最终采用图，按套装和版本持续管理。历史版本不会被覆盖，清空工作台也不会影响已保存素材。</p>
    </header>
    <section className="flex flex-col gap-3 rounded-2xl border border-gray-200 bg-white p-4 shadow-sm dark:border-white/[0.08] dark:bg-gray-900 md:flex-row">
      <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索套装、商品或品类" className={`${input} min-w-0 flex-1`} />
      <select value={category} onChange={(event) => setCategory(event.target.value)} className={`${input} md:w-52`}><option value="">全部品类</option>{categories.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select>
      <select value={completion} onChange={(event) => setCompletion(event.target.value)} className={`${input} md:w-44`}><option value="">全部完整度</option><option value="complete">完整套图</option><option value="incomplete">未完整</option></select>
    </section>
    {error && <div className="rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}
    {loading ? <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">{Array.from({ length: 4 }, (_, index) => <div key={index} className="aspect-[4/3] animate-pulse rounded-2xl bg-gray-100 dark:bg-white/[0.04]" />)}</div> : items.length ? <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">{items.map((item) => <MaterialCard key={item.id} item={item} />)}</div> : <div className="flex min-h-72 flex-col items-center justify-center rounded-3xl border border-dashed border-gray-300 bg-white text-center dark:border-white/[0.1] dark:bg-gray-900"><div className="text-lg font-semibold text-gray-800 dark:text-white">个人素材库还是空的</div><p className="mt-2 max-w-md text-sm text-gray-500">在附图生成工作台将结果设为 Final 后，使用“保存整套”或单张结果里的“保存到素材库”。</p><Link to="/workspaces/attachment-images" className="mt-5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white">前往附图生成工作台</Link></div>}
  </div>
}

function MaterialDetail({ materialSetId }: { materialSetId: string }) {
  const auth = useAuth()
  const navigate = useNavigate()
  const [detail, setDetail] = useState<AttachmentMaterialSetDetail | null>(null)
  const [versionNumber, setVersionNumber] = useState<number | null>(null)
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState('')
  const [tags, setTags] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      const value = await getAttachmentMaterialSet(materialSetId)
      setDetail(value); setVersionNumber((current) => current ?? value.current_version_number)
      setName(value.display_name); setTags(value.tags.join('，')); setNote(value.note)
    } catch (reason) { setError(reason instanceof Error ? reason.message : '素材套装加载失败') }
  }, [materialSetId])
  useEffect(() => { void load() }, [load])
  const version = detail ? materialVersionByNumber(detail.versions, versionNumber) : null
  const itemMap = useMemo(() => new Map((version?.items || []).map((item) => [item.module_key, item])), [version])
  if (!detail) return <div className="p-6 text-sm text-gray-500">{error || '正在加载素材套装…'}</div>

  const continueUrl = detail.source_session_id ? `/attachment-image-workbench/${detail.source_session_id}` : '/workspaces/attachment-images'
  return <div className="mx-auto max-w-[1500px] space-y-5 p-5 sm:p-6">
    <div className="flex flex-wrap items-start justify-between gap-4"><div><button className="mb-3 text-sm font-semibold text-gray-500 hover:text-gray-900" onClick={() => navigate('/materials')}>← 返回个人素材库</button><h1 className="text-2xl font-semibold text-gray-950 dark:text-white">{detail.display_name}</h1><p className="mt-2 text-sm text-gray-500">{detail.product_name} · {detail.category_name} · {attachmentMaterialCompletionLabel(detail.module_count, detail.target_module_count, detail.is_complete)}</p></div><div className="flex flex-wrap gap-2"><Link to={continueUrl} className={secondary}>继续制作</Link><button className={secondary} onClick={() => setEditing((value) => !value)}>编辑信息</button><button className={secondary} disabled={busy} onClick={() => version && void downloadAttachmentMaterialVersion(detail.id, version.version_number, detail.display_name)}>下载当前版本 ZIP</button><button className="rounded-lg border border-red-200 bg-white px-3.5 py-2 text-sm font-semibold text-red-600 disabled:opacity-50" disabled={busy} onClick={() => { if (!window.confirm('归档后会从个人素材库默认列表隐藏，但不会删除图片和版本。确认归档吗？')) return; setBusy(true); void archiveAttachmentMaterialSet(detail.id).then(() => navigate('/materials')).finally(() => setBusy(false)) }}>归档</button></div></div>
    {editing && <form className="grid gap-3 rounded-2xl border border-gray-200 bg-white p-4 shadow-sm dark:border-white/[0.08] dark:bg-gray-900 md:grid-cols-[1fr_1fr_auto]" onSubmit={(event) => { event.preventDefault(); setBusy(true); void updateAttachmentMaterialSet(detail.id, { display_name: name.trim(), tags: tags.split(/[,，]/).map((value) => value.trim()).filter(Boolean), note: note.trim() }).then((value) => { setDetail(value); setEditing(false) }).finally(() => setBusy(false)) }}><input className={input} value={name} onChange={(event) => setName(event.target.value)} /><input className={input} value={tags} onChange={(event) => setTags(event.target.value)} placeholder="标签，逗号分隔" /><button className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white" disabled={busy || !name.trim()}>保存信息</button><textarea className={`${input} md:col-span-3`} rows={2} value={note} onChange={(event) => setNote(event.target.value)} placeholder="备注" /></form>}
    <section className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm dark:border-white/[0.08] dark:bg-gray-900"><div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-base font-semibold text-gray-950 dark:text-white">版本记录</h2><p className="mt-1 text-xs text-gray-500">每个版本都是不可变快照，可随时切换查看和下载。</p></div><select className={input} value={version?.version_number || ''} onChange={(event) => setVersionNumber(Number(event.target.value))}>{detail.versions.map((item) => <option key={item.id} value={item.version_number}>{attachmentMaterialVersionLabel(item)} · {formatDate(item.created_at)}</option>)}</select></div>{version && <div className="mt-4 flex flex-wrap gap-2 text-xs"><span className={`rounded-full px-2.5 py-1 font-semibold ${version.is_complete ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>{attachmentMaterialCompletionLabel(version.module_count, version.target_module_count, version.is_complete)}</span><span className="rounded-full bg-gray-100 px-2.5 py-1 text-gray-600">生成模式与来源已保存</span>{version.changed_module_keys.map((key) => <span key={key} className="rounded-full bg-blue-50 px-2.5 py-1 text-blue-700">本版变更：{attachmentMaterialModuleLabels[key] || key}</span>)}</div>}</section>
    <section className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">{attachmentMaterialModuleOrder.map((moduleKey) => {
      const item = itemMap.get(moduleKey)
      return <article key={moduleKey} className="overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm dark:border-white/[0.08] dark:bg-gray-900"><div className="flex items-center justify-between border-b border-gray-100 px-4 py-3 dark:border-white/[0.06]"><h3 className="text-sm font-semibold text-gray-900 dark:text-white">{attachmentMaterialModuleLabels[moduleKey]}</h3><span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${item ? 'bg-emerald-50 text-emerald-700' : 'bg-gray-100 text-gray-500'}`}>{item ? '已保存' : '本版缺失'}</span></div>{item?.asset.url ? <AuthenticatedImage url={item.asset.url} alt={attachmentMaterialModuleLabels[moduleKey]} className="aspect-[4/3] w-full bg-gray-50 object-contain" placeholderClassName="aspect-[4/3]" /> : <div className="flex aspect-[4/3] items-center justify-center bg-gray-50 text-sm text-gray-400 dark:bg-white/[0.02]">该版本未保存此模块</div>}{item && <div className="grid grid-cols-2 gap-2 p-4 text-xs text-gray-500"><span>{item.output_size}</span><span className="text-right">{item.aspect_ratio}</span><span>{item.generation_mode}</span><span className="text-right">{item.product_mode}</span>{auth.hasPermission('platform.admin') && <button className={`${secondary} col-span-2 mt-1`} disabled={busy} onClick={() => { setBusy(true); void addAttachmentMaterialToReferenceLibrary(item.id, { name: `${attachmentMaterialModuleLabels[moduleKey]} 优秀素材`, module_key: moduleKey, reference_role: 'TEMPLATE', guidance: '参考画面构图、布局、镜头、光线与留白；禁止继承参考图中的商品身份、颜色、Logo、文字和号码。', tags: [attachmentMaterialModuleLabels[moduleKey], '个人素材'] }).then(() => window.alert('已加入参考图库，并已开始后台分析。')).catch((reason) => window.alert(reason instanceof Error ? reason.message : '加入参考图库失败')).finally(() => setBusy(false)) }}>加入参考图库</button>}</div>}</article>
    })}</section>
  </div>
}

export default function AttachmentMaterialLibraryPage() {
  const { materialSetId } = useParams()
  return materialSetId ? <MaterialDetail materialSetId={materialSetId} /> : <MaterialList />
}
