import { useEffect, useState } from 'react'
import type { ListingImageTask, ListingImageTaskGroup } from '../../lib/listingWorkflowApi'
import type { ListingWorkflowSessionSummary } from '../../lib/listingWorkflowApi'
import type { Asset } from '../../lib/contentApi'
import { listAttachmentPlanVersions, type AttachmentModulePlan, type AttachmentModuleResultState, type AttachmentPlanVersion, type AttachmentProductComposition } from '../../lib/attachmentPlanningApi'
import type {
  AttachmentModuleDefinition,
  AttachmentModuleDraft,
} from '../../lib/attachmentImageWorkbench'
import type {
  AttachmentModuleReferenceState,
  AttachmentProductReferenceItem,
  AttachmentReferenceSlotType,
} from '../../lib/attachmentPlanningApi'
import AttachmentReferencePanel from './AttachmentReferencePanel'
import AttachmentResultReviewPanel, { type AttachmentResultEntry } from './AttachmentResultReviewPanel'
import AttachmentProductCompositionPanel from './AttachmentProductCompositionPanel'

const statusLabels: Record<string, string> = {
  queued: '等待中',
  waiting_for_resource: '等待资源',
  dispatching: '正在调度',
  running: '生成中',
  retry_waiting: '等待重试',
  succeeded: '已完成',
  failed: '失败',
  cancelled: '已停止',
}

interface Props {
  index: number
  definition: AttachmentModuleDefinition
  draft: AttachmentModuleDraft
  expanded: boolean
  available: boolean
  unavailableReason?: string
  objective?: string
  projectId: string
  planning?: AttachmentModulePlan
  planningBusy?: boolean
  referenceState?: AttachmentModuleReferenceState
  productReferences?: AttachmentProductReferenceItem[]
  productComposition?: AttachmentProductComposition
  productCandidates?: ListingWorkflowSessionSummary[]
  productCandidateAssets?: Record<string, Asset>
  tasks: ListingImageTask[]
  groups: ListingImageTaskGroup[]
  resultState?: AttachmentModuleResultState
  onToggleExpanded: () => void
  onChange: (next: AttachmentModuleDraft) => void
  onSavePlanning: (input: { plan_summary_cn: string; prompt_cn: string; operator_requirement_cn: string; aspect_ratio: string; expected_state_version: number }) => Promise<void>
  onReplan: (operatorRequirement: string) => Promise<void>
  onOptimizePrompt: (operatorRequirement: string) => Promise<void>
  onAddReference: (slot: AttachmentReferenceSlotType, assetId: string) => Promise<void>
  onRemoveReference: (referenceId: string) => Promise<void>
  onAnalyzeReferences: () => Promise<void>
  onProductModeChange: (mode: 'SINGLE' | 'MULTI') => Promise<void>
  onAddSecondaryProduct: (sessionId: string) => Promise<void>
  onReplaceSecondaryProduct: (itemId: string, sessionId: string) => Promise<void>
  onRemoveSecondaryProduct: (itemId: string) => Promise<void>
  onReferenceError: (message: string) => void
  onGenerate: () => Promise<void>
  generationBusy?: boolean
  onApproveResult: (entry: AttachmentResultEntry, setFinal: boolean) => Promise<void>
  onRejectResult: (entry: AttachmentResultEntry, clearFinal: boolean) => Promise<void>
  onRetryTask: (task: ListingImageTask) => Promise<void>
  onClearResults: () => Promise<void>
  onResetModule: () => Promise<void>
  onAdoptDirection: (entry: AttachmentResultEntry, expectedStateVersion: number) => Promise<void>
  onSaveSingle?: (entry: AttachmentResultEntry) => Promise<void>
}

export default function AttachmentImageModuleCard({
  index,
  definition,
  draft,
  expanded,
  available,
  unavailableReason,
  objective,
  projectId,
  planning,
  planningBusy = false,
  referenceState,
  productReferences = [],
  productComposition,
  productCandidates = [],
  productCandidateAssets = {},
  tasks,
  groups,
  resultState,
  onToggleExpanded,
  onChange,
  onSavePlanning,
  onReplan,
  onOptimizePrompt,
  onAddReference,
  onRemoveReference,
  onAnalyzeReferences,
  onProductModeChange,
  onAddSecondaryProduct,
  onReplaceSecondaryProduct,
  onRemoveSecondaryProduct,
  onReferenceError,
  onGenerate,
  generationBusy = false,
  onApproveResult,
  onRejectResult,
  onRetryTask,
  onClearResults,
  onResetModule,
  onAdoptDirection,
  onSaveSingle,
}: Props) {
  const [planSummary, setPlanSummary] = useState('')
  const [prompt, setPrompt] = useState('')
  const [operatorRequirement, setOperatorRequirement] = useState('')
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [versions, setVersions] = useState<AttachmentPlanVersion[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)
  useEffect(() => {
    if (dirty) return
    setPlanSummary(planning?.plan_summary_cn || '')
    setPrompt(planning?.prompt_cn || '')
    setOperatorRequirement(planning?.operator_requirement_cn || '')
  }, [planning?.state_version, planning?.current_version_number, dirty])

  const saveCurrent = async () => {
    if (!planning) return
    await onSavePlanning({
      plan_summary_cn: planSummary,
      prompt_cn: prompt,
      operator_requirement_cn: operatorRequirement,
      aspect_ratio: draft.aspectRatio,
      expected_state_version: planning.state_version,
    })
    setDirty(false)
  }

  const saveThenRun = async (action: () => Promise<void>) => {
    setSaving(true)
    try {
      await saveCurrent()
      await action()
    } finally {
      setSaving(false)
    }
  }

  const latestStatus = tasks[0]?.status || 'draft'
  const readyToGenerate = Boolean(
    available
    && (draft.generationMode === 'creative' || (planning?.prompt_cn.trim() && planning?.plan_summary_cn.trim()))
    && (draft.generationMode === 'creative' || planning?.status === 'ready')
    && referenceState?.understanding?.status === 'ready' && !referenceState.reference_context_dirty,
  )

  return <article className={`overflow-hidden rounded-2xl border bg-white shadow-sm transition dark:bg-gray-900 ${draft.selected && available ? 'border-blue-300 ring-1 ring-blue-100 dark:border-blue-500/40' : 'border-gray-200 dark:border-white/[0.08]'}`}>
    <header className="flex items-center gap-3 p-4 sm:p-5">
      <input
        aria-label={`选择${definition.name}`}
        type="checkbox"
        className="h-4 w-4 shrink-0"
        checked={draft.selected && available}
        disabled={!available}
        onChange={(event) => onChange({ ...draft, selected: event.target.checked })}
      />
      <button type="button" onClick={onToggleExpanded} className="flex min-w-0 flex-1 items-center gap-3 text-left">
        <span className="text-xs font-bold text-blue-600">{String(index).padStart(2, '0')}</span>
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-2">
            <strong className="text-sm text-gray-950 dark:text-white">{definition.name}</strong>
            <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] text-gray-600 dark:bg-white/[0.08] dark:text-gray-300">{draft.aspectRatio}</span>
            <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[11px] text-blue-700">{draft.imageCount} {draft.generationMode === 'creative' ? '个方向 · 创意生成' : '张 · 标准生成'}</span>
            {tasks.length > 0 && <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] text-emerald-700">{statusLabels[latestStatus] || latestStatus}</span>}
            {planning && <span className={`rounded-full px-2 py-0.5 text-[11px] ${planning.status === 'failed' ? 'bg-red-50 text-red-700' : planning.status === 'planning' ? 'bg-violet-50 text-violet-700' : 'bg-gray-100 text-gray-600'}`}>{planning.status === 'planning' ? 'AI策划中' : planning.current_version_number ? `Prompt V${planning.current_version_number}` : '尚未策划'}</span>}
          </span>
          <span className="mt-1 block truncate text-xs text-gray-500">{definition.shortDescription}</span>
        </span>
        <span aria-hidden className={`text-sm text-gray-400 transition ${expanded ? 'rotate-180' : ''}`}>⌄</span>
      </button>
    </header>

    {!available && <div className="mx-4 mb-4 rounded-xl bg-amber-50 p-3 text-xs text-amber-800 sm:mx-5">{unavailableReason || '当前商品资料不满足该模块条件。'}</div>}

    {expanded && <div className="grid gap-5 border-t border-gray-100 p-4 dark:border-white/[0.06] sm:p-5 lg:grid-cols-[minmax(0,1.05fr)_minmax(300px,.95fr)]">
      <section>
        <AttachmentResultReviewPanel moduleKey={definition.code} moduleName={definition.name} groups={groups} state={resultState} busy={generationBusy} moduleStateVersion={planning?.state_version || 0} onApprove={onApproveResult} onReject={onRejectResult} onRetry={onRetryTask} onClear={onClearResults} onReset={onResetModule} onAdoptDirection={onAdoptDirection} onSaveSingle={onSaveSingle} />
      </section>

      <section className="space-y-4">
        <div className="rounded-xl bg-gray-50 p-4 dark:bg-white/[0.03]">
          <div className="text-xs font-semibold text-gray-500">当前模块目标</div>
          <p className="mt-2 text-sm leading-6 text-gray-700 dark:text-gray-200">{objective || definition.shortDescription}</p>
        </div>
        <div className={`grid gap-3 ${planning?.supports_creative ? 'sm:grid-cols-3' : 'sm:grid-cols-2'}`}>
          {planning?.supports_creative && <label className="text-xs font-semibold text-gray-600 dark:text-gray-300">生成模式
            <select
              className="mt-1 w-full rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm dark:border-white/[0.1] dark:bg-gray-950"
              value={draft.generationMode}
              onChange={(event) => onChange({ ...draft, generationMode: event.target.value === 'creative' ? 'creative' : 'standard' })}
            >
              <option value="standard">标准生成</option>
              <option value="creative">创意生成</option>
            </select>
            <span className="mt-1 block font-normal text-gray-400">{draft.generationMode === 'creative' ? '探索多个不同画面方向' : '同一方向生成多个候选'}</span>
          </label>}
          <label className="text-xs font-semibold text-gray-600 dark:text-gray-300">画面比例
            <select
              className="mt-1 w-full rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm dark:border-white/[0.1] dark:bg-gray-950"
              value={draft.aspectRatio}
              onChange={(event) => { onChange({ ...draft, aspectRatio: event.target.value }); setDirty(true) }}
            >
              {definition.allowedAspectRatios.map((ratio) => <option key={ratio} value={ratio}>{ratio}</option>)}
            </select>
          </label>
          <label className="text-xs font-semibold text-gray-600 dark:text-gray-300">{draft.generationMode === 'creative' ? '创意方向数量' : '生成数量'}
            <select
              className="mt-1 w-full rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm dark:border-white/[0.1] dark:bg-gray-950"
              value={draft.imageCount}
              onChange={(event) => onChange({ ...draft, imageCount: Number(event.target.value) })}
            >
              {[1, 2, 3, 4].map((count) => <option key={count} value={count}>{count} {draft.generationMode === 'creative' ? '个方向' : '张'}</option>)}
            </select>
          </label>
        </div>
        {productComposition && <AttachmentProductCompositionPanel
          composition={productComposition}
          supportsMultiProduct={Boolean(planning?.supports_multi_product)}
          candidates={productCandidates}
          candidateAssets={productCandidateAssets}
          busy={planningBusy}
          onModeChange={onProductModeChange}
          onAdd={onAddSecondaryProduct}
          onReplace={onReplaceSecondaryProduct}
          onRemove={onRemoveSecondaryProduct}
        />}
        {referenceState && <AttachmentReferencePanel
          state={referenceState}
          productReferences={productReferences}
          busy={planningBusy}
          onAdd={onAddReference}
          onRemove={onRemoveReference}
          onAnalyze={onAnalyzeReferences}
          onError={onReferenceError}
        />}
        <div className="space-y-4 rounded-xl border border-gray-200 p-4 dark:border-white/[0.08]">
          <div className="flex flex-wrap items-center justify-between gap-3"><div><div className="text-xs font-semibold text-gray-500">模块方案</div><p className="mt-1 text-xs text-gray-400">回答“这张图准备做成什么样”。</p></div><button type="button" className="text-xs font-semibold text-blue-600 disabled:opacity-50" disabled={!planning || historyLoading} onClick={() => { const next = !historyOpen; setHistoryOpen(next); if (next) { setHistoryLoading(true); void listAttachmentPlanVersions(projectId, definition.code).then(setVersions).catch(() => setVersions([])).finally(() => setHistoryLoading(false)) } }}>{historyOpen ? '收起版本' : '查看版本'}</button></div>
          <textarea className="min-h-20 w-full rounded-xl border border-gray-200 px-3 py-2 text-sm leading-6 dark:border-white/[0.1] dark:bg-gray-950" value={planSummary} placeholder="尚未策划" onChange={(event) => { setPlanSummary(event.target.value); setDirty(true) }} />
          <label className="block text-xs font-semibold text-gray-600 dark:text-gray-300">运营补充要求
            <textarea className="mt-1 min-h-20 w-full rounded-xl border border-gray-200 px-3 py-2 text-sm font-normal leading-6 dark:border-white/[0.1] dark:bg-gray-950" value={operatorRequirement} placeholder="可选：补充希望增加、删除或强调的画面要求" onChange={(event) => { setOperatorRequirement(event.target.value); setDirty(true) }} />
          </label>
          <label className="block text-xs font-semibold text-gray-600 dark:text-gray-300">最终中文 Prompt
            <textarea className="mt-1 min-h-48 w-full rounded-xl border border-gray-200 px-3 py-2 text-sm font-normal leading-6 dark:border-white/[0.1] dark:bg-gray-950" value={prompt} placeholder="AI策划后将在这里显示可直接用于后续生图的中文Prompt" onChange={(event) => { setPrompt(event.target.value); setDirty(true) }} />
          </label>
          {planning?.error_message && <div className="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">{planning.error_message}</div>}
          {planning?.derived_from_output_id && <div className="rounded-lg bg-violet-50 px-3 py-2 text-xs text-violet-700">当前标准方案沿用自创意结果 {planning.derived_from_output_id.slice(0, 8)}；可以继续编辑后再生成。</div>}
          {draft.generationMode === 'creative' && <div className="rounded-lg bg-blue-50 px-3 py-2 text-xs leading-5 text-blue-700">当前标准方案与Prompt不会被覆盖。点击生成后，AI会一次策划 {draft.imageCount} 个不同方向，再进入确认。</div>}
          <div className="flex flex-wrap gap-2">
            <button type="button" className="rounded-lg bg-blue-600 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50" disabled={!planning || planningBusy || saving || !dirty} onClick={() => { setSaving(true); void saveCurrent().catch(() => undefined).finally(() => setSaving(false)) }}>{saving ? '保存中…' : '保存修改'}</button>
            <button type="button" className="rounded-lg border border-gray-200 px-3 py-2 text-xs font-semibold text-gray-700 disabled:opacity-50 dark:border-white/[0.1] dark:text-gray-200" disabled={!planning || planningBusy || saving} onClick={() => void saveThenRun(() => onReplan(operatorRequirement)).catch(() => undefined)}>AI重新策划</button>
            <button type="button" className="rounded-lg border border-gray-200 px-3 py-2 text-xs font-semibold text-gray-700 disabled:opacity-50 dark:border-white/[0.1] dark:text-gray-200" disabled={!planning || !prompt.trim() || planningBusy || saving} onClick={() => void saveThenRun(() => onOptimizePrompt(operatorRequirement)).catch(() => undefined)}>AI优化 Prompt</button>
            <button type="button" className="rounded-lg bg-blue-600 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50" disabled={!readyToGenerate || planningBusy || saving || generationBusy || dirty} onClick={() => void onGenerate()}>{generationBusy ? '准备确认…' : '生成当前模块'}</button>
          </div>
          {!readyToGenerate && <p className="text-[11px] leading-5 text-amber-700">正式生成前需完成当前参考素材分析{draft.generationMode === 'standard' ? '，并保存完整方案与Prompt' : ''}。</p>}
          {planning?.skill_source.can_view_rules && planning.skill_source.module_rule && <details><summary className="cursor-pointer text-xs font-semibold text-gray-500">管理员：查看规则来源</summary><pre className="mt-2 max-h-52 overflow-auto whitespace-pre-wrap rounded-lg bg-gray-50 p-3 text-[11px] leading-5 text-gray-500 dark:bg-white/[0.03]">{JSON.stringify(planning.skill_source.module_rule, null, 2)}</pre></details>}
          {historyOpen && <div className="space-y-2 border-t border-gray-100 pt-3 dark:border-white/[0.06]">{historyLoading ? <p className="text-xs text-gray-500">正在读取版本…</p> : versions.length ? versions.map((item) => <details key={item.id} className="rounded-lg bg-gray-50 px-3 py-2 dark:bg-white/[0.03]"><summary className="cursor-pointer text-xs font-semibold text-gray-700 dark:text-gray-200">{item.generation_mode === 'creative' ? `创意方向 ${item.creative_direction_index}` : item.action === 'derived_from_creative' ? '沿用创意方向' : `标准 V${item.version_number}`} · {new Date(item.created_at).toLocaleString('zh-CN', { hour12: false })}</summary><div className="mt-2 whitespace-pre-wrap text-xs leading-5 text-gray-500">{item.plan_summary_cn}{item.prompt_cn ? `\n\n${item.prompt_cn}` : ''}</div></details>) : <p className="text-xs text-gray-500">暂无历史版本。</p>}</div>}
        </div>
      </section>
    </div>}
  </article>
}
