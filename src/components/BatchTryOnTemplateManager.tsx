import { useRef, useState, type DragEvent } from 'react'
import { useImagePaste } from '../hooks/useImagePaste'
import type { BatchTryOnTemplate } from '../types'
import type { BatchTryOnPromptPreset, BatchTryOnTemplateType } from '../lib/batchTryOnWorkflowApi'
import { BatchTryOnImage } from './BatchTryOnImage'

interface Props {
  templates: BatchTryOnTemplate[]
  maxItems: number
  disabled?: boolean
  detailMode?: boolean
  combinationMode?: 'cartesian' | 'one_to_one'
  promptPresets: BatchTryOnPromptPreset[]
  promptPresetIds: Record<string, string | undefined>
  generateAllCount?: number
  generateAllDisabledReason?: string
  referenceWarnings?: Record<string, string | undefined>
  onUpload: (files: File[]) => void
  onRemove: (template: BatchTryOnTemplate) => void
  onPromptPresetChange: (templateId: string, presetId: string) => void
  onGenerateAllValidations?: () => void
  onSetDefault: (templateId: string) => void
  onToggle: (templateId: string) => void
  onToggleAll: (selected: boolean) => void
  onView: (imageId: string) => void
  onDetailChange?: (templateId: string, patch: Pick<BatchTryOnTemplate, 'focusArea' | 'detailPriority'>) => void
  onGarmentViewChange?: (templateId: string, garmentView: NonNullable<BatchTryOnTemplate['garmentView']>) => void
  onPromptStrategyChange?: (templateId: string, strategy: NonNullable<BatchTryOnTemplate['promptStrategy']>) => void
  onGenerateValidation?: (templateId: string) => void
  onReviewValidation?: (templateId: string) => void
}

export default function BatchTryOnTemplateManager({
  templates, maxItems, disabled, promptPresets, promptPresetIds, generateAllCount = 0, generateAllDisabledReason,
  referenceWarnings = {},
  onUpload, onRemove, onPromptPresetChange, onGenerateAllValidations, onSetDefault,
  onToggle, onToggleAll, onView, detailMode, combinationMode = 'cartesian', onDetailChange, onGarmentViewChange,
  onPromptStrategyChange, onGenerateValidation, onReviewValidation,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const full = templates.length >= maxItems
  const selectedCount = templates.filter((item) => item.selected).length
  const pasteZoneProps = useImagePaste({
    disabled: Boolean(disabled || full),
    maxFiles: Math.max(0, maxItems - templates.length),
    onPasteFiles: onUpload,
  })

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
          <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
            {combinationMode === 'one_to_one'
              ? '按当前已选列表顺序，将第 1 个模板与第 1 件服装依次一一配对。'
              : '可多选模板，与选中的服装生成笛卡尔组合。'}
          </p>
        </div>
        <span className="rounded-full bg-gray-100 px-2.5 py-1 text-xs font-semibold text-gray-600 dark:bg-white/[0.07] dark:text-gray-300">已选 {selectedCount} / 共 {templates.length}</span>
      </div>

      <div
        {...pasteZoneProps}
        onDragEnter={(event) => { event.preventDefault(); if (!disabled && !full) setDragging(true) }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={() => setDragging(false)}
        onDrop={receiveDrop}
        className={`mt-3 rounded-xl border border-dashed p-3 outline-none transition focus:ring-2 focus:ring-blue-500/20 ${dragging ? 'border-blue-400 bg-blue-50 dark:bg-blue-500/10' : 'border-gray-300 bg-gray-50 dark:border-white/[0.12] dark:bg-white/[0.03]'}`}
      >
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" disabled={disabled || full} onClick={() => inputRef.current?.click()} className="h-9 rounded-lg bg-gray-900 px-3 text-xs font-semibold text-white disabled:opacity-40 dark:bg-white dark:text-gray-950">上传模板图</button>
          <button
            type="button"
            disabled={disabled || Boolean(generateAllDisabledReason) || !onGenerateAllValidations}
            title={generateAllDisabledReason || `并行生成 ${generateAllCount} 张待验证样图`}
            onClick={onGenerateAllValidations}
            className="h-9 rounded-lg bg-blue-600 px-3 text-xs font-semibold text-white transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:bg-gray-300 dark:disabled:bg-white/[0.12]"
          >一键生成样图{generateAllCount > 0 ? `（${generateAllCount}）` : ''}</button>
          {templates.length > 0 && <>
            <button type="button" disabled={disabled || selectedCount === templates.length} onClick={() => onToggleAll(true)} className="h-9 rounded-lg border border-gray-200 px-3 text-xs font-semibold dark:border-white/[0.1]">全选模板</button>
            <button type="button" disabled={disabled || selectedCount === 0} onClick={() => onToggleAll(false)} className="h-9 rounded-lg border border-gray-200 px-3 text-xs font-semibold dark:border-white/[0.1]">取消全选</button>
          </>}
        </div>
        <div className="mt-2 text-xs text-gray-400">支持多选、拖拽或点击此区域后 Ctrl/⌘+V 粘贴 PNG、JPG、JPEG、WEBP，最多 {maxItems} 张。</div>
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
              <div className="mt-2 truncate text-xs font-semibold text-gray-800 dark:text-gray-100" title={template.displayName}>{template.displayName}</div>
              <div className="mt-1 truncate text-[11px] text-gray-400" title={template.fileName}>{template.fileName}</div>
              <label className="mt-2 block">
                <span className="mb-1 block text-[11px] font-medium text-gray-500">提示词预设</span>
                <select
                  value={promptPresetIds[template.id] || ''}
                  disabled={disabled || template.validationStatus === 'generating'}
                  onChange={(event) => onPromptPresetChange(template.id, event.target.value)}
                  className="h-8 w-full rounded-lg border border-gray-200 bg-white px-2 text-xs font-semibold outline-none focus:border-blue-400 disabled:bg-gray-100 disabled:text-gray-400 dark:border-white/[0.1] dark:bg-gray-950 dark:disabled:bg-white/[0.04]"
                  aria-label={`${template.displayName} 提示词预设`}
                  title={template.validationStatus === 'generating' ? '当前样图已使用提交时的提示词快照；其他模板仍可继续配置。' : '选择该模板生成样图和正式批量时使用的提示词预设'}
                >
                  <option value="" disabled>请选择提示词预设</option>
                  {Object.entries(TEMPLATE_TYPE_LABELS).map(([templateType, label]) => {
                    const options = promptPresets.filter((preset) => preset.enabled && preset.template_type === templateType)
                    return options.length ? <optgroup key={templateType} label={label}>
                      {options.map((preset) => <option key={preset.id} value={preset.id}>
                        {preset.label}{preset.is_system_preset ? '（系统）' : preset.scope === 'organization' ? '（团队）' : '（个人）'}
                      </option>)}
                    </optgroup> : null
                  })}
                </select>
                {template.validationStatus === 'generating' && <span className="mt-1 block text-[10px] text-blue-600 dark:text-blue-300">当前样图使用已提交快照</span>}
              </label>
              <label className="mt-2 block">
                <span className="mb-1 block text-[11px] font-medium text-gray-500">生成模型选择</span>
                <select value={template.promptStrategy || 'luna_per_image'} disabled={disabled} onChange={(event) => onPromptStrategyChange?.(template.id, event.target.value as NonNullable<BatchTryOnTemplate['promptStrategy']>)} className="h-8 w-full rounded-lg border border-gray-200 bg-white px-2 text-xs font-semibold dark:border-white/[0.1] dark:bg-gray-950">
                  <option value="luna_per_image">Luna 精细逐图 · 默认</option>
                  <option value="ai_optimize">AI 分析优化</option>
                  <option value="preset">直接使用预设 · 最快</option>
                </select>
              </label>
              <select value={template.garmentView || 'auto'} disabled={disabled} onChange={(event) => onGarmentViewChange?.(template.id, event.target.value as NonNullable<BatchTryOnTemplate['garmentView']>)} className="mt-2 h-8 w-full rounded-lg border border-gray-200 bg-white px-2 text-xs dark:border-white/[0.1] dark:bg-gray-950" aria-label={`${template.displayName} 服装参考视图`}>
                <option value="auto">参考视图：自动（原图）</option><option value="front">正面参考</option><option value="back">背面参考</option><option value="front_back">正面 + 背面</option><option value="detail">细节参考</option>
              </select>
              {referenceWarnings[template.id] && <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-2 py-1.5 text-[11px] leading-4 text-amber-800 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-200">
                {referenceWarnings[template.id]}
              </div>}
              {combinationMode === 'one_to_one' && template.selected && <div className="mt-1 text-[11px] font-semibold text-blue-600 dark:text-blue-300">配对顺序 {templates.filter((item) => item.selected).findIndex((item) => item.id === template.id) + 1}</div>}
              {detailMode && <div className="mt-2 grid gap-2">
                <select
                  value={template.focusArea || 'garment_detail'}
                  disabled={disabled}
                  onChange={(event) => onDetailChange?.(template.id, { focusArea: event.target.value, detailPriority: template.detailPriority })}
                  className="h-8 rounded-lg border border-gray-200 bg-white px-2 text-xs outline-none focus:border-blue-400 dark:border-white/[0.1] dark:bg-gray-950"
                  aria-label={`${template.displayName} 细节区域`}
                >
                  <option value="garment_detail">服装细节</option>
                  <option value="neckline">领口</option>
                  <option value="chest_text">胸前文字</option>
                  <option value="chest_number">胸前号码</option>
                  <option value="wearer_left_sleeve">穿着者左袖</option>
                  <option value="wearer_right_sleeve">穿着者右袖</option>
                  <option value="cuff">袖口</option>
                  <option value="shoulder">肩部</option>
                  <option value="fabric">面料</option>
                  <option value="graphic">图案</option>
                </select>
                <input
                  value={template.detailPriority || ''}
                  disabled={disabled}
                  maxLength={500}
                  onChange={(event) => onDetailChange?.(template.id, { focusArea: template.focusArea || 'garment_detail', detailPriority: event.target.value })}
                  placeholder="细节优先要求（可选）"
                  className="h-8 rounded-lg border border-gray-200 bg-white px-2 text-xs outline-none focus:border-blue-400 dark:border-white/[0.1] dark:bg-gray-950"
                />
              </div>}
            </div>
          </div>
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
            <button type="button" disabled={disabled || template.isDefault} onClick={() => onSetDefault(template.id)} className={`rounded-md px-2 py-1 text-[11px] font-semibold ${template.isDefault ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-200' : 'border border-gray-200 dark:border-white/[0.1]'}`}>{template.isDefault ? '默认模板' : '设为默认'}</button>
            <button type="button" disabled={disabled} onClick={() => onRemove(template)} className="rounded-md px-2 py-1 text-[11px] font-semibold text-red-600 disabled:opacity-40">删除模板</button>
          </div>
          {template.selected && <div className="mt-2 flex items-center justify-between rounded-lg bg-gray-50 px-2.5 py-2 text-[11px] dark:bg-white/[0.04]">
            <span className={template.validationStatus === 'approved' ? 'font-semibold text-emerald-600' : template.validationStatus === 'pending_review' ? 'font-semibold text-amber-600' : template.validationStatus === 'generating' ? 'font-semibold text-blue-600' : 'text-gray-500'}>
              {template.validationStatus === 'approved' ? '✓ 已验证' : template.validationStatus === 'pending_review' ? '● 待确认' : template.validationStatus === 'generating' ? '● 样图生成中' : template.validationStatus === 'rejected' || template.validationStatus === 'needs_revalidation' ? '● 需要重新验证' : '● 待生成样图'}
            </span>
            {template.validationStatus === 'pending_review'
              ? <button type="button" onClick={() => onReviewValidation?.(template.id)} className="font-semibold text-blue-600">查看样图</button>
              : <button type="button" disabled={disabled || template.validationStatus === 'generating'} onClick={() => onGenerateValidation?.(template.id)} className="font-semibold text-blue-600 disabled:opacity-40">{template.validationStatus === 'approved' ? '重新验证' : '生成样图'}</button>}
          </div>}
        </article>)}
      </div> : <div className="mt-3 rounded-xl border border-dashed border-gray-200 px-4 py-10 text-center text-xs text-gray-400 dark:border-white/[0.08]">尚未上传模板图</div>}
      <input ref={inputRef} type="file" multiple accept="image/png,image/jpeg,image/webp" className="hidden" onChange={(event) => { onUpload(Array.from(event.target.files || [])); event.target.value = '' }} />
    </section>
  )
}

const TEMPLATE_TYPE_LABELS: Record<BatchTryOnTemplateType, string> = {
  pure_white: '纯白底图',
  gift_scene: '礼品场景图',
  stadium_scene: '观赛场景图',
  detail_display: '细节展示图',
  casual_scene: '休闲场景图',
  custom_process: '定制信息流程图',
}
