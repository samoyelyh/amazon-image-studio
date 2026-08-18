import { useRef, type DragEvent } from 'react'
import { useImagePaste } from '../hooks/useImagePaste'
import type { BatchTryOnFontReference } from '../types'
import { BatchTryOnImage } from './BatchTryOnImage'

interface Props {
  garmentName: string
  reference?: BatchTryOnFontReference
  disabled?: boolean
  onUpload: (file: File) => void
  onRemove: () => void
  onView: (imageId: string) => void
}

export default function BatchTryOnGarmentFontReference({
  garmentName, reference, disabled, onUpload, onRemove, onView,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  const pasteProps = useImagePaste({
    disabled: Boolean(disabled), maxFiles: 1,
    onPasteFiles: (files) => files[0] && onUpload(files[0]),
  })
  const receiveDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    event.stopPropagation()
    if (!disabled && event.dataTransfer.files[0]) onUpload(event.dataTransfer.files[0])
  }

  return <div
    {...pasteProps}
    onDragOver={(event) => { event.preventDefault(); event.stopPropagation() }}
    onDrop={receiveDrop}
    className="group relative h-14 w-14 shrink-0 rounded-lg border border-dashed border-blue-200 bg-blue-50/50 outline-none focus:ring-2 focus:ring-blue-500/20 dark:border-blue-400/20 dark:bg-blue-500/[0.06]"
    title={reference ? `字体参考：${reference.fileName}` : `为 ${garmentName} 添加字体参考图`}
  >
    {reference ? <>
      <button type="button" onClick={() => onView(reference.imageId)} className="h-full w-full overflow-hidden rounded-lg">
        <BatchTryOnImage imageId={reference.imageId} alt={`${garmentName} 字体参考`} className="h-full w-full object-contain" />
      </button>
      <button type="button" disabled={disabled} onClick={() => inputRef.current?.click()} className="absolute inset-x-0 bottom-0 bg-gray-950/70 py-0.5 text-[9px] font-semibold text-white opacity-0 transition group-hover:opacity-100 disabled:hidden">替换</button>
      <button type="button" disabled={disabled} onClick={onRemove} aria-label={`删除 ${garmentName} 的字体参考图`} className="absolute -right-1.5 -top-1.5 flex h-5 w-5 items-center justify-center rounded-full bg-white text-xs font-bold text-red-600 shadow opacity-0 transition group-hover:opacity-100 disabled:hidden dark:bg-gray-900">×</button>
    </> : <button type="button" disabled={disabled} onClick={() => inputRef.current?.click()} className="flex h-full w-full flex-col items-center justify-center text-blue-600 disabled:opacity-40">
      <span className="text-lg leading-none">＋</span><span className="mt-0.5 text-[9px] font-semibold">字体图</span>
    </button>}
    <input ref={inputRef} type="file" accept="image/png,image/jpeg,image/webp" className="hidden" onChange={(event) => { const file = event.target.files?.[0]; if (file) onUpload(file); event.target.value = '' }} />
  </div>
}
