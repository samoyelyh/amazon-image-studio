import AuthenticatedImage from '../category-listing/AuthenticatedImage'
import type { ListingImageTask } from '../../lib/listingWorkflowApi'
import type {
  AttachmentModuleDefinition,
  AttachmentModuleDraft,
} from '../../lib/attachmentImageWorkbench'

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
  existingPrompt?: string
  tasks: ListingImageTask[]
  onToggleExpanded: () => void
  onChange: (next: AttachmentModuleDraft) => void
}

export default function AttachmentImageModuleCard({
  index,
  definition,
  draft,
  expanded,
  available,
  unavailableReason,
  objective,
  existingPrompt,
  tasks,
  onToggleExpanded,
  onChange,
}: Props) {
  const outputs = tasks.flatMap((task) => task.outputs)
  const latestStatus = tasks[0]?.status || 'draft'
  const slotCount = Math.max(draft.imageCount, Math.min(4, outputs.length))

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
            <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[11px] text-blue-700">{draft.imageCount} 张 · 标准生成</span>
            {tasks.length > 0 && <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] text-emerald-700">{statusLabels[latestStatus] || latestStatus}</span>}
          </span>
          <span className="mt-1 block truncate text-xs text-gray-500">{definition.shortDescription}</span>
        </span>
        <span aria-hidden className={`text-sm text-gray-400 transition ${expanded ? 'rotate-180' : ''}`}>⌄</span>
      </button>
    </header>

    {!available && <div className="mx-4 mb-4 rounded-xl bg-amber-50 p-3 text-xs text-amber-800 sm:mx-5">{unavailableReason || '当前商品资料不满足该模块条件。'}</div>}

    {expanded && <div className="grid gap-5 border-t border-gray-100 p-4 dark:border-white/[0.06] sm:p-5 lg:grid-cols-[minmax(0,1.05fr)_minmax(300px,.95fr)]">
      <section>
        <div className="flex items-center justify-between gap-3">
          <div><h3 className="text-sm font-semibold text-gray-900 dark:text-white">结果槽位</h3><p className="mt-1 text-xs text-gray-500">固定按任务顺序显示，已完成结果不会因返回先后跳位。</p></div>
          <span className="text-xs text-gray-500">已有 {outputs.length} 张</span>
        </div>
        <div className="mt-3 grid grid-cols-2 gap-3">
          {Array.from({ length: slotCount }, (_, slot) => {
            const output = outputs[slot]
            return <div key={slot} className="overflow-hidden rounded-xl border border-gray-200 bg-gray-50 dark:border-white/[0.08] dark:bg-white/[0.03]">
              {output
                ? <AuthenticatedImage url={output.url} alt={`${definition.name}结果${slot + 1}`} className="aspect-square w-full object-contain" placeholderClassName="aspect-square" />
                : <div className="flex aspect-square items-center justify-center text-xs text-gray-400">候选 {slot + 1} · 尚未生成</div>}
            </div>
          })}
        </div>
      </section>

      <section className="space-y-4">
        <div className="rounded-xl bg-gray-50 p-4 dark:bg-white/[0.03]">
          <div className="text-xs font-semibold text-gray-500">当前模块目标</div>
          <p className="mt-2 text-sm leading-6 text-gray-700 dark:text-gray-200">{objective || definition.shortDescription}</p>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-xs font-semibold text-gray-600 dark:text-gray-300">画面比例
            <select
              className="mt-1 w-full rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm dark:border-white/[0.1] dark:bg-gray-950"
              value={draft.aspectRatio}
              onChange={(event) => onChange({ ...draft, aspectRatio: event.target.value })}
            >
              {definition.allowedAspectRatios.map((ratio) => <option key={ratio} value={ratio}>{ratio}</option>)}
            </select>
          </label>
          <label className="text-xs font-semibold text-gray-600 dark:text-gray-300">生成数量
            <select
              className="mt-1 w-full rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm dark:border-white/[0.1] dark:bg-gray-950"
              value={draft.imageCount}
              onChange={(event) => onChange({ ...draft, imageCount: Number(event.target.value) })}
            >
              {[1, 2, 3, 4].map((count) => <option key={count} value={count}>{count} 张</option>)}
            </select>
          </label>
        </div>
        <div className="rounded-xl border border-dashed border-gray-200 p-4 dark:border-white/[0.08]">
          <div className="flex items-center justify-between gap-3"><span className="text-xs font-semibold text-gray-500">方案与 Prompt</span><span className="rounded-full bg-violet-50 px-2 py-1 text-[11px] text-violet-700">Phase 2</span></div>
          {existingPrompt
            ? <details className="mt-3"><summary className="cursor-pointer text-xs font-semibold text-gray-700 dark:text-gray-200">查看旧工作台已有 Prompt</summary><p className="mt-2 max-h-40 overflow-y-auto whitespace-pre-wrap text-xs leading-5 text-gray-500">{existingPrompt}</p></details>
            : <p className="mt-2 text-xs leading-5 text-gray-500">本阶段先保存模块与参数。整套策划、模块方案和可编辑 Prompt 将在 Phase 2 接入现有版本体系。</p>}
        </div>
      </section>
    </div>}
  </article>
}
