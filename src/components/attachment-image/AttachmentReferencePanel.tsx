import { useRef, useState } from 'react'
import AuthenticatedImage from '../category-listing/AuthenticatedImage'
import { uploadAsset } from '../../lib/contentApi'
import type {
  AttachmentModuleReferenceState,
  AttachmentProductReferenceItem,
  AttachmentReferenceSlotType,
} from '../../lib/attachmentPlanningApi'

const slotCopy: Record<AttachmentReferenceSlotType, { label: string; description: string }> = {
  PRODUCT: { label: '商品图', description: '决定商品外观' },
  TEMPLATE: { label: '模板参考', description: '参考构图和摆放' },
  SCENE: { label: '场景参考', description: '参考氛围和环境' },
  PRINT: { label: '印花参考', description: '保持字形和图形' },
  OTHER: { label: '其他补充', description: '补充局部细节' },
}

const assetCategory: Record<AttachmentReferenceSlotType, Parameters<typeof uploadAsset>[1]> = {
  PRODUCT: 'product_reference', TEMPLATE: 'model_template', SCENE: 'style_reference',
  PRINT: 'print_asset', OTHER: 'style_reference',
}

interface Props {
  state: AttachmentModuleReferenceState
  productReferences: AttachmentProductReferenceItem[]
  busy?: boolean
  onAdd: (slot: AttachmentReferenceSlotType, assetId: string) => Promise<void>
  onRemove: (referenceId: string) => Promise<void>
  onAnalyze: () => Promise<void>
  onError: (message: string) => void
}

function summaryText(value: unknown) {
  return typeof value === 'object' && value !== null && 'summary' in value
    ? String((value as { summary?: unknown }).summary || '') : ''
}

export default function AttachmentReferencePanel({
  state, productReferences, busy = false, onAdd, onRemove, onAnalyze, onError,
}: Props) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [uploadSlot, setUploadSlot] = useState<AttachmentReferenceSlotType>('OTHER')
  const [uploading, setUploading] = useState(false)
  const [understandingOpen, setUnderstandingOpen] = useState(false)

  const pick = (slot: AttachmentReferenceSlotType) => {
    setUploadSlot(slot)
    fileRef.current?.click()
  }

  const upload = async (file: File) => {
    setUploading(true)
    try {
      const asset = await uploadAsset(file, assetCategory[uploadSlot])
      await onAdd(uploadSlot, asset.id)
    } catch (error) {
      onError(error instanceof Error ? error.message : '参考素材上传失败')
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const understanding = state.understanding
  const structured = understanding?.structured || {}
  return <section className="rounded-xl border border-gray-200 p-4 dark:border-white/[0.08]">
    <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={(event) => { const file = event.target.files?.[0]; if (file) void upload(file) }} />
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><h3 className="text-sm font-semibold text-gray-900 dark:text-white">参考素材</h3><p className="mt-1 text-xs text-gray-500">按用途组织；移除只解除当前模块引用，不会删除原始 Asset。</p></div>
      <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${state.reference_context_dirty ? 'bg-amber-50 text-amber-700' : 'bg-emerald-50 text-emerald-700'}`}>{state.reference_context_dirty ? '参考素材已更新' : understanding ? `理解 V${understanding.version_number}` : '等待分析'}</span>
    </div>
    <div className="mt-4 space-y-3">{state.slot_definitions.map((definition) => {
      const slot = definition.slot_type
      const explicit = state.references.filter((item) => item.slot_type === slot)
      const products = slot === 'PRODUCT' && !explicit.length ? productReferences : []
      const count = explicit.length || products.length
      return <div key={slot} className="rounded-xl bg-gray-50 p-3 dark:bg-white/[0.03]">
        <div className="flex items-center justify-between gap-3"><div><div className="text-xs font-semibold text-gray-800 dark:text-gray-100">{slotCopy[slot].label}{definition.required ? ' · 必需' : definition.recommended ? ' · 推荐' : ''}</div><div className="mt-0.5 text-[11px] text-gray-500">{slotCopy[slot].description} · {count}/{definition.max_items}</div></div><button type="button" disabled={busy || uploading || count >= definition.max_items} onClick={() => pick(slot)} className="rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-[11px] font-semibold text-blue-600 disabled:opacity-40 dark:border-white/[0.1] dark:bg-gray-950">{uploading && uploadSlot === slot ? '上传中…' : slot === 'PRODUCT' ? '本模块更换' : '添加'}</button></div>
        <div className="mt-2 flex min-h-16 gap-2 overflow-x-auto">
          {products.map((item) => <div key={item.id} className="relative w-16 shrink-0 overflow-hidden rounded-lg border border-gray-200 bg-white dark:border-white/[0.08]"><AuthenticatedImage url={item.asset.url} alt={item.asset.filename} className="aspect-square w-full object-contain" placeholderClassName="aspect-square" /><span className="absolute bottom-0 inset-x-0 bg-gray-950/65 py-0.5 text-center text-[9px] text-white">{item.view_role === 'front' ? '正面' : item.view_role === 'back' ? '背面' : '细节'}</span></div>)}
          {explicit.map((item) => <div key={item.id} className="group relative w-16 shrink-0 overflow-hidden rounded-lg border border-gray-200 bg-white dark:border-white/[0.08]"><AuthenticatedImage url={item.asset.url} alt={item.asset.filename} className="aspect-square w-full object-contain" placeholderClassName="aspect-square" /><button type="button" aria-label="移除参考图" disabled={busy} onClick={() => void onRemove(item.id)} className="absolute right-1 top-1 rounded-full bg-gray-950/75 px-1.5 py-0.5 text-[10px] text-white opacity-0 transition group-hover:opacity-100">×</button></div>)}
          {!count && <div className="flex min-h-16 flex-1 items-center justify-center rounded-lg border border-dashed border-gray-200 text-[11px] text-gray-400 dark:border-white/[0.08]">暂无{slotCopy[slot].label}</div>}
        </div>
      </div>
    })}</div>
    <div className="mt-4 flex flex-wrap items-center gap-2">
      <button type="button" disabled={busy || uploading || Boolean(state.reference_analysis_job_id)} onClick={() => void onAnalyze()} className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-xs font-semibold text-blue-700 disabled:opacity-40">{state.reference_analysis_job_id ? '参考素材分析中…' : understanding ? '重新分析参考素材' : '分析参考素材'}</button>
      {understanding && <button type="button" onClick={() => setUnderstandingOpen((value) => !value)} className="rounded-lg border border-gray-200 px-3 py-2 text-xs font-semibold text-gray-600 dark:border-white/[0.1] dark:text-gray-300">{understandingOpen ? '收起理解摘要' : '参考图理解摘要'}</button>}
      {understanding?.status === 'failed' && <span className="text-xs text-red-600">{understanding.error_message || '参考素材分析失败，可重试'}</span>}
    </div>
    {understandingOpen && understanding && <div className="mt-3 space-y-2 rounded-xl bg-blue-50/60 p-3 text-xs leading-5 text-gray-700 dark:bg-blue-500/5 dark:text-gray-200">
      <div className="font-semibold">Reference Understanding V{understanding.version_number}</div>
      {(['product', 'template', 'scene', 'print', 'other'] as const).map((key) => summaryText(structured[key]) ? <div key={key}><span className="font-semibold uppercase text-blue-700">{key}</span> · {summaryText(structured[key])}</div> : null)}
      <div className="border-t border-blue-100 pt-2 dark:border-blue-400/10">{String(structured.combined_summary_cn || '暂无综合摘要')}</div>
    </div>}
  </section>
}
