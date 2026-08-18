import { useEffect, useMemo, useRef, useState } from 'react'
import type { BatchTryOnFontReference, BatchTryOnGarment, BatchTryOnTemplate, BatchTryOnTemplateGarmentView } from '../types'
import type {
  BatchTryOnPromptPreset,
  BatchTryOnPromptMode,
  BatchTryOnTemplatePrompt,
  BatchTryOnTemplateType,
} from '../lib/batchTryOnWorkflowApi'
import { syncBatchTryOnPromptDrafts } from '../lib/batchTryOnPromptDrafts'
import { resolveBatchTryOnFontReference } from '../lib/batchTryOnFontReferences'
import { resolveEffectiveGarmentReferencePreviews } from '../lib/batchTryOnGarmentPreprocess'
import BatchTryOnFontReferenceInputs from './BatchTryOnFontReferenceInputs'

interface Props {
  templates: BatchTryOnTemplate[]
  garments: BatchTryOnGarment[]
  fontReferenceOverrides?: Record<string, BatchTryOnFontReference>
  presets: BatchTryOnPromptPreset[]
  promptMode: BatchTryOnPromptMode
  onPromptModeChange: (mode: BatchTryOnPromptMode) => void
  templateConfigs: Record<string, TemplatePromptDraftConfig>
  records: BatchTryOnTemplatePrompt[]
  status?: string | null
  busy: boolean
  workflowReady: boolean
  canManageSystemPresets: boolean
  onManageSystemPresets: () => void
  onTemplateConfigChange: (templateId: string, patch: Partial<TemplatePromptDraftConfig>) => void
  onAnalyzeCurrentTemplate: (templateId: string) => Promise<void>
  onReanalyze: (record: BatchTryOnTemplatePrompt, analysisPrompt: string) => Promise<void>
  onConfirm: (record: BatchTryOnTemplatePrompt, finalPrompt: string) => Promise<void>
  onSubmit: () => Promise<void>
  onSaveAsPersonalPreset: (templateId: string) => Promise<void>
  onSetGarmentFontReference: (garmentId: string, file: File) => void
  onSetCombinationFontReference: (templateId: string, garmentId: string, file: File) => void
  onClearGarmentFontReference: (garmentId: string) => void
  onClearCombinationFontReference: (templateId: string, garmentId: string) => void
  onGarmentViewChange: (templateId: string, view: BatchTryOnTemplateGarmentView) => void
  onViewImage: (imageId: string) => void
}

export interface TemplatePromptDraftConfig {
  templateType: BatchTryOnTemplateType
  presetId: string
  analysisPrompt: string
}

export default function BatchTryOnPromptTemplatePanel({
  templates,
  garments,
  fontReferenceOverrides,
  presets,
  promptMode,
  onPromptModeChange,
  templateConfigs,
  records,
  status,
  busy,
  workflowReady,
  canManageSystemPresets,
  onManageSystemPresets,
  onTemplateConfigChange,
  onAnalyzeCurrentTemplate,
  onReanalyze,
  onConfirm,
  onSubmit,
  onSaveAsPersonalPreset,
  onSetGarmentFontReference,
  onSetCombinationFontReference,
  onClearGarmentFontReference,
  onClearCombinationFontReference,
  onGarmentViewChange,
  onViewImage,
}: Props) {
  const [expanded, setExpanded] = useState(true)
  const [activeTemplateId, setActiveTemplateId] = useState(templates[0]?.id || '')
  const [activeGarmentId, setActiveGarmentId] = useState(garments[0]?.id || '')
  const [finalDrafts, setFinalDrafts] = useState<Record<string, string>>({})
  const [showAnalysisEditor, setShowAnalysisEditor] = useState(true)
  const lastServerPromptsRef = useRef<Record<string, string>>({})
  const activeTemplate = templates.find((template) => template.id === activeTemplateId) || templates[0]
  const activeGarment = garments.find((garment) => garment.id === activeGarmentId) || garments[0]
  const activeTemplateHasRecord = Boolean(activeTemplate && records.some((record) => (
    record.template_id === activeTemplate.id
    || (activeTemplate.serverAssetId && record.template_asset_id === activeTemplate.serverAssetId)
  )))
  const activeConfig = activeTemplate ? templateConfigs[activeTemplate.id] : undefined
  const availablePresets = useMemo(() => presets.filter(
    (preset) => preset.template_type === activeConfig?.templateType && preset.enabled,
  ), [activeConfig?.templateType, presets])

  useEffect(() => {
    if (!templates.length) {
      setActiveTemplateId('')
      return
    }
    if (!templates.some((template) => template.id === activeTemplateId)) setActiveTemplateId(templates[0].id)
  }, [activeTemplateId, templates])

  useEffect(() => {
    if (!garments.length) {
      setActiveGarmentId('')
      return
    }
    if (!garments.some((garment) => garment.id === activeGarmentId)) setActiveGarmentId(garments[0].id)
  }, [activeGarmentId, garments])

  useEffect(() => {
    setFinalDrafts((current) => {
      const synchronized = syncBatchTryOnPromptDrafts(current, lastServerPromptsRef.current, records)
      lastServerPromptsRef.current = synchronized.serverPrompts
      return synchronized.drafts
    })
  }, [records])

  useEffect(() => {
    if (promptMode === 'direct') setShowAnalysisEditor(true)
    else if (records.length > 0) setShowAnalysisEditor(false)
  }, [promptMode, records.length])

  useEffect(() => {
    if (activeTemplate && !activeTemplateHasRecord) setShowAnalysisEditor(true)
  }, [activeTemplate?.id, activeTemplateHasRecord])

  const allEffective = records.length > 0 && records.every((record) => record.prompt_status === 'effective')
  const completed = records.filter((record) => ['ready', 'effective'].includes(record.prompt_status)).length
  const selectedGarmentCount = garments.filter((garment) => garment.selected).length

  return (
    <section className="mt-4 overflow-hidden rounded-2xl border border-blue-100 bg-white shadow-sm dark:border-blue-400/15 dark:bg-gray-950">
      <div className="flex w-full items-center justify-between gap-4 px-4 py-4 text-left">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-bold text-gray-900 dark:text-gray-100">批量换衣提示词</h3>
            <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[11px] font-semibold text-blue-700 dark:bg-blue-500/10 dark:text-blue-200">
              {promptMode === 'direct' ? '直接使用预设' : promptMode === 'ai_detailed' ? 'Luna 逐图精细分析' : 'AI 模板分析'} · 6 类已启用
            </span>
            {records.length > 0 && (
              <span className="text-xs text-gray-400">已完成 {completed}/{records.length}</span>
            )}
          </div>
          <p className="mt-1 text-xs leading-5 text-gray-500 dark:text-gray-400">
            {promptMode === 'direct'
              ? '每个模板独立设置最终提示词；生成组合时直接使用当前输入，不调用 AI 分析。'
              : promptMode === 'ai_detailed'
                ? '使用 GPT-5.6 Luna 对每个“模板 × 服装”组合分别进行视觉分析，生成逐图专用提示词。'
                : '使用模板图、首件服装和当前分析指令生成模板级提示词，确认后供同模板服装复用。'}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {canManageSystemPresets && <button type="button" onClick={onManageSystemPresets} className="h-8 rounded-lg border border-blue-200 bg-blue-50 px-3 text-xs font-semibold text-blue-700 transition hover:bg-blue-100 dark:border-blue-400/20 dark:bg-blue-500/10 dark:text-blue-200">管理系统预设</button>}
          <button type="button" onClick={() => setExpanded((value) => !value)} className="h-8 rounded-lg px-2 text-xs font-semibold text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-500/10">{expanded ? '收起' : '展开'}</button>
        </div>
      </div>

      {expanded && (
        <div className="border-t border-gray-100 p-4 dark:border-white/[0.06]">
          <div className="mb-3 rounded-xl border border-gray-200 bg-gray-50 p-1 dark:border-white/[0.08] dark:bg-white/[0.025]">
            <div className="grid grid-cols-3 gap-1">
              <button
                type="button"
                disabled={busy || workflowReady}
                onClick={() => onPromptModeChange('direct')}
                className={`rounded-lg px-3 py-2 text-xs font-semibold transition ${promptMode === 'direct' ? 'bg-white text-blue-700 shadow-sm dark:bg-gray-900 dark:text-blue-300' : 'text-gray-500'}`}
              >
                直接使用预设
              </button>
              <button
                type="button"
                disabled={busy || workflowReady}
                onClick={() => onPromptModeChange('ai_analysis')}
                className={`rounded-lg px-3 py-2 text-xs font-semibold transition ${promptMode === 'ai_analysis' ? 'bg-white text-blue-700 shadow-sm dark:bg-gray-900 dark:text-blue-300' : 'text-gray-500'}`}
              >
                AI 分析优化
              </button>
              <button
                type="button"
                disabled={busy || workflowReady}
                onClick={() => onPromptModeChange('ai_detailed')}
                className={`rounded-lg px-3 py-2 text-xs font-semibold transition ${promptMode === 'ai_detailed' ? 'bg-white text-blue-700 shadow-sm dark:bg-gray-900 dark:text-blue-300' : 'text-gray-500'}`}
              >
                Luna 精细逐图
              </button>
            </div>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <label className="block">
              <span className="mb-1.5 block text-xs font-semibold text-gray-600 dark:text-gray-300">当前配置模板</span>
              <select
                value={activeTemplate?.id || ''}
                disabled={busy || workflowReady}
                onChange={(event) => setActiveTemplateId(event.target.value)}
                className="h-10 w-full rounded-xl border border-gray-200 bg-white px-3 text-sm text-gray-800 outline-none focus:border-blue-400 disabled:bg-gray-50 dark:border-white/[0.08] dark:bg-gray-900 dark:text-gray-100"
              >
                {templates.map((template, index) => <option key={template.id} value={template.id}>{index + 1}. {template.displayName || template.fileName}</option>)}
              </select>
            </label>
            <label className="block">
              <span className="mb-1.5 block text-xs font-semibold text-gray-600 dark:text-gray-300">当前服装</span>
              <select
                value={activeGarment?.id || ''}
                disabled={busy || workflowReady}
                onChange={(event) => setActiveGarmentId(event.target.value)}
                className="h-10 w-full rounded-xl border border-gray-200 bg-white px-3 text-sm text-gray-800 outline-none focus:border-blue-400 disabled:bg-gray-50 dark:border-white/[0.08] dark:bg-gray-900 dark:text-gray-100"
              >
                {garments.map((garment, index) => <option key={garment.id} value={garment.id}>{index + 1}. {garment.garmentFileName}</option>)}
              </select>
            </label>
            <label className="block">
              <span className="mb-1.5 block text-xs font-semibold text-gray-600 dark:text-gray-300">模板类型</span>
              <select
                value={activeConfig?.templateType || 'pure_white'}
                disabled={busy || workflowReady}
                onChange={(event) => {
                  if (!activeTemplate) return
                  const templateType = event.target.value as BatchTryOnTemplateType
                  const preset = presets.find((item) => item.template_type === templateType && item.enabled)
                  onTemplateConfigChange(activeTemplate.id, {
                    templateType,
                    presetId: preset?.id || '',
                    analysisPrompt: preset?.analysis_prompt_template || '',
                  })
                }}
                className="h-10 w-full rounded-xl border border-gray-200 bg-white px-3 text-sm text-gray-800 outline-none focus:border-blue-400 disabled:bg-gray-50 dark:border-white/[0.08] dark:bg-gray-900 dark:text-gray-100"
              >
                {Object.entries(TEMPLATE_TYPE_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="mb-1.5 flex items-center justify-between gap-2 text-xs font-semibold text-gray-600 dark:text-gray-300">
                <span>{promptMode === 'direct' ? '提示词预设' : 'AI 分析预设'}</span>
                <button
                  type="button"
                  disabled={busy || workflowReady || !activeConfig?.presetId}
                  onClick={() => {
                    if (!activeTemplate) return
                    const preset = presets.find((item) => item.id === activeConfig?.presetId)
                    if (preset) onTemplateConfigChange(activeTemplate.id, { analysisPrompt: preset.analysis_prompt_template })
                  }}
                  className="text-[11px] font-semibold text-blue-600 disabled:opacity-40"
                >重新加载预设</button>
              </span>
              <select
                value={activeConfig?.presetId || ''}
                disabled={busy || workflowReady}
                onChange={(event) => {
                  if (!activeTemplate) return
                  const preset = presets.find((item) => item.id === event.target.value)
                  onTemplateConfigChange(activeTemplate.id, {
                    presetId: event.target.value,
                    analysisPrompt: preset?.analysis_prompt_template || activeConfig?.analysisPrompt || '',
                  })
                }}
                className="h-10 w-full rounded-xl border border-gray-200 bg-white px-3 text-sm text-gray-800 outline-none focus:border-blue-400 dark:border-white/[0.08] dark:bg-gray-900 dark:text-gray-100"
              >
                {availablePresets.map((preset) => (
                  <option key={preset.id} value={preset.id}>{preset.label}{preset.is_system_preset ? '（系统）' : '（个人）'}</option>
                ))}
              </select>
            </label>
          </div>

          {activeTemplate && activeGarment && (() => {
            const resolved = resolveBatchTryOnFontReference(activeTemplate.id, activeGarment, fontReferenceOverrides)
            return <BatchTryOnFontReferenceInputs
              template={activeTemplate}
              garment={activeGarment}
              fontReference={resolved.reference}
              source={resolved.source}
              disabled={busy || workflowReady}
              garmentViewDisabled={busy}
              onSetGarmentDefault={(file) => onSetGarmentFontReference(activeGarment.id, file)}
              onSetCombinationOverride={(file) => onSetCombinationFontReference(activeTemplate.id, activeGarment.id, file)}
              onClearGarmentDefault={() => onClearGarmentFontReference(activeGarment.id)}
              onClearCombinationOverride={() => onClearCombinationFontReference(activeTemplate.id, activeGarment.id)}
              onGarmentViewChange={(view) => onGarmentViewChange(activeTemplate.id, view)}
              onView={onViewImage}
            />
          })()}

          <div className="mt-3 rounded-xl border border-gray-200 bg-gray-50/60 p-3 dark:border-white/[0.08] dark:bg-white/[0.025]">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <div className="text-xs font-bold text-gray-700 dark:text-gray-200">{promptMode === 'direct' ? '最终换衣提示词' : 'AI 分析指令'}</div>
                <div className="mt-1 text-[11px] text-gray-400">
                  {promptMode === 'direct'
                    ? '这里的内容会直接用于当前模板下的全部服装；可以选择预设后继续编辑。'
                    : promptMode === 'ai_detailed'
                      ? `同一分析指令会分别结合每个组合的模板图和服装图，由 GPT-5.6 Luna 生成 ${templates.length * garments.length} 份逐图提示词。`
                      : 'AI 将结合当前模板图和本批首件服装生成最终换衣提示词；第 2 件以后不重复分析。'}
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {promptMode !== 'direct' && records.length > 0 && <button type="button" onClick={() => setShowAnalysisEditor((value) => !value)} className="text-xs font-semibold text-gray-500 dark:text-gray-300">
                  {showAnalysisEditor ? '收起分析要求' : '展开分析要求'}
                </button>}
                <button type="button" disabled={!activeConfig?.analysisPrompt.trim() || busy || !activeTemplate} onClick={() => activeTemplate && void onSaveAsPersonalPreset(activeTemplate.id)} className="text-xs font-semibold text-blue-600 disabled:opacity-40">另存为个人预设</button>
                {promptMode !== 'direct' && <button
                  type="button"
                  disabled={!activeTemplate || !activeConfig?.analysisPrompt.trim() || selectedGarmentCount === 0 || busy}
                  title={selectedGarmentCount === 0 ? '请至少选择一件服装' : '为当前下拉框中的模板创建新的独立分析工作流'}
                  onClick={() => activeTemplate && void onAnalyzeCurrentTemplate(activeTemplate.id)}
                  className="h-8 rounded-lg bg-blue-600 px-3 text-xs font-semibold text-white transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:bg-gray-300 dark:disabled:bg-white/[0.12]"
                >{busy ? '分析中…' : '分析当前模板'}</button>}
              </div>
            </div>
            {(promptMode === 'direct' || showAnalysisEditor) && <textarea
              value={activeConfig?.analysisPrompt || ''}
              disabled={busy || workflowReady}
              onChange={(event) => activeTemplate && onTemplateConfigChange(activeTemplate.id, { analysisPrompt: event.target.value })}
              rows={9}
              className="mt-3 w-full resize-y rounded-xl border border-gray-200 bg-white px-3 py-2.5 text-xs leading-5 text-gray-700 outline-none focus:border-blue-400 disabled:bg-gray-100 dark:border-white/[0.08] dark:bg-gray-950 dark:text-gray-200 dark:disabled:bg-white/[0.03]"
            />}
            {!records.length && (
              <div className="mt-3 rounded-lg bg-blue-50 px-3 py-2 text-xs text-blue-700 dark:bg-blue-500/10 dark:text-blue-200">
                {promptMode === 'direct'
                  ? `已配置 ${templates.length} 个模板。点击页面中的“生成组合”后，系统会直接保存这些提示词快照并提交图片任务。`
                  : promptMode === 'ai_detailed'
                    ? `点击“分析当前模板”，将为当前模板与 ${selectedGarmentCount} 件已选服装创建 Luna 逐图分析任务。`
                    : `点击“分析当前模板”，将使用当前模板与首件已选服装创建一次 AI Prompt Analysis。`}
              </div>
            )}
          </div>

          {status && <div className="mt-3 rounded-xl bg-blue-50 px-3 py-2 text-xs text-blue-700 dark:bg-blue-500/10 dark:text-blue-200">{status}</div>}

          {records.length > 0 && (
            <div className="mt-4 space-y-3">
              {records.map((record, index) => {
                const template = templates.find((item) => item.id === record.template_id || item.serverAssetId === record.template_asset_id)
                const garment = garments.find((item) => item.id === record.garment_id || item.serverAssetId === record.first_garment_asset_id)
                const effectiveGarmentNames = template && garment
                  ? resolveEffectiveGarmentReferencePreviews(template, garment).map((item) => item.fileName)
                  : []
                const draft = finalDrafts[record.id] ?? ''
                const isDirectPrompt = !record.analysis_job_id
                return (
                  <article key={record.id} className="rounded-xl border border-gray-200 p-3 dark:border-white/[0.08]">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="text-xs font-bold text-gray-800 dark:text-gray-100">
                        {index + 1}. {template?.displayName || template?.fileName || record.template_id}
                        {record.client_item_id && garment ? ` × ${effectiveGarmentNames.join(' + ') || garment.garmentFileName}` : ''}
                      </div>
                      {record.client_item_id && garment && effectiveGarmentNames.length > 0 && (
                        <div className="w-full text-[11px] text-gray-500 dark:text-gray-400">
                          Luna 实际服装参考：{effectiveGarmentNames.join(' + ')}
                        </div>
                      )}
                      <PromptStatus status={record.prompt_status} version={record.prompt_version} />
                    </div>
                    {record.error_message && <div className="mt-2 rounded-lg bg-red-50 px-2.5 py-2 text-xs text-red-700 dark:bg-red-500/10 dark:text-red-200">{record.error_message}</div>}
                    {isDirectPrompt ? (
                      <details className="mt-3 rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-600 dark:bg-white/[0.025] dark:text-gray-300">
                        <summary className="cursor-pointer font-semibold">查看任务提示词快照</summary>
                        <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap font-sans leading-5">{draft}</pre>
                      </details>
                    ) : <textarea
                      value={draft}
                      disabled={record.prompt_status === 'analyzing'}
                      onChange={(event) => setFinalDrafts((current) => ({ ...current, [record.id]: event.target.value }))}
                      rows={7}
                      placeholder="最终换衣提示词"
                      className="mt-3 w-full resize-y rounded-xl border border-gray-200 bg-gray-50 px-3 py-2.5 text-xs leading-5 text-gray-700 outline-none focus:border-blue-400 disabled:opacity-60 dark:border-white/[0.08] dark:bg-white/[0.025] dark:text-gray-200"
                    />}
                    <div className="mt-2 flex flex-wrap justify-end gap-2">
                      <button type="button" disabled={!draft} onClick={() => void navigator.clipboard.writeText(draft)} className="h-8 rounded-lg border border-gray-200 px-3 text-xs font-semibold text-gray-600 disabled:opacity-40 dark:border-white/[0.08] dark:text-gray-300">复制</button>
                      {isDirectPrompt ? (
                        <span className="flex h-8 items-center rounded-lg bg-emerald-50 px-3 text-xs font-semibold text-emerald-700">已作为任务提示词快照生效</span>
                      ) : (
                        <>
                          <button type="button" disabled={busy || record.prompt_status === 'analyzing'} onClick={() => void onReanalyze(record, record.analysis_prompt_used)} className="h-8 rounded-lg border border-gray-200 px-3 text-xs font-semibold text-gray-600 disabled:opacity-40 dark:border-white/[0.08] dark:text-gray-300">重新分析</button>
                          <button type="button" disabled={busy || !draft.trim() || !['ready', 'effective'].includes(record.prompt_status)} onClick={() => void onConfirm(record, draft)} className="h-8 rounded-lg bg-blue-600 px-3 text-xs font-semibold text-white disabled:bg-gray-300">
                            {record.prompt_status === 'effective' ? '更新生效提示词' : '确认并生效'}
                          </button>
                        </>
                      )}
                    </div>
                  </article>
                )
              })}
            </div>
          )}

          {workflowReady && records.length > 0 && (
            <div className="mt-4 flex flex-col gap-2 rounded-xl border border-emerald-200 bg-emerald-50 p-3 dark:border-emerald-400/20 dark:bg-emerald-500/10 sm:flex-row sm:items-center sm:justify-between">
              <div className="text-xs text-emerald-800 dark:text-emerald-100">
                {allEffective ? '所有模板提示词已确认，可以创建正式图片批次。' : '请逐个确认模板提示词；确认前不会提交图片生成任务。'}
              </div>
              <button type="button" disabled={busy || !allEffective} onClick={() => void onSubmit()} className="h-9 shrink-0 rounded-xl bg-emerald-600 px-4 text-xs font-semibold text-white disabled:bg-gray-300">
                开始批量生成
              </button>
            </div>
          )}
        </div>
      )}
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

function PromptStatus({ status, version }: { status: BatchTryOnTemplatePrompt['prompt_status']; version: number }) {
  const labels: Record<BatchTryOnTemplatePrompt['prompt_status'], string> = {
    draft: '草稿', analyzing: '分析中', ready: '待确认', effective: '已生效', stale: '需重新分析', failed: '失败',
  }
  const tones: Record<BatchTryOnTemplatePrompt['prompt_status'], string> = {
    draft: 'bg-gray-100 text-gray-600', analyzing: 'bg-blue-50 text-blue-700', ready: 'bg-amber-50 text-amber-700',
    effective: 'bg-emerald-50 text-emerald-700', stale: 'bg-orange-50 text-orange-700', failed: 'bg-red-50 text-red-700',
  }
  return <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${tones[status]}`}>{labels[status]} · v{version}</span>
}
