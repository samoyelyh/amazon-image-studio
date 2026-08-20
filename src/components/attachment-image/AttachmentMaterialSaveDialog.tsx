import { useEffect, useMemo, useState } from 'react'
import type { AttachmentMaterialSaveContext, AttachmentMaterialSaveInput } from '../../lib/attachmentMaterialApi'

interface Props {
  open: boolean
  context: AttachmentMaterialSaveContext | null
  title?: string
  saving: boolean
  onClose: () => void
  onSubmit: (input: AttachmentMaterialSaveInput) => Promise<void>
}

export default function AttachmentMaterialSaveDialog({ open, context, title = '保存到个人素材库', saving, onClose, onSubmit }: Props) {
  const [name, setName] = useState('')
  const [tagsText, setTagsText] = useState('')
  const [note, setNote] = useState('')
  const [saveMode, setSaveMode] = useState<'update_existing' | 'new'>('update_existing')

  useEffect(() => {
    if (!open || !context) return
    setName(context.existing_display_name || context.default_name)
    setTagsText(context.suggested_tags.join('，'))
    setNote(context.existing_note || '')
    setSaveMode(context.existing_material_set_id ? 'update_existing' : 'new')
  }, [context, open])

  const tags = useMemo(
    () => [...new Set(tagsText.split(/[,，]/).map((value) => value.trim()).filter(Boolean))].slice(0, 12),
    [tagsText],
  )
  if (!open || !context) return null

  return <div className="fixed inset-0 z-[110] flex items-center justify-center bg-slate-950/50 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-label={title}>
    <form className="w-full max-w-xl overflow-hidden rounded-2xl border border-white/60 bg-white shadow-2xl dark:border-white/[0.08] dark:bg-gray-900" onSubmit={(event) => {
      event.preventDefault()
      if (!name.trim() || saving) return
      void onSubmit({
        display_name: name.trim(), tags, note: note.trim(), save_mode: saveMode,
        material_set_id: saveMode === 'update_existing' ? context.existing_material_set_id : null,
      })
    }}>
      <div className="border-b border-gray-100 px-6 py-5 dark:border-white/[0.07]">
        <div className="flex items-start justify-between gap-4">
          <div><h2 className="text-lg font-semibold text-gray-950 dark:text-white">{title}</h2><p className="mt-1 text-sm text-gray-500">保存的是当前结果引用与制作快照，不会复制对象存储文件。</p></div>
          <button type="button" className="text-2xl leading-none text-gray-400 hover:text-gray-700" onClick={onClose}>×</button>
        </div>
      </div>
      <div className="space-y-5 px-6 py-5">
        {context.existing_material_set_id && <div className="grid grid-cols-2 gap-2 rounded-xl bg-gray-50 p-1 dark:bg-white/[0.04]">
          <button type="button" className={`rounded-lg px-3 py-2 text-sm font-semibold ${saveMode === 'update_existing' ? 'bg-white text-blue-700 shadow-sm dark:bg-gray-800 dark:text-blue-300' : 'text-gray-500'}`} onClick={() => setSaveMode('update_existing')}>更新现有素材套装</button>
          <button type="button" className={`rounded-lg px-3 py-2 text-sm font-semibold ${saveMode === 'new' ? 'bg-white text-blue-700 shadow-sm dark:bg-gray-800 dark:text-blue-300' : 'text-gray-500'}`} onClick={() => setSaveMode('new')}>另存为新套装</button>
        </div>}
        <label className="block"><span className="text-sm font-semibold text-gray-800 dark:text-gray-200">素材套装名称</span><input autoFocus value={name} maxLength={255} onChange={(event) => setName(event.target.value)} className="mt-2 w-full rounded-xl border border-gray-200 bg-white px-3.5 py-2.5 text-sm outline-none transition focus:border-blue-500 focus:ring-4 focus:ring-blue-500/10 dark:border-white/[0.1] dark:bg-gray-950" /></label>
        <label className="block"><span className="text-sm font-semibold text-gray-800 dark:text-gray-200">标签</span><input value={tagsText} onChange={(event) => setTagsText(event.target.value)} placeholder="用逗号分隔，如：橄榄球衣，Listing套图" className="mt-2 w-full rounded-xl border border-gray-200 bg-white px-3.5 py-2.5 text-sm outline-none focus:border-blue-500 dark:border-white/[0.1] dark:bg-gray-950" /><span className="mt-1.5 block text-xs text-gray-400">最多 12 个标签，当前 {tags.length} 个</span></label>
        <label className="block"><span className="text-sm font-semibold text-gray-800 dark:text-gray-200">备注</span><textarea value={note} maxLength={4000} rows={3} onChange={(event) => setNote(event.target.value)} placeholder="可选：记录本套图的用途、商品版本或后续修改方向" className="mt-2 w-full resize-none rounded-xl border border-gray-200 bg-white px-3.5 py-2.5 text-sm outline-none focus:border-blue-500 dark:border-white/[0.1] dark:bg-gray-950" /></label>
      </div>
      <div className="flex items-center justify-between border-t border-gray-100 bg-gray-50/70 px-6 py-4 dark:border-white/[0.07] dark:bg-white/[0.02]">
        <p className="text-xs text-gray-500">内容未变化时不会重复创建版本。</p>
        <div className="flex gap-2"><button type="button" className="rounded-lg border border-gray-200 bg-white px-4 py-2 text-sm font-semibold text-gray-700 dark:border-white/[0.1] dark:bg-gray-900 dark:text-gray-200" onClick={onClose}>取消</button><button type="submit" disabled={!name.trim() || saving} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm disabled:opacity-50">{saving ? '正在保存…' : saveMode === 'new' ? '保存新套装' : '保存新版本'}</button></div>
      </div>
    </form>
  </div>
}
