import { useRef, useState, type DragEvent } from 'react'
import type { BatchTryOnTemplate } from '../types'
import { BatchTryOnImage } from './BatchTryOnImage'

interface Props {
  templates: BatchTryOnTemplate[]
  maxItems: number
  disabled?: boolean
  onUpload: (files: File[]) => void
  onRemove: (template: BatchTryOnTemplate) => void
  onRename: (templateId: string, name: string) => void
  onSetDefault: (templateId: string) => void
  onToggle: (templateId: string) => void
  onToggleAll: (selected: boolean) => void
  onView: (imageId: string) => void
}

export default function BatchTryOnTemplateManager({
  templates, maxItems, disabled, onUpload, onRemove, onRename, onSetDefault,
  onToggle, onToggleAll, onView,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const full = templates.length >= maxItems
  const selectedCount = templates.filter((item) => item.selected).length

  const receiveDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setDragging(false)
    if (!disabled && !full) onUpload(Array.from(event.dataTransfer.files))
  }

  return (
    <section className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm dark:border-white/[0.08] dark:bg-gray-950">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-bold text-gray-900 dark:text-gray-100">模板图管理</h3>
          <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">可多选模板，与选中的服装生成笛卡尔组合。</p>
        </div>
        <span className="rounded-full bg-gray-100 px-2.5 py-1 text-xs font-semibold text-gray-600 dark:bg-white/[0.07] dark:text-gray-300">已选 {selectedCount} / 共 {templates.length}</span>
      </div>

      <div
        onDragEnter={(event) => { event.preventDefault(); if (!disabled && !full) setDragging(true) }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={() => setDragging(false)}
        onDrop={receiveDrop}
        className={`mt-3 rounded-xl border border-dashed p-3 transition ${dragging ? 'border-blue-400 bg-blue-50 dark:bg-blue-500/10' : 'border-gray-300 bg-gray-50 dark:border-white/[0.12] dark:bg-white/[0.03]'}`}
      >
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" disabled={disabled || full} onClick={() => inputRef.current?.click()} className="h-9 rounded-lg bg-gray-900 px-3 text-xs font-semibold text-white disabled:opacity-40 dark:bg-white dark:text-gray-950">上传模板图</button>
          {templates.length > 0 && <>
            <button type="button" disabled={disabled || selectedCount === templates.length} onClick={() => onToggleAll(true)} className="h-9 rounded-lg border border-gray-200 px-3 text-xs font-semibold dark:border-white/[0.1]">全选模板</button>
            <button type="button" disabled={disabled || selectedCount === 0} onClick={() => onToggleAll(false)} className="h-9 rounded-lg border border-gray-200 px-3 text-xs font-semibold dark:border-white/[0.1]">取消全选</button>
          </>}
        </div>
        <div className="mt-2 text-xs text-gray-400">支持多选或拖拽 PNG、JPG、JPEG、WEBP，最多 {maxItems} 张。</div>
      </div>

      {templates.length ? <div className="mt-3 grid max-h-[430px] gap-3 overflow-y-auto pr-1 sm:grid-cols-2">
        {templates.map((template) => <article key={template.id} className={`rounded-xl border p-2 ${template.selected ? 'border-blue-300 bg-blue-50/40 dark:border-blue-500/40 dark:bg-blue-500/5' : 'border-gray-200 dark:border-white/[0.08]'}`}>
          <div className="flex gap-3">
            <button type="button" onClick={() => onView(template.imageId)} className="h-20 w-20 shrink-0 overflow-hidden rounded-lg bg-gray-100 dark:bg-gray-900">
              <BatchTryOnImage imageId={template.imageId} alt={template.displayName} className="h-full w-full object-cover" />
            </button>
            <div className="min-w-0 flex-1">
              <label className="flex items-center gap-2 text-xs font-semibold text-gray-700 dark:text-gray-200">
                <input type="checkbox" checked={template.selected} disabled={disabled} onChange={() => onToggle(template.id)} />
                参与本次生成
              </label>
              <input
                value={template.displayName}
                disabled={disabled}
                maxLength={120}
                onChange={(event) => onRename(template.id, event.target.value)}
                className="mt-2 h-8 w-full rounded-lg border border-gray-200 bg-white px-2 text-xs font-semibold outline-none focus:border-blue-400 dark:border-white/[0.1] dark:bg-gray-950"
                aria-label={`重命名 ${template.displayName}`}
              />
              <div className="mt-1 truncate text-[11px] text-gray-400" title={template.fileName}>{template.fileName}</div>
            </div>
          </div>
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
            <button type="button" disabled={disabled || template.isDefault} onClick={() => onSetDefault(template.id)} className={`rounded-md px-2 py-1 text-[11px] font-semibold ${template.isDefault ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-200' : 'border border-gray-200 dark:border-white/[0.1]'}`}>{template.isDefault ? '默认模板' : '设为默认'}</button>
            <button type="button" disabled={disabled} onClick={() => onRemove(template)} className="rounded-md px-2 py-1 text-[11px] font-semibold text-red-600 disabled:opacity-40">删除模板</button>
          </div>
        </article>)}
      </div> : <div className="mt-3 rounded-xl border border-dashed border-gray-200 px-4 py-10 text-center text-xs text-gray-400 dark:border-white/[0.08]">尚未上传模板图</div>}
      <input ref={inputRef} type="file" multiple accept="image/png,image/jpeg,image/webp" className="hidden" onChange={(event) => { onUpload(Array.from(event.target.files || [])); event.target.value = '' }} />
    </section>
  )
}
