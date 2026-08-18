import { useRef, type DragEvent } from 'react'
import { useImagePaste } from '../hooks/useImagePaste'
import type {
  BatchTryOnFontReference,
  BatchTryOnGarment,
  BatchTryOnTemplate,
  BatchTryOnTemplateGarmentView,
} from '../types'
import { resolveEffectiveGarmentReferencePreviews } from '../lib/batchTryOnGarmentPreprocess'
import { BatchTryOnImage } from './BatchTryOnImage'

interface Props {
  template: BatchTryOnTemplate
  garment: BatchTryOnGarment
  fontReference?: BatchTryOnFontReference
  source: 'combination' | 'garment' | 'none'
  disabled?: boolean
  garmentViewDisabled?: boolean
  onSetGarmentDefault: (file: File) => void
  onSetCombinationOverride: (file: File) => void
  onClearGarmentDefault: () => void
  onClearCombinationOverride: () => void
  onGarmentViewChange: (view: BatchTryOnTemplateGarmentView) => void
  onView: (imageId: string) => void
}

const accept = 'image/png,image/jpeg,image/webp'

export default function BatchTryOnFontReferenceInputs({
  template, garment, fontReference, source, disabled, garmentViewDisabled,
  onSetGarmentDefault, onSetCombinationOverride,
  onClearGarmentDefault, onClearCombinationOverride, onGarmentViewChange, onView,
}: Props) {
  const garmentInput = useRef<HTMLInputElement>(null)
  const combinationInput = useRef<HTMLInputElement>(null)
  const pasteProps = useImagePaste({
    disabled: Boolean(disabled),
    maxFiles: 1,
    onPasteFiles: (files) => files[0] && onSetGarmentDefault(files[0]),
  })
  const drop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    if (!disabled && event.dataTransfer.files[0]) onSetGarmentDefault(event.dataTransfer.files[0])
  }
  const garmentReferences = resolveEffectiveGarmentReferencePreviews(template, garment)
  const hasTwoGarmentReferences = garmentReferences.length > 1
  const viewLabel = garmentReferences.map((item) => item.view === 'original' ? '原图回退' : `${VIEW_LABELS[item.view]}参考`).join(' + ')

  return (
    <div className="mt-3 rounded-xl border border-blue-100 bg-blue-50/40 p-3 dark:border-blue-400/15 dark:bg-blue-500/[0.04]">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="text-xs font-bold text-gray-800 dark:text-gray-100">Luna 与生图参考顺序</div>
          <div className="mt-1 text-[11px] leading-5 text-gray-500 dark:text-gray-400">图A固定模板构图；图B可切换为原图、正面或背面参考。这里的选择会同时用于 Luna 分析和最终生图。</div>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <label className="flex items-center gap-2 rounded-lg border border-blue-200 bg-white px-2 py-1.5 text-[11px] font-semibold text-gray-600 shadow-sm dark:border-blue-400/20 dark:bg-gray-900 dark:text-gray-200">
            <span>Luna 图B</span>
            <select
              value={template.garmentView || 'auto'}
              disabled={garmentViewDisabled}
              onChange={(event) => onGarmentViewChange(event.target.value as BatchTryOnTemplateGarmentView)}
              className="bg-transparent text-[11px] font-semibold text-blue-700 outline-none disabled:opacity-50 dark:text-blue-200"
              aria-label="Luna 图B服装参考"
            >
              <option value="auto">原始服装图</option>
              <option value="front">正面参考</option>
              <option value="back">背面参考</option>
              <option value="front_back">正面 + 背面</option>
              <option value="detail">细节参考</option>
            </select>
          </label>
          <span className={`rounded-full px-2 py-1 text-[11px] font-semibold shadow-sm ${garmentReferences.some((item) => !item.derived) && template.garmentView !== 'auto' ? 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-200' : 'bg-white text-blue-700 dark:bg-gray-900 dark:text-blue-200'}`}>当前：{viewLabel}</span>
          {source !== 'none' && <span className="rounded-full bg-white px-2 py-1 text-[11px] font-semibold text-blue-700 shadow-sm dark:bg-gray-900 dark:text-blue-200">字体：{source === 'combination' ? '当前组合覆盖' : '沿用服装默认'}</span>}
        </div>
      </div>

      <div className={`grid gap-3 md:grid-cols-2 ${hasTwoGarmentReferences ? 'xl:grid-cols-4' : 'xl:grid-cols-3'}`}>
        <ReferenceCard label="图A" title="当前模板图" imageId={template.imageId} serverAssetId={template.serverAssetId} fileName={template.displayName || template.fileName} onView={onView} />
        <ReferenceCard
          label="图B"
          title={garmentReferences[0].view === 'original' ? '当前服装原图（回退）' : `${VIEW_LABELS[garmentReferences[0].view]}服装参考`}
          imageId={garmentReferences[0].imageId}
          serverAssetId={garmentReferences[0].serverAssetId}
          fileName={garmentReferences[0].fileName}
          onView={onView}
        />
        {hasTwoGarmentReferences && !fontReference && <ReferenceCard label="图C" title="背面服装参考" imageId={garmentReferences[1].imageId} serverAssetId={garmentReferences[1].serverAssetId} fileName={garmentReferences[1].fileName} onView={onView} />}
        <div
          {...pasteProps}
          onDragOver={(event) => event.preventDefault()}
          onDrop={drop}
          className="rounded-xl border border-dashed border-gray-300 bg-white p-2 outline-none focus:ring-2 focus:ring-blue-500/20 dark:border-white/[0.12] dark:bg-gray-950"
        >
          <div className="flex items-center justify-between gap-2">
            <div><span className="text-[11px] font-bold text-blue-600">{fontReference ? '图C' : hasTwoGarmentReferences ? '可选' : '图C'}</span><span className="ml-1.5 text-xs font-semibold text-gray-700 dark:text-gray-200">定制字体参考图（可选）</span></div>
          </div>
          {fontReference ? (
            <button type="button" onClick={() => onView(fontReference.imageId)} className="mt-2 block aspect-[4/3] w-full overflow-hidden rounded-lg bg-gray-100 dark:bg-gray-900">
              <BatchTryOnImage imageId={fontReference.imageId} serverAssetId={fontReference.serverAssetId} alt="定制字体参考图" className="h-full w-full object-contain" />
            </button>
          ) : (
            <button type="button" disabled={disabled} onClick={() => garmentInput.current?.click()} className="mt-2 flex aspect-[4/3] w-full flex-col items-center justify-center rounded-lg bg-gray-50 px-3 text-center text-xs text-gray-400 disabled:opacity-50 dark:bg-white/[0.03]">
              <span className="text-xl">＋</span><span className="mt-1">上传、拖拽或粘贴图片</span>
            </button>
          )}
          <p className="mt-2 text-[11px] leading-5 text-gray-500 dark:text-gray-400">用于参考姓名、背号、肩号的字形和描边样式，不改变当前服装的颜色、图案和结构。</p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <button type="button" disabled={disabled} onClick={() => garmentInput.current?.click()} className="rounded-lg border border-gray-200 px-2 py-1.5 text-[11px] font-semibold text-gray-600 disabled:opacity-40 dark:border-white/[0.1] dark:text-gray-300">设为该服装默认</button>
            <button type="button" disabled={disabled} onClick={() => combinationInput.current?.click()} className="rounded-lg border border-blue-200 px-2 py-1.5 text-[11px] font-semibold text-blue-700 disabled:opacity-40 dark:border-blue-400/20 dark:text-blue-200">仅覆盖当前组合</button>
            {source === 'combination' && <button type="button" disabled={disabled} onClick={onClearCombinationOverride} className="rounded-lg px-2 py-1.5 text-[11px] font-semibold text-amber-700 disabled:opacity-40">取消组合覆盖</button>}
            {garment.fontReference && <button type="button" disabled={disabled} onClick={onClearGarmentDefault} className="rounded-lg px-2 py-1.5 text-[11px] font-semibold text-red-600 disabled:opacity-40">删除服装默认</button>}
          </div>
          <input ref={garmentInput} type="file" accept={accept} className="hidden" onChange={(event) => { const file = event.target.files?.[0]; if (file) onSetGarmentDefault(file); event.target.value = '' }} />
          <input ref={combinationInput} type="file" accept={accept} className="hidden" onChange={(event) => { const file = event.target.files?.[0]; if (file) onSetCombinationOverride(file); event.target.value = '' }} />
        </div>
        {hasTwoGarmentReferences && fontReference && <ReferenceCard label="图D" title="背面服装参考" imageId={garmentReferences[1].imageId} serverAssetId={garmentReferences[1].serverAssetId} fileName={garmentReferences[1].fileName} onView={onView} />}
      </div>
    </div>
  )
}

const VIEW_LABELS: Record<Exclude<BatchTryOnTemplateGarmentView, 'auto' | 'front_back'>, string> = {
  front: '正面',
  back: '背面',
  detail: '细节',
}

function ReferenceCard({ label, title, imageId, serverAssetId, fileName, onView }: {
  label: string
  title: string
  imageId: string
  serverAssetId?: string
  fileName: string
  onView: (imageId: string) => void
}) {
  return <div className="rounded-xl border border-gray-200 bg-white p-2 dark:border-white/[0.08] dark:bg-gray-950">
    <div><span className="text-[11px] font-bold text-blue-600">{label}</span><span className="ml-1.5 text-xs font-semibold text-gray-700 dark:text-gray-200">{title}</span></div>
    <button type="button" onClick={() => onView(imageId)} className="mt-2 block aspect-[4/3] w-full overflow-hidden rounded-lg bg-gray-100 dark:bg-gray-900">
      <BatchTryOnImage imageId={imageId} serverAssetId={serverAssetId} alt={title} className="h-full w-full object-contain" />
    </button>
    <div className="mt-2 truncate text-[11px] text-gray-500" title={fileName}>{fileName}</div>
  </div>
}
