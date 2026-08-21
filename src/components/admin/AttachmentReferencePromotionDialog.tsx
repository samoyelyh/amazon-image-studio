import { useEffect, useMemo, useState } from 'react'
import { AuthApiError } from '../../lib/authApi'
import {
  getAdminAttachmentReferenceLibraryOptions,
  type AttachmentReferenceLibraryCategoryOption,
  type AttachmentReferenceLibrarySourceMutation,
} from '../../lib/attachmentReferenceLibraryApi'

const input = 'w-full rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-500 dark:border-white/[0.1] dark:bg-gray-950 dark:text-white'
const roles = ['TEMPLATE', 'SCENE', 'PRINT', 'OTHER'] as const

interface Props {
  open: boolean
  title: string
  defaultName: string
  defaultCategoryKey?: string
  defaultModuleKey: string
  defaultTags?: string[]
  onClose: () => void
  onSubmit: (input: AttachmentReferenceLibrarySourceMutation) => Promise<unknown>
}

export default function AttachmentReferencePromotionDialog({
  open, title, defaultName, defaultCategoryKey = '', defaultModuleKey, defaultTags = [], onClose, onSubmit,
}: Props) {
  const [options, setOptions] = useState<AttachmentReferenceLibraryCategoryOption[]>([])
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState({
    name: defaultName, description: '', category_key: defaultCategoryKey,
    module_keys: [defaultModuleKey], reference_role: 'TEMPLATE' as typeof roles[number],
    tags: defaultTags.join('，'), guidance: '', is_featured: false, is_active: true, sort_order: 100,
  })
  useEffect(() => {
    if (!open) return
    setForm({
      name: defaultName, description: '', category_key: defaultCategoryKey,
      module_keys: [defaultModuleKey], reference_role: 'TEMPLATE', tags: defaultTags.join('，'),
      guidance: '', is_featured: false, is_active: true, sort_order: 100,
    })
    void getAdminAttachmentReferenceLibraryOptions().then(setOptions).catch(() => setOptions([]))
  }, [defaultCategoryKey, defaultModuleKey, defaultName, defaultTags.join('|'), open])
  const modules = useMemo(() => {
    const selected = options.find((item) => item.category_key === form.category_key)
    if (selected) return selected.modules
    const merged = new Map<string, { code: string; name: string; sort_order: number }>()
    for (const option of options) for (const module of option.modules) if (!merged.has(module.code)) merged.set(module.code, module)
    return [...merged.values()].sort((a, b) => a.sort_order - b.sort_order)
  }, [form.category_key, options])
  if (!open) return null

  const submit = async (allowDuplicateAsset = false) => {
    if (!form.name.trim() || !form.module_keys.length) return
    setBusy(true)
    const payload: AttachmentReferenceLibrarySourceMutation = {
      name: form.name.trim(), description: form.description.trim(), category_key: form.category_key || null,
      module_keys: form.module_keys, reference_role: form.reference_role, guidance: form.guidance.trim(),
      tags: form.tags.split(/[，,]/).map((item) => item.trim()).filter(Boolean),
      is_featured: form.is_featured, is_active: form.is_active, sort_order: form.sort_order,
      allow_duplicate_asset: allowDuplicateAsset,
    }
    try { await onSubmit(payload); onClose() }
    catch (reason) {
      if (reason instanceof AuthApiError && reason.code === 'reference_library.duplicate_confirmation_required' && !allowDuplicateAsset) {
        if (window.confirm(`${reason.message}\n\n确认作为新的使用规则添加吗？`)) await submit(true)
      } else window.alert(reason instanceof Error ? reason.message : '加入参考图库失败')
    } finally { setBusy(false) }
  }

  return <div className="fixed inset-0 z-[140] flex items-center justify-center bg-black/60 p-4" role="dialog" aria-modal="true" aria-label={title}>
    <div className="max-h-[92vh] w-full max-w-2xl overflow-auto rounded-2xl bg-white p-5 shadow-2xl dark:bg-gray-900">
      <div className="flex items-start justify-between gap-3"><div><h2 className="text-lg font-semibold text-gray-950 dark:text-white">{title}</h2><p className="mt-1 text-xs text-gray-500">复用当前图片 Asset，不复制对象存储文件。保存成功后后台分析不会阻塞关闭弹窗。</p></div><button type="button" className="text-xl text-gray-400" onClick={onClose}>×</button></div>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <label className="text-xs font-semibold text-gray-600">名称<input className={`${input} mt-1`} value={form.name} onChange={(event) => setForm((value) => ({ ...value, name: event.target.value }))} /></label>
        <label className="text-xs font-semibold text-gray-600">品类<select className={`${input} mt-1`} value={form.category_key} onChange={(event) => { const next = options.find((item) => item.category_key === event.target.value); setForm((value) => ({ ...value, category_key: event.target.value, module_keys: next?.modules.some((item) => item.code === defaultModuleKey) ? [defaultModuleKey] : next?.modules[0] ? [next.modules[0].code] : value.module_keys })) }}><option value="">通用品类</option>{options.map((item) => <option key={item.category_key} value={item.category_key}>{item.category_name}</option>)}</select></label>
        <label className="text-xs font-semibold text-gray-600">Reference Role<select className={`${input} mt-1`} value={form.reference_role} onChange={(event) => setForm((value) => ({ ...value, reference_role: event.target.value as typeof roles[number] }))}>{roles.map((role) => <option key={role} value={role}>{role}</option>)}</select></label>
        <label className="text-xs font-semibold text-gray-600">排序<input className={`${input} mt-1`} type="number" min={0} max={10000} value={form.sort_order} onChange={(event) => setForm((value) => ({ ...value, sort_order: Number(event.target.value) }))} /></label>
      </div>
      <div className="mt-3 rounded-xl border border-gray-200 p-3"><div className="text-xs font-semibold text-gray-600">适用模块（可多选）</div><div className="mt-2 flex flex-wrap gap-2">{modules.map((module) => <label key={module.code} className={`cursor-pointer rounded-lg border px-3 py-2 text-xs ${form.module_keys.includes(module.code) ? 'border-violet-500 bg-violet-50 text-violet-700' : 'border-gray-200 text-gray-600'}`}><input className="mr-2" type="checkbox" checked={form.module_keys.includes(module.code)} onChange={() => setForm((value) => ({ ...value, module_keys: value.module_keys.includes(module.code) ? value.module_keys.filter((code) => code !== module.code) : [...value.module_keys, module.code] }))} />{module.name}</label>)}</div></div>
      <label className="mt-3 block text-xs font-semibold text-gray-600">AI参考说明 Guidance<textarea className={`${input} mt-1 min-h-24`} value={form.guidance} onChange={(event) => setForm((value) => ({ ...value, guidance: event.target.value }))} placeholder="写明重点参考什么，以及禁止继承哪些商品身份内容。" /></label>
      <label className="mt-3 block text-xs font-semibold text-gray-600">描述<textarea className={`${input} mt-1 min-h-16`} value={form.description} onChange={(event) => setForm((value) => ({ ...value, description: event.target.value }))} /></label>
      <label className="mt-3 block text-xs font-semibold text-gray-600">标签<input className={`${input} mt-1`} value={form.tags} onChange={(event) => setForm((value) => ({ ...value, tags: event.target.value }))} placeholder="礼品，俯拍，暖色光" /></label>
      <div className="mt-3 flex gap-5"><label className="flex items-center gap-2 text-xs text-gray-600"><input type="checkbox" checked={form.is_featured} onChange={(event) => setForm((value) => ({ ...value, is_featured: event.target.checked }))} />推荐参考</label><label className="flex items-center gap-2 text-xs text-gray-600"><input type="checkbox" checked={form.is_active} onChange={(event) => setForm((value) => ({ ...value, is_active: event.target.checked }))} />立即启用</label></div>
      <div className="mt-5 flex justify-end gap-2"><button type="button" className="rounded-lg border border-gray-200 px-3 py-2 text-sm font-semibold" disabled={busy} onClick={onClose}>取消</button><button type="button" className="rounded-lg bg-violet-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50" disabled={busy || !form.name.trim() || !form.module_keys.length} onClick={() => void submit()}>{busy ? '保存中…' : '加入公共参考图库'}</button></div>
    </div>
  </div>
}
