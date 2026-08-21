import { useEffect, useMemo, useRef, useState } from 'react'
import AuthenticatedImage from '../category-listing/AuthenticatedImage'
import { uploadAsset } from '../../lib/contentApi'
import { attachmentModuleDefinitions } from '../../lib/attachmentImageWorkbench'
import {
  createAttachmentReferenceLibraryItem,
  getAdminAttachmentReferenceLibraryOptions,
  listAdminAttachmentReferenceLibrary,
  reanalyzeAttachmentReferenceLibraryItem,
  updateAttachmentReferenceLibraryItem,
  type AttachmentReferenceLibraryItem,
  type AttachmentReferenceLibraryCategoryOption,
} from '../../lib/attachmentReferenceLibraryApi'
import { AuthApiError } from '../../lib/authApi'

const panel = 'rounded-2xl border border-gray-200 bg-white p-5 shadow-sm dark:border-white/[0.08] dark:bg-gray-900'
const input = 'w-full rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm outline-none focus:border-blue-500 dark:border-white/[0.1] dark:bg-gray-950 dark:text-white'
const button = 'rounded-xl border border-gray-200 bg-white px-3 py-2 text-xs font-semibold text-gray-700 disabled:opacity-50 dark:border-white/[0.1] dark:bg-gray-950 dark:text-gray-200'

const roles = ['TEMPLATE', 'SCENE', 'PRINT', 'OTHER'] as const
type Role = typeof roles[number]
const emptyForm = { name: '', description: '', category_key: '', module_keys: [] as string[], reference_role: 'TEMPLATE' as Role, guidance: '', tags: '', is_featured: false, is_active: true, sort_order: 100 }

export default function AttachmentReferenceLibraryManagementPanel({ notify }: { notify: (message: string) => void }) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [items, setItems] = useState<AttachmentReferenceLibraryItem[]>([])
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [moduleFilter, setModuleFilter] = useState('')
  const [search, setSearch] = useState('')
  const [roleFilter, setRoleFilter] = useState('')
  const [activeFilter, setActiveFilter] = useState<'all' | 'active' | 'inactive'>('all')
  const [featuredOnly, setFeaturedOnly] = useState(false)
  const [editingId, setEditingId] = useState('')
  const [options, setOptions] = useState<AttachmentReferenceLibraryCategoryOption[]>([])
  const [form, setForm] = useState(emptyForm)
  const load = async () => {
    setError('')
    try { setItems(await listAdminAttachmentReferenceLibrary(moduleFilter || undefined)) }
    catch (reason) { setError(reason instanceof Error ? reason.message : '参考图库读取失败') }
  }
  useEffect(() => { void load() }, [moduleFilter])
  useEffect(() => { void getAdminAttachmentReferenceLibraryOptions().then((rows) => { setOptions(rows); setForm((value) => value.category_key || !rows[0] ? value : ({ ...value, category_key: rows[0].category_key, module_keys: rows[0].modules[0] ? [rows[0].modules[0].code] : [] })) }).catch(() => setOptions([])) }, [])
  const activeCount = useMemo(() => items.filter((item) => item.is_active).length, [items])
  const moduleOptions = useMemo(() => options.find((item) => item.category_key === form.category_key)?.modules || attachmentModuleDefinitions, [form.category_key, options])
  const allModuleOptions = useMemo(() => {
    const merged = new Map<string, { code: string; name: string; sort_order: number }>()
    for (const option of options) for (const module of option.modules) if (!merged.has(module.code)) merged.set(module.code, module)
    return merged.size ? [...merged.values()].sort((a, b) => a.sort_order - b.sort_order) : attachmentModuleDefinitions
  }, [options])
  const visibleItems = useMemo(() => items.filter((item) => {
    const query = search.trim().toLowerCase()
    if (query && ![item.name, item.description, item.guidance, ...item.tags].join(' ').toLowerCase().includes(query)) return false
    if (roleFilter && item.reference_role !== roleFilter) return false
    if (activeFilter === 'active' && !item.is_active) return false
    if (activeFilter === 'inactive' && item.is_active) return false
    return !featuredOnly || item.is_featured
  }), [activeFilter, featuredOnly, items, roleFilter, search])

  const resetForm = () => {
    const first = options[0]
    setEditingId('')
    setForm({ ...emptyForm, category_key: first?.category_key || '', module_keys: first?.modules[0] ? [first.modules[0].code] : [] })
  }

  const beginEdit = (item: AttachmentReferenceLibraryItem) => {
    setEditingId(item.id)
    setForm({
      name: item.name, description: item.description || '', category_key: item.category_key || '',
      module_keys: [...item.module_keys], reference_role: item.reference_role, guidance: item.guidance || '',
      tags: item.tags.join('，'), is_featured: item.is_featured, is_active: item.is_active, sort_order: item.sort_order,
    })
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const upload = async (file: File) => {
    setBusy('create')
    try {
      const category = form.reference_role === 'PRINT' ? 'print_asset' : form.reference_role === 'TEMPLATE' ? 'model_template' : 'style_reference'
      const asset = await uploadAsset(file, category)
      const payload = {
        name: form.name.trim() || file.name.replace(/\.[^.]+$/, ''), description: form.description.trim(),
        category_key: form.category_key.trim() || null, module_keys: form.module_keys,
        reference_role: form.reference_role, asset_id: asset.id, guidance: form.guidance.trim(),
        tags: form.tags.split(/[，,]/).map((item) => item.trim()).filter(Boolean),
        is_featured: form.is_featured, is_active: form.is_active, sort_order: form.sort_order,
      }
      try { await createAttachmentReferenceLibraryItem(payload) }
      catch (reason) {
        if (!(reason instanceof AuthApiError) || reason.code !== 'reference_library.duplicate_confirmation_required' || !window.confirm(`${reason.message}\n\n确认继续为同一图片创建新的用途规则吗？`)) throw reason
        await createAttachmentReferenceLibraryItem({ ...payload, allow_duplicate_asset: true })
      }
      setForm((value) => ({ ...value, name: '', description: '', guidance: '', tags: '', is_featured: false, is_active: true }))
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

  const saveEdit = async () => {
    if (!editingId || !form.module_keys.length || !form.name.trim()) return
    setBusy(editingId)
    try {
      await updateAttachmentReferenceLibraryItem(editingId, {
        name: form.name.trim(), description: form.description.trim(), category_key: form.category_key.trim() || null,
        module_keys: form.module_keys, reference_role: form.reference_role, guidance: form.guidance.trim(),
        tags: form.tags.split(/[，,]/).map((item) => item.trim()).filter(Boolean),
        is_featured: form.is_featured, is_active: form.is_active, sort_order: form.sort_order,
      })
      notify('参考图库配置已保存；需要时系统会生成新的理解版本。')
      resetForm(); await load()
    } catch (reason) { notify(reason instanceof Error ? reason.message : '保存失败') }
    finally { setBusy('') }
  }

  return <div className="space-y-5">
    <section className={panel}>
      <div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="font-semibold text-gray-950 dark:text-white">{editingId ? '编辑参考图配置' : '参考图库'}</h2><p className="mt-1 text-xs text-gray-500">按附图模块沉淀成熟构图。图库只建立 Asset 关系，不复制 MinIO 文件；运营选择后自动复用已分析理解。</p></div><span className="rounded-full bg-violet-50 px-3 py-1 text-xs font-semibold text-violet-700">启用 {activeCount} / {items.length}</span></div>
      <input ref={fileRef} hidden type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => { const file = event.target.files?.[0]; if (file) void upload(file) }} />
      <div className="mt-5 grid gap-3 lg:grid-cols-3">
        <input className={input} placeholder="参考图名称" value={form.name} onChange={(event) => setForm((value) => ({ ...value, name: event.target.value }))} />
        <select className={input} value={form.category_key} onChange={(event) => { const next = options.find((item) => item.category_key === event.target.value); setForm((value) => ({ ...value, category_key: event.target.value, module_keys: next?.modules[0] ? [next.modules[0].code] : [] })) }}><option value="">通用品类</option>{options.map((item) => <option key={item.category_key} value={item.category_key}>{item.category_name}</option>)}</select>
        <select className={input} value={form.reference_role} onChange={(event) => setForm((value) => ({ ...value, reference_role: event.target.value as Role }))}>{roles.map((role) => <option key={role} value={role}>{role}</option>)}</select>
        <input className={input} placeholder="标签，逗号分隔" value={form.tags} onChange={(event) => setForm((value) => ({ ...value, tags: event.target.value }))} />
        <input className={input} type="number" min={0} max={10000} aria-label="排序" value={form.sort_order} onChange={(event) => setForm((value) => ({ ...value, sort_order: Number(event.target.value) }))} />
      </div>
      <div className="mt-3 rounded-xl border border-gray-200 p-3"><div className="text-xs font-semibold text-gray-600">适用模块（可多选，来源于当前品类已发布 Skill）</div><div className="mt-2 flex flex-wrap gap-2">{moduleOptions.map((item) => <label key={item.code} className={`cursor-pointer rounded-lg border px-3 py-2 text-xs ${form.module_keys.includes(item.code) ? 'border-blue-500 bg-blue-50 text-blue-700' : 'border-gray-200 text-gray-600'}`}><input className="mr-2" type="checkbox" checked={form.module_keys.includes(item.code)} onChange={() => setForm((value) => ({ ...value, module_keys: value.module_keys.includes(item.code) ? value.module_keys.filter((code) => code !== item.code) : [...value.module_keys, item.code] }))} />{item.name}</label>)}</div></div>
      <textarea className={`${input} mt-3 min-h-20`} placeholder="Guidance：主要参考什么、明确禁止继承什么" value={form.guidance} onChange={(event) => setForm((value) => ({ ...value, guidance: event.target.value }))} />
      <textarea className={`${input} mt-3 min-h-16`} placeholder="说明（运营可见）" value={form.description} onChange={(event) => setForm((value) => ({ ...value, description: event.target.value }))} />
      <div className="mt-3 flex flex-wrap items-center gap-3"><label className="flex items-center gap-2 text-xs text-gray-600"><input type="checkbox" checked={form.is_featured} onChange={(event) => setForm((value) => ({ ...value, is_featured: event.target.checked }))} />推荐参考</label><label className="flex items-center gap-2 text-xs text-gray-600"><input type="checkbox" checked={form.is_active} onChange={(event) => setForm((value) => ({ ...value, is_active: event.target.checked }))} />立即启用</label>{editingId ? <><button className="rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50" disabled={busy !== '' || !form.module_keys.length || !form.name.trim()} onClick={() => void saveEdit()}>{busy === editingId ? '保存中…' : '保存配置'}</button><button className={button} disabled={busy !== ''} onClick={resetForm}>取消编辑</button></> : <button className="rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50" disabled={busy !== '' || !form.module_keys.length} onClick={() => fileRef.current?.click()}>{busy === 'create' ? '上传并分析中…' : '上传参考图'}</button>}</div>
    </section>

    <section className={panel}>
      <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-semibold text-gray-950 dark:text-white">图库项目</h2><p className="mt-1 text-xs text-gray-500">Guidance、Role 或模块变化会生成新的理解版本；停用不会删除历史引用。</p></div><div className="flex flex-wrap gap-2"><input className="rounded-xl border border-gray-200 px-3 py-2 text-xs dark:border-white/[0.1] dark:bg-gray-950" placeholder="搜索名称、标签或说明" value={search} onChange={(event) => setSearch(event.target.value)} /><select className="rounded-xl border border-gray-200 px-3 py-2 text-xs dark:border-white/[0.1] dark:bg-gray-950" value={moduleFilter} onChange={(event) => setModuleFilter(event.target.value)}><option value="">全部模块</option>{allModuleOptions.map((item) => <option key={item.code} value={item.code}>{item.name}</option>)}</select><select className="rounded-xl border border-gray-200 px-3 py-2 text-xs dark:border-white/[0.1] dark:bg-gray-950" value={roleFilter} onChange={(event) => setRoleFilter(event.target.value)}><option value="">全部角色</option>{roles.map((role) => <option key={role} value={role}>{role}</option>)}</select><select className="rounded-xl border border-gray-200 px-3 py-2 text-xs dark:border-white/[0.1] dark:bg-gray-950" value={activeFilter} onChange={(event) => setActiveFilter(event.target.value as typeof activeFilter)}><option value="all">全部状态</option><option value="active">仅启用</option><option value="inactive">仅停用</option></select><label className="flex items-center gap-2 rounded-xl border border-gray-200 px-3 py-2 text-xs"><input type="checkbox" checked={featuredOnly} onChange={(event) => setFeaturedOnly(event.target.checked)} />仅推荐</label></div></div>
      {error && <div className="mt-4 rounded-xl bg-red-50 p-3 text-xs text-red-700">{error}</div>}
      <div className="mt-4 grid gap-3 xl:grid-cols-2">{visibleItems.map((item) => <article key={item.id} className="flex gap-4 rounded-2xl border border-gray-200 p-3 dark:border-white/[0.08]">
        <AuthenticatedImage url={item.asset.url} alt={item.name} className="h-28 w-28 shrink-0 rounded-xl bg-gray-50 object-cover" />
        <div className="min-w-0 flex-1"><div className="flex items-start justify-between gap-2"><div><div className="truncate text-sm font-semibold text-gray-900 dark:text-white">{item.name}</div><div className="mt-1 text-[11px] text-gray-500">{item.category_key || '通用品类'} · {item.module_keys.join('、')} · {item.reference_role} · 排序 {item.sort_order}</div><div className="mt-1 text-[10px] text-gray-400">创建人 {item.created_by.slice(0, 8)} · 更新 {new Date(item.updated_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })}</div></div><span className={`rounded-full px-2 py-1 text-[10px] font-semibold ${item.understanding?.status === 'ready' ? 'bg-emerald-50 text-emerald-700' : item.understanding?.status === 'failed' ? 'bg-red-50 text-red-700' : 'bg-violet-50 text-violet-700'}`}>{item.understanding?.status === 'ready' ? `已理解 V${item.understanding.version_number}` : item.understanding?.status || '等待分析'}</span></div><p className="mt-2 line-clamp-2 text-xs leading-5 text-gray-500">{item.guidance || item.description || '未填写 Guidance'}</p><div className="mt-3 flex flex-wrap gap-2"><button className={button} disabled={busy !== ''} onClick={() => beginEdit(item)}>编辑配置</button><button className={button} disabled={busy !== ''} onClick={() => void update(item, { is_active: !item.is_active })}>{item.is_active ? '停用' : '启用'}</button><button className={button} disabled={busy !== ''} onClick={() => void update(item, { is_featured: !item.is_featured })}>{item.is_featured ? '取消推荐' : '设为推荐'}</button><button className={button} disabled={busy !== ''} onClick={() => { setBusy(item.id); void reanalyzeAttachmentReferenceLibraryItem(item.id).then(() => { notify('重新分析已提交。'); return load() }).catch((reason) => notify(reason instanceof Error ? reason.message : '提交失败')).finally(() => setBusy('')) }}>重新分析</button></div></div>
      </article>)}</div>
      {!visibleItems.length && !error && <div className="py-12 text-center text-sm text-gray-500">当前筛选下还没有参考图。</div>}
    </section>
  </div>
}
