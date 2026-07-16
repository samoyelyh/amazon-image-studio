import { useRef, useState, type DragEvent } from 'react'
import type { BatchTryOnItem } from '../types'
import { BatchTryOnImage } from './BatchTryOnImage'

interface Props {
  items: BatchTryOnItem[]
  maxItems: number
  disabled?: boolean
  onUpload: (files: File[]) => void
  onRemove: (item: BatchTryOnItem) => void
  onClear: () => void
  onView: (imageId: string) => void
}

export default function BatchTryOnGarmentList({ items, maxItems, disabled, onUpload, onRemove, onClear, onView }: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const full = items.length >= maxItems

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
          <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">每张图片作为一个独立款式任务，按上传顺序生成。</p>
        </div>
        <span className="shrink-0 rounded-full bg-gray-100 px-2.5 py-1 text-xs font-semibold text-gray-600 dark:bg-white/[0.07] dark:text-gray-300">{items.length} / {maxItems}</span>
      </div>

      <div
        onDragEnter={(event) => { event.preventDefault(); if (!disabled && !full) setDragging(true) }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={() => setDragging(false)}
        onDrop={receiveDrop}
        className={`mt-3 rounded-xl border border-dashed p-3 transition ${dragging ? 'border-blue-400 bg-blue-50 dark:bg-blue-500/10' : 'border-gray-300 bg-gray-50 dark:border-white/[0.12] dark:bg-white/[0.03]'}`}
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <button type="button" disabled={disabled || full} onClick={() => inputRef.current?.click()} className="inline-flex h-9 items-center rounded-lg bg-gray-900 px-3 text-xs font-semibold text-white transition hover:bg-gray-700 disabled:cursor-not-allowed disabled:bg-gray-300 dark:bg-white dark:text-gray-950 dark:hover:bg-gray-200 dark:disabled:bg-white/[0.12] dark:disabled:text-gray-500">上传服装图片</button>
          {items.length > 0 && <button type="button" disabled={disabled} onClick={onClear} className="h-9 rounded-lg px-3 text-xs font-medium text-red-600 transition hover:bg-red-50 disabled:opacity-50 dark:text-red-300 dark:hover:bg-red-400/10">清空全部</button>}
        </div>
        <div className="mt-2 text-xs text-gray-400">支持多选或拖拽 PNG、JPG、JPEG、WEBP，最多 {maxItems} 张。</div>
      </div>

      {items.length > 0 ? (
        <div className="mt-3 max-h-[350px] space-y-2 overflow-y-auto pr-1">
          {items.map((item) => (
            <div key={item.id} className="flex items-center gap-3 rounded-xl border border-gray-200 bg-white p-2 dark:border-white/[0.08] dark:bg-gray-900">
              <button type="button" onClick={() => onView(item.garmentImageId)} className="h-14 w-14 shrink-0 overflow-hidden rounded-lg bg-gray-100 dark:bg-gray-800" title="查看大图">
                <BatchTryOnImage imageId={item.garmentImageId} alt={item.garmentFileName} className="h-full w-full object-cover" />
              </button>
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium text-gray-800 dark:text-gray-100" title={item.garmentFileName}>{item.garmentFileName}</div>
                <div className="mt-0.5 text-xs text-gray-400">第 {item.index + 1} 个款式</div>
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
    </section>
  )
}
