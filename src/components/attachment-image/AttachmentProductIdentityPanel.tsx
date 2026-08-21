import { useEffect, useMemo, useState } from 'react'
import type { AttachmentProductIdentityLock } from '../../lib/attachmentPlanningApi'

const input = 'w-full rounded-lg border border-gray-200 bg-white px-2.5 py-2 text-xs text-gray-800 outline-none focus:border-blue-500 dark:border-white/[0.1] dark:bg-gray-950 dark:text-gray-100'
const button = 'rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs font-semibold text-gray-700 disabled:opacity-50 dark:border-white/[0.1] dark:bg-gray-950 dark:text-gray-200'

const scalarFields: Array<[string, string]> = [
  ['category', '品类'], ['primary_color', '主色'], ['collar', '领口'], ['sleeve_type', '袖型'],
  ['garment_structure', '服装结构'], ['front_text', '正面文字'], ['back_text', '背面文字'],
  ['front_number', '正面号码'], ['back_number', '背面号码'], ['shoulder_number', '肩号'],
  ['print_structure', '印花结构'],
]
const listFields: Array<[string, string]> = [
  ['secondary_colors', '辅助色'], ['logos', 'Logo'], ['customization_elements', '定制元素'],
  ['material_visual_features', '可见材质特征'], ['immutable_features', '必须保持'],
  ['forbidden_changes', '禁止改变'], ['needs_confirmation', '需要人工确认'],
]

function textValue(value: unknown) {
  return value == null ? '' : Array.isArray(value) ? value.join('\n') : String(value)
}

export default function AttachmentProductIdentityPanel({
  value, busy, onSave, onReextract,
}: {
  value: AttachmentProductIdentityLock | null
  busy: boolean
  onSave: (structured: Record<string, unknown>) => Promise<void>
  onReextract: () => Promise<void>
}) {
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<Record<string, unknown>>({})
  useEffect(() => { if (!editing) setDraft(value?.structured || {}) }, [editing, value?.id, value?.structured])
  const unknownCount = useMemo(() => Object.values(value?.structured || {}).filter((item) => item === 'unknown').length, [value?.structured])
  const status = value?.status === 'ready' ? `已锁定 V${value.version_number}` : value?.status === 'failed' ? '提取失败' : '提取中'
  const update = (key: string, raw: string, list = false) => setDraft((current) => ({
    ...current,
    [key]: list ? raw.split(/\r?\n/).map((item) => item.trim()).filter(Boolean) : raw.trim() || 'unknown',
  }))

  return <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm dark:border-white/[0.08] dark:bg-gray-900">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><h2 className="font-semibold text-gray-950 dark:text-white">商品事实</h2><p className="mt-1 text-xs text-gray-500">AI从 PRODUCT / PRINT 与已确认 Listing 提取不可改变的商品事实；策划和生图会绑定具体版本。</p></div>
      <div className="flex items-center gap-2"><span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${value?.status === 'ready' ? 'bg-emerald-50 text-emerald-700' : value?.status === 'failed' ? 'bg-red-50 text-red-700' : 'bg-violet-50 text-violet-700'}`}>{status}</span><button type="button" className={button} onClick={() => setOpen((current) => !current)}>{open ? '收起' : '查看商品事实'}</button></div>
    </div>
    {value?.status === 'failed' && <div className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">{value.error_message || '商品事实提取失败'} <button className="ml-2 font-semibold underline" disabled={busy} onClick={() => void onReextract()}>重新提取</button></div>}
    {value?.status === 'ready' && !open && <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-gray-600">{scalarFields.slice(0, 5).map(([key, label]) => <span key={key} className="rounded-full bg-gray-100 px-2.5 py-1 dark:bg-white/[0.06]">{label}：{textValue(value.structured[key]) || 'unknown'}</span>)}{unknownCount > 0 && <span className="rounded-full bg-amber-50 px-2.5 py-1 text-amber-700">{unknownCount} 项待确认</span>}</div>}
    {open && <div className="mt-4 space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{scalarFields.map(([key, label]) => <label key={key} className="text-[11px] font-semibold text-gray-500">{label}<input disabled={!editing} className={`${input} mt-1 disabled:bg-gray-50 disabled:text-gray-500`} value={textValue(draft[key])} onChange={(event) => update(key, event.target.value)} /></label>)}</div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{listFields.map(([key, label]) => <label key={key} className="text-[11px] font-semibold text-gray-500">{label}（每行一项）<textarea disabled={!editing} className={`${input} mt-1 min-h-24 resize-y disabled:bg-gray-50 disabled:text-gray-500`} value={textValue(draft[key])} onChange={(event) => update(key, event.target.value, true)} /></label>)}</div>
      <div className="flex flex-wrap items-center gap-2"><button type="button" className={button} disabled={busy || value?.status !== 'ready'} onClick={() => setEditing((current) => !current)}>{editing ? '取消修改' : '修正商品事实'}</button>{editing && <button type="button" className="rounded-lg bg-blue-600 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50" disabled={busy} onClick={() => void onSave(draft).then(() => setEditing(false))}>保存新事实</button>}<button type="button" className={button} disabled={busy || value?.status === 'analyzing'} onClick={() => void onReextract()}>重新从图片提取</button><span className="text-[11px] text-gray-400">模型：{value?.ai_model || '等待路由'} · {value?.corrected_by_user ? '已人工修正' : 'AI提取'}</span></div>
    </div>}
  </section>
}
