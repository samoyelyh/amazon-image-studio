import { useRef, useState, type DragEvent } from 'react'
import { BatchTryOnImage } from './BatchTryOnImage'

interface Props {
  imageId: string | null
  fileName?: string
  width?: number
  height?: number
  disabled?: boolean
  onUpload: (files: File[]) => void
  onRemove: () => void
  onView: () => void
  sourceLabel?: string
}

export default function BatchTryOnTemplateUploader({ imageId, fileName, width, height, disabled, onUpload, onRemove, onView, sourceLabel }: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  const receiveDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setDragging(false)
    if (!disabled) onUpload(Array.from(event.dataTransfer.files).slice(0, 1))
  }

  return (
    <section className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm dark:border-white/[0.08] dark:bg-gray-950">
      <div className="mb-3">
        <h3 className="text-sm font-bold text-gray-900 dark:text-gray-100">模特模板图</h3>
        <p className="mt-1 text-xs leading-relaxed text-gray-500 dark:text-gray-400">
          上传一张包含模特和完整场景的副图。批量生成时只替换模特身上的服装，人物、姿势、背景、构图和光线保持不变。
        </p>
      </div>
      <div
        onDragEnter={(event) => { event.preventDefault(); if (!disabled) setDragging(true) }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={() => setDragging(false)}
        onDrop={receiveDrop}
        className={`relative overflow-hidden rounded-xl border border-dashed transition ${dragging ? 'border-blue-400 bg-blue-50 dark:bg-blue-500/10' : 'border-gray-300 bg-gray-50 dark:border-white/[0.12] dark:bg-white/[0.03]'}`}
      >
        {imageId ? (
          <div className="grid gap-3 p-3 sm:grid-cols-[160px_minmax(0,1fr)]">
            <button type="button" onClick={onView} className="aspect-[4/3] overflow-hidden rounded-lg bg-gray-100 dark:bg-gray-900" title="查看大图">
              <BatchTryOnImage imageId={imageId} alt="模特模板图" className="h-full w-full object-cover" />
            </button>
            <div className="flex min-w-0 flex-col justify-between gap-3 py-1">
              <div>
                <div className="truncate text-sm font-semibold text-gray-800 dark:text-gray-100" title={fileName}>{fileName || '模特模板图'}</div>
                <div className="mt-1 text-xs text-gray-500 dark:text-gray-400">{width && height ? `${width} × ${height}` : '正在读取图片尺寸'}</div>
                {sourceLabel && <div className="mt-1 inline-flex rounded-full bg-blue-50 px-2 py-1 text-[11px] font-semibold text-blue-700 dark:bg-blue-500/10 dark:text-blue-200">来源：{sourceLabel}</div>}
              </div>
              <div className="flex flex-wrap gap-2">
                <button type="button" disabled={disabled} onClick={() => inputRef.current?.click()} className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-700 transition hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-white/[0.1] dark:text-gray-200 dark:hover:bg-white/[0.06]">替换图片</button>
                <button type="button" disabled={disabled} onClick={onRemove} className="rounded-lg px-3 py-1.5 text-xs font-medium text-red-600 transition hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50 dark:text-red-300 dark:hover:bg-red-400/10">删除图片</button>
              </div>
            </div>
          </div>
        ) : (
          <button type="button" disabled={disabled} onClick={() => inputRef.current?.click()} className="flex min-h-48 w-full flex-col items-center justify-center px-5 text-center disabled:cursor-not-allowed disabled:opacity-50">
            <svg className="h-8 w-8 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.7} d="M4 16l4-4a3 3 0 014 0l1 1 2-2a3 3 0 014 0l1 1M8 8h.01M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" /></svg>
            <span className="mt-3 text-sm font-semibold text-gray-700 dark:text-gray-200">点击或拖拽上传模特模板图</span>
            <span className="mt-1 text-xs text-gray-400">PNG、JPG、JPEG、WEBP</span>
          </button>
        )}
      </div>
      <input ref={inputRef} type="file" accept="image/png,image/jpeg,image/webp" className="hidden" onChange={(event) => { onUpload(Array.from(event.target.files || []).slice(0, 1)); event.target.value = '' }} />
    </section>
  )
}
