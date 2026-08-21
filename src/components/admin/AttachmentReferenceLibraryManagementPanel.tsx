import { useEffect, useMemo, useRef, useState } from 'react'
import AuthenticatedImage from '../category-listing/AuthenticatedImage'
import { uploadAsset } from '../../lib/contentApi'
import { attachmentModuleDefinitions } from '../../lib/attachmentImageWorkbench'
import {
  createAttachmentReferenceLibraryItem,
  listAdminAttachmentReferenceLibrary,
  reanalyzeAttachmentReferenceLibraryItem,
  updateAttachmentReferenceLibraryItem,
  type AttachmentReferenceLibraryItem,
} from '../../lib/attachmentReferenceLibraryApi'

const panel = 'rounded-2xl border border-gray-200 bg-white p-5 shadow-sm dark:border-white/[0.08] dark:bg-gray-900'
const input = 'w-full rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm outline-none focus:border-blue-500 dark:border-white/[0.1] dark:bg-gray-950 dark:text-white'
const button = 'rounded-xl border border-gray-200 bg-white px-3 py-2 text-xs font-semibold text-gray-700 disabled:opacity-50 dark:border-white/[0.1] dark:bg-gray-950 dark:text-gray-200'

const roles = ['TEMPLATE', 'SCENE', 'PRINT', 'OTHER'] as const
type Role = typeof roles[number]

export default function AttachmentReferenceLibraryManagementPanel({ notify }: { notify: (message: string) => void }) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [items, setItems] = useState<AttachmentReferenceLibraryItem[]>([])
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [moduleFilter, setModuleFilter] = useState('')
  const [form, setForm] = useState({ name: '', description: '', category_key: 'football_jersey', module_key: 'gift_scene', reference_role: 'TEMPLATE' as Role, guidance: '', tags: '', is_featured: false, sort_order: 100 })
  const load = async () => {
    setError('')
    try { setItems(await listAdminAttachmentReferenceLibrary(moduleFilter || undefined)) }
    catch (reason) { setError(reason instanceof Error ? reason.message : '参考图库读取失败') }
  }
  useEffect(() => { void load() }, [moduleFilter])
  const activeCount = useMemo(() => items.filter((item) => item.is_active).length, [items])

  const upload = async (file: File) => {
    setBusy('create')
    try {
      const category = form.reference_role === 'PRINT' ? 'print_asset' : form.reference_role === 'TEMPLATE' ? 'model_template' : 'style_reference'
      const asset = await uploadAsset(file, category)
      await createAttachmentReferenceLibraryItem({
        name: form.name.trim() || file.name.replace(/\.[^.]+$/, ''), description: form.description.trim(),
        category_key: form.category_key.trim() || null, module_key: form.module_key,
        reference_role: form.reference_role, asset_id: asset.id, guidance: form.guidance.trim(),
        tags: form.tags.split(/[，,]/).map((item) => item.trim()).filter(Boolean),
        is_featured: form.is_featured, sort_order: form.sort_order,
      })
      setForm((value) => ({ ...value, name: '', description: '', guidance: '', tags: '', is_featured: false }))
      notify('参考图已加入公司图库，并已自动提交固有构图分析。')
      await load()
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : '参考图上传失败')
    } finally {
      setBusy('')
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const update = async (item: AttachmentReferenceLibraryItem, values: Parameters<typeof updateAttachmentReferenceLibraryItem>[1]) => {
    setBusy(item.id)
    try { await updateAttachmentReferenceLibraryItem(item.id, values); notify('参考图库配置已更新。'); await load() }
    catch (reason) { notify(reason instanceof Error ? reason.message : '更新失败') }
    finally { setBusy('') }
  }

  return <div className="space-y-5">
    <section className={panel}>
      <div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="font-semibold text-gray-950 dark:text-white">参考图库</h2><p className="mt-1 text-xs text-gray-500">按附图模块沉淀成熟构图。图库只建立 Asset 关系，不复制 MinIO 文件；运营选择后自动复用已分析理解。</p></div><span className="rounded-full bg-violet-50 px-3 py-1 text-xs font-semibold text-violet-700">启用 {activeCount} / {items.length}</span></div>
      <input ref={fileRef} hidden type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => { const file = event.target.files?.[0]; if (file) void upload(file) }} />
      <div className="mt-5 grid gap-3 lg:grid-cols-3">
        <input className={input} placeholder="参考图名称" value={form.name} onChange={(event) => setForm((value) => ({ ...value, name: event.target.value }))} />
        <select className={input} value={form.module_key} onChange={(event) => setForm((value) => ({ ...value, module_key: event.target.value }))}>{attachmentModuleDefinitions.map((item) => <option key={item.code} value={item.code}>{item.name}</option>)}</select>
        <select className={input} value={form.reference_role} onChange={(event) => setForm((value) => ({ ...value, reference_role: event.target.value as Role }))}>{roles.map((role) => <option key={role} value={role}>{role}</option>)}</select>
        <input className={input} placeholder="品类编码；留空表示通用" value={form.category_key} onChange={(event) => setForm((value) => ({ ...value, category_key: event.target.value }))} />
        <input className={input} placeholder="标签，逗号分隔" value={form.tags} onChange={(event) => setForm((value) => ({ ...value, tags: event.target.value }))} />
        <input className={input} type="number" min={0} max={10000} aria-label="排序" value={form.sort_order} onChange={(event) => setForm((value) => ({ ...value, sort_order: Number(event.target.value) }))} />
      </div>
      <textarea className={`${input} mt-3 min-h-20`} placeholder="Guidance：主要参考什么、明确禁止继承什么" value={form.guidance} onChange={(event) => setForm((value) => ({ ...value, guidance: event.target.value }))} />
      <textarea className={`${input} mt-3 min-h-16`} placeholder="说明（运营可见）" value={form.description} onChange={(event) => setForm((value) => ({ ...value, description: event.target.value }))} />
      <div className="mt-3 flex flex-wrap items-center gap-3"><label className="flex items-center gap-2 text-xs text-gray-600"><input type="checkbox" checked={form.is_featured} onChange={(event) => setForm((value) => ({ ...value, is_featured: event.target.checked }))} />推荐参考</label><button className="rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50" disabled={busy !== '' || !form.module_key} onClick={() => fileRef.current?.click()}>{busy === 'create' ? '上传并分析中…' : '上传参考图'}</button></div>
    </section>

    <section className={panel}>
      <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-semibold text-gray-950 dark:text-white">图库项目</h2><p className="mt-1 text-xs text-gray-500">Guidance、Role 或模块变化会生成新的理解版本；停用不会删除历史引用。</p></div><select className="rounded-xl border border-gray-200 px-3 py-2 text-xs dark:border-white/[0.1] dark:bg-gray-950" value={moduleFilter} onChange={(event) => setModuleFilter(event.target.value)}><option value="">全部模块</option>{attachmentModuleDefinitions.map((item) => <option key={item.code} value={item.code}>{item.name}</option>)}</select></div>
      {error && <div className="mt-4 rounded-xl bg-red-50 p-3 text-xs text-red-700">{error}</div>}
      <div className="mt-4 grid gap-3 xl:grid-cols-2">{items.map((item) => <article key={item.id} className="flex gap-4 rounded-2xl border border-gray-200 p-3 dark:border-white/[0.08]">
        <AuthenticatedImage url={item.asset.url} alt={item.name} className="h-28 w-28 shrink-0 rounded-xl bg-gray-50 object-cover" />
        <div className="min-w-0 flex-1"><div className="flex items-start justify-between gap-2"><div><div className="truncate text-sm font-semibold text-gray-900 dark:text-white">{item.name}</div><div className="mt-1 text-[11px] text-gray-500">{item.module_key} · {item.reference_role} · 排序 {item.sort_order}</div></div><span className={`rounded-full px-2 py-1 text-[10px] font-semibold ${item.understanding?.status === 'ready' ? 'bg-emerald-50 text-emerald-700' : item.understanding?.status === 'failed' ? 'bg-red-50 text-red-700' : 'bg-violet-50 text-violet-700'}`}>{item.understanding?.status === 'ready' ? `已理解 V${item.understanding.version_number}` : item.understanding?.status || '等待分析'}</span></div><p className="mt-2 line-clamp-2 text-xs leading-5 text-gray-500">{item.guidance || item.description || '未填写 Guidance'}</p><div className="mt-3 flex flex-wrap gap-2"><button className={button} disabled={busy !== ''} onClick={() => void update(item, { is_active: !item.is_active })}>{item.is_active ? '停用' : '启用'}</button><button className={button} disabled={busy !== ''} onClick={() => void update(item, { is_featured: !item.is_featured })}>{item.is_featured ? '取消推荐' : '设为推荐'}</button><button className={button} disabled={busy !== ''} onClick={() => { setBusy(item.id); void reanalyzeAttachmentReferenceLibraryItem(item.id).then(() => { notify('重新分析已提交。'); return load() }).catch((reason) => notify(reason instanceof Error ? reason.message : '提交失败')).finally(() => setBusy('')) }}>重新分析</button></div></div>
      </article>)}</div>
      {!items.length && !error && <div className="py-12 text-center text-sm text-gray-500">当前筛选下还没有参考图。</div>}
    </section>
  </div>
}
