import { useRef, useState, type DragEvent } from 'react'
import { useImagePaste } from '../hooks/useImagePaste'
import type { BatchTryOnGarment } from '../types'
import { BatchTryOnImage } from './BatchTryOnImage'
import BatchTryOnGarmentFontReference from './BatchTryOnGarmentFontReference'

interface Props {
  items: BatchTryOnGarment[]
  maxItems: number
  disabled?: boolean
  combinationMode?: 'cartesian' | 'one_to_one'
  onUpload: (files: File[]) => void
  onRemove: (item: BatchTryOnGarment) => void
  onClear: () => void
  onToggle: (itemId: string) => void
  onToggleAll: (selected: boolean) => void
  onView: (imageId: string) => void
  onFontReferenceUpload: (garmentId: string, file: File) => void
  onFontReferenceRemove: (garmentId: string) => void
  onBulkFontReferenceUpload: (files: File[]) => void
  onPreprocess: (garmentId?: string) => void
  sampleGarmentId?: string
  onSetSampleGarment: (garmentId: string) => void
}

export default function BatchTryOnGarmentList({
  items, maxItems, disabled, combinationMode = 'cartesian', onUpload, onRemove, onClear, onToggle, onToggleAll, onView,
  onFontReferenceUpload, onFontReferenceRemove, onBulkFontReferenceUpload, onPreprocess,
  sampleGarmentId, onSetSampleGarment,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  const bulkFontInputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const full = items.length >= maxItems
  const selectedCount = items.filter((item) => item.selected).length
  const pasteZoneProps = useImagePaste({
    disabled: Boolean(disabled || full),
    maxFiles: Math.max(0, maxItems - items.length),
    onPasteFiles: onUpload,
  })

  const receiveDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setDragging(false)
    if (!disabled && !full) onUpload(Array.from(event.dataTransfer.files))
  }

  return (
    <section className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm dark:border-white/[0.08] dark:bg-gray-950">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-bold text-gray-900 dark:text-gray-100">待套服装</h3>
          <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">{combinationMode === 'one_to_one' ? '按当前已选顺序与模板一一配对；字体图仍按完整数字编号匹配服装。' : '每张图片作为一个独立款式任务，按上传顺序生成。'}</p>
        </div>
        <span className="shrink-0 rounded-full bg-gray-100 px-2.5 py-1 text-xs font-semibold text-gray-600 dark:bg-white/[0.07] dark:text-gray-300">已选 {selectedCount} / 共 {items.length}</span>
      </div>

      <div
        {...pasteZoneProps}
        onDragEnter={(event) => { event.preventDefault(); if (!disabled && !full) setDragging(true) }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={() => setDragging(false)}
        onDrop={receiveDrop}
        className={`mt-3 rounded-xl border border-dashed p-3 outline-none transition focus:ring-2 focus:ring-blue-500/20 ${dragging ? 'border-blue-400 bg-blue-50 dark:bg-blue-500/10' : 'border-gray-300 bg-gray-50 dark:border-white/[0.12] dark:bg-white/[0.03]'}`}
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <button type="button" disabled={disabled || full} onClick={() => inputRef.current?.click()} className="inline-flex h-9 items-center rounded-lg bg-gray-900 px-3 text-xs font-semibold text-white transition hover:bg-gray-700 disabled:cursor-not-allowed disabled:bg-gray-300 dark:bg-white dark:text-gray-950 dark:hover:bg-gray-200 dark:disabled:bg-white/[0.12] dark:disabled:text-gray-500">上传服装图片</button>
          {items.length > 0 && <div className="flex gap-2">
            <button type="button" disabled={disabled} onClick={() => onPreprocess()} className="h-9 rounded-lg border border-violet-200 bg-violet-50 px-3 text-xs font-semibold text-violet-700 disabled:opacity-40 dark:border-violet-400/20 dark:bg-violet-500/10 dark:text-violet-200">批量裁剪 / 遮罩</button>
            <button type="button" disabled={disabled} onClick={() => bulkFontInputRef.current?.click()} className="h-9 rounded-lg border border-blue-200 bg-blue-50 px-3 text-xs font-semibold text-blue-700 disabled:opacity-40 dark:border-blue-400/20 dark:bg-blue-500/10 dark:text-blue-200">批量匹配字体图</button>
            <button type="button" disabled={disabled || selectedCount === items.length} onClick={() => onToggleAll(true)} className="h-9 rounded-lg border border-gray-200 px-3 text-xs font-semibold disabled:opacity-40 dark:border-white/[0.1]">全选服装</button>
            <button type="button" disabled={disabled || selectedCount === 0} onClick={() => onToggleAll(false)} className="h-9 rounded-lg border border-gray-200 px-3 text-xs font-semibold disabled:opacity-40 dark:border-white/[0.1]">取消全选</button>
          </div>}
          {items.length > 0 && <button type="button" disabled={disabled} onClick={onClear} className="h-9 rounded-lg px-3 text-xs font-medium text-red-600 transition hover:bg-red-50 disabled:opacity-50 dark:text-red-300 dark:hover:bg-red-400/10">清空全部</button>}
        </div>
        <div className="mt-2 text-xs text-gray-400">支持多选、拖拽或点击此区域后 Ctrl/⌘+V 粘贴 PNG、JPG、JPEG、WEBP，最多 {maxItems} 张。</div>
        {items.length > 0 && <div className="mt-1 text-[11px] text-blue-600 dark:text-blue-300">字体图可逐件添加；批量匹配会比较服装与字体图文件名中的完整数字编号，例如 0000532，前置零不会丢失。</div>}
      </div>

      {items.length > 0 ? (
        <div className="mt-3 max-h-[350px] space-y-2 overflow-y-auto pr-1">
          {items.map((item) => (
            <div key={item.id} className="flex items-center gap-3 rounded-xl border border-gray-200 bg-white p-2 dark:border-white/[0.08] dark:bg-gray-900">
              <button type="button" onClick={() => onView(item.garmentImageId)} className="h-14 w-14 shrink-0 overflow-hidden rounded-lg bg-gray-100 dark:bg-gray-800" title="查看大图">
                <BatchTryOnImage imageId={item.garmentImageId} alt={item.garmentFileName} className="h-full w-full object-cover" />
              </button>
              <span className="shrink-0 text-xs text-gray-300" aria-hidden="true">→</span>
              <BatchTryOnGarmentFontReference
                garmentName={item.garmentFileName}
                reference={item.fontReference}
                disabled={disabled}
                onUpload={(file) => onFontReferenceUpload(item.id, file)}
                onRemove={() => onFontReferenceRemove(item.id)}
                onView={onView}
              />
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium text-gray-800 dark:text-gray-100" title={item.garmentFileName}>{item.garmentFileName}</div>
                <div className="mt-0.5 truncate text-xs text-gray-400" title={item.fontReference?.fileName || '未设置字体参考图'}>
                  {combinationMode === 'one_to_one' && item.selected
                    ? `配对顺序 ${items.filter((candidate) => candidate.selected).findIndex((candidate) => candidate.id === item.id) + 1}`
                    : `第 ${item.index + 1} 个款式`}
                  {' · '}{item.fontReference ? `字体参考：${item.fontReference.fileName}` : '未设置字体参考'}
                </div>
                <label className="mt-1.5 flex items-center gap-1.5 text-[11px] font-semibold text-gray-600 dark:text-gray-300"><input type="checkbox" checked={item.selected} disabled={disabled} onChange={() => onToggle(item.id)} />参与本次生成</label>
                <button type="button" disabled={disabled} onClick={() => onSetSampleGarment(item.id)} className={`mt-1.5 rounded-md px-2 py-1 text-[11px] font-semibold ${sampleGarmentId === item.id ? 'bg-blue-100 text-blue-700 dark:bg-blue-500/15 dark:text-blue-200' : 'bg-gray-100 text-gray-500 dark:bg-white/[0.06]'}`}>
                  {sampleGarmentId === item.id ? '✓ 样图商品' : '设为样图商品'}
                </button>
                <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[11px]">
                  <span className={item.references?.front ? 'text-emerald-600' : 'text-gray-400'}>正面参考 {item.references?.front ? '✓' : '—'}</span>
                  <span className={item.references?.back ? 'text-emerald-600' : 'text-gray-400'}>背面参考 {item.references?.back ? '✓' : '—'}</span>
                  <button type="button" disabled={disabled} onClick={() => onPreprocess(item.id)} className="font-semibold text-blue-600 disabled:opacity-40">{item.references?.front || item.references?.back ? '重新处理' : '处理'}</button>
                  {item.references?.front && <button type="button" onClick={() => onView(item.references!.front!.imageId)} className="text-gray-500">查看正面</button>}
                  {item.references?.back && <button type="button" onClick={() => onView(item.references!.back!.imageId)} className="text-gray-500">查看背面</button>}
                </div>
              </div>
              <button type="button" disabled={disabled} onClick={() => onRemove(item)} className="rounded-lg p-2 text-gray-400 transition hover:bg-red-50 hover:text-red-600 disabled:opacity-40 dark:hover:bg-red-400/10 dark:hover:text-red-300" aria-label={`删除 ${item.garmentFileName}`}>
                <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
              </button>
            </div>
          ))}
        </div>
      ) : (
        <div className="mt-3 rounded-xl border border-dashed border-gray-200 px-4 py-8 text-center text-xs text-gray-400 dark:border-white/[0.08]">尚未上传服装图片</div>
      )}
      <input ref={inputRef} type="file" multiple accept="image/png,image/jpeg,image/webp" className="hidden" onChange={(event) => { onUpload(Array.from(event.target.files || [])); event.target.value = '' }} />
      <input ref={bulkFontInputRef} type="file" multiple accept="image/png,image/jpeg,image/webp" className="hidden" onChange={(event) => { onBulkFontReferenceUpload(Array.from(event.target.files || [])); event.target.value = '' }} />
    </section>
  )
}
