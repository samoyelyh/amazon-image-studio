import { useMemo, useState } from 'react'
import type { JobOutput } from '../../lib/jobsApi'
import type { ListingImageTask, ListingImageTaskGroup } from '../../lib/listingWorkflowApi'
import type { AttachmentModuleResultState } from '../../lib/attachmentPlanningApi'
import { downloadServerOutput } from '../../lib/serverDownloads'
import AuthenticatedImage from '../category-listing/AuthenticatedImage'

const button = 'rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-semibold text-gray-700 disabled:opacity-50 dark:border-white/[0.1] dark:bg-gray-950 dark:text-gray-200'
const primary = 'rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50'
const reviewLabel = { pending_review: '待审核', approved: '已通过', rejected: '已打回' } as const

export interface AttachmentResultEntry {
  group: ListingImageTaskGroup
  task: ListingImageTask
  output: JobOutput
}

interface Props {
  moduleKey: string
  moduleName: string
  groups: ListingImageTaskGroup[]
  state?: AttachmentModuleResultState
  busy: boolean
  onApprove: (entry: AttachmentResultEntry, setFinal: boolean) => Promise<void>
  onReject: (entry: AttachmentResultEntry, clearFinal: boolean) => Promise<void>
  onRetry: (task: ListingImageTask) => Promise<void>
  onClear: () => Promise<void>
  onReset: () => Promise<void>
  moduleStateVersion: number
  onAdoptDirection: (entry: AttachmentResultEntry, expectedStateVersion: number) => Promise<void>
}

export function deriveAttachmentResultData(
  moduleKey: string, groups: ListingImageTaskGroup[], state?: AttachmentModuleResultState,
) {
  const sorted = [...groups].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
  const entries: AttachmentResultEntry[] = []
  const failed: ListingImageTask[] = []
  for (const group of sorted) for (const task of group.tasks.filter((item) => item.image_type === moduleKey)) {
    for (const output of task.outputs) entries.push({ group, task, output })
    if (!task.outputs.length && ['failed', 'cancelled'].includes(task.status)) {
      const clearedAt = state?.results_cleared_at ? new Date(state.results_cleared_at).getTime() : 0
      if (new Date(task.created_at).getTime() > clearedAt) failed.push(task)
    }
  }
  const visible = entries.filter((entry) => !entry.output.discarded_at)
  const final = entries.find((entry) => entry.output.id === state?.current_final_output_id) || null
  const bySlot = new Map<number, AttachmentResultEntry>()
  for (const entry of visible) {
    const slot = entry.task.slot_index || entry.output.sequence_number + 1
    if (!bySlot.has(slot)) bySlot.set(slot, entry)
  }
  const current = [...bySlot.values()]
  if (final && !current.some((entry) => entry.output.id === final.output.id)) current.unshift(final)
  const currentIds = new Set(current.map((entry) => entry.output.id))
  return { current, final, history: entries.filter((entry) => !currentIds.has(entry.output.id)), failed }
}

function time(value: string | null) {
  return value ? new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : '—'
}

function OutputCard({ entry, final, onOpen }: { entry: AttachmentResultEntry; final: boolean; onOpen: () => void }) {
  const status = entry.output.review_status || 'pending_review'
  return <article role="button" tabIndex={0} onClick={onOpen} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') onOpen() }} className={`cursor-pointer overflow-hidden rounded-xl border bg-gray-50 text-left transition hover:shadow-sm dark:bg-white/[0.03] ${final ? 'border-blue-400 ring-2 ring-blue-100' : status === 'rejected' ? 'border-red-200' : 'border-gray-200 dark:border-white/[0.08]'}`}>
    <div className="relative">
      <AuthenticatedImage allowZoom={false} url={entry.output.url} alt={`${entry.task.image_type}结果`} className="aspect-square w-full object-contain" placeholderClassName="aspect-square" />
      <div className="absolute left-2 top-2 flex flex-wrap gap-1">
        {final && <span className="rounded-full bg-blue-600 px-2 py-0.5 text-[10px] font-semibold text-white">最终采用</span>}
        <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${status === 'approved' ? 'bg-emerald-600 text-white' : status === 'rejected' ? 'bg-red-600 text-white' : 'bg-gray-900/75 text-white'}`}>{reviewLabel[status]}</span>
        {entry.task.generation_mode === 'creative' && <span className="rounded-full bg-violet-600 px-2 py-0.5 text-[10px] font-semibold text-white">创意 {entry.task.creative_direction_index || entry.task.slot_index}</span>}
      </div>
    </div>
    <div className="p-2.5"><div className="text-xs font-semibold text-gray-800 dark:text-gray-100">{entry.task.generation_mode === 'creative' ? `创意方向 ${entry.task.creative_direction_index || entry.task.slot_index}` : `候选 ${entry.task.slot_index || entry.output.sequence_number + 1}`}</div><div className="mt-1 text-[11px] text-gray-500">任务组 #{entry.group.group_number} · {entry.task.generation_mode === 'creative' ? '创意' : '标准'} · {entry.output.width}×{entry.output.height}</div></div>
  </article>
}

export default function AttachmentResultReviewPanel({
  moduleKey, moduleName, groups, state, busy, onApprove, onReject, onRetry, onClear, onReset,
  moduleStateVersion, onAdoptDirection,
}: Props) {
  const [selected, setSelected] = useState<AttachmentResultEntry | null>(null)
  const [historyOpen, setHistoryOpen] = useState(false)
  const data = useMemo(
    () => deriveAttachmentResultData(moduleKey, groups, state),
    [groups, moduleKey, state?.current_final_output_id, state?.results_cleared_at],
  )

  return <section>
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><h3 className="text-sm font-semibold text-gray-900 dark:text-white">生成结果与审核</h3><p className="mt-1 text-xs text-gray-500">当前区域保留最终采用图和每个槽位的最新结果；旧批次不会被新批次覆盖。</p></div>
      <div className="flex flex-wrap gap-2"><button className={button} disabled={busy || !data.current.length} onClick={() => void onClear()}>清空当前结果</button><button className={button} disabled={busy} onClick={() => void onReset()}>重置模块</button></div>
    </div>
    {data.current.length > 0 ? <div className="mt-3 grid grid-cols-2 gap-3">{data.current.map((entry) => <OutputCard key={entry.output.id} entry={entry} final={entry.output.id === state?.current_final_output_id} onOpen={() => setSelected(entry)} />)}</div> : <div className="mt-3 flex min-h-32 items-center justify-center rounded-xl border border-dashed border-gray-200 text-xs text-gray-400 dark:border-white/[0.08]">当前结果为空；历史图片和对象存储文件仍会保留。</div>}
    {data.failed.length > 0 && <div className="mt-3 space-y-2">{data.failed.map((task) => <div key={task.id} className="flex items-center justify-between gap-3 rounded-xl bg-red-50 px-3 py-2 text-xs text-red-700"><span>候选 {task.slot_index || '-'} 生成失败：{task.error_message || '上游未返回结果'}</span><button className={button} disabled={busy} onClick={() => void onRetry(task)}>仅重试此槽位</button></div>)}</div>}
    {data.history.length > 0 && <div className="mt-4 border-t border-gray-100 pt-3 dark:border-white/[0.06]"><button type="button" className="text-xs font-semibold text-gray-600 dark:text-gray-300" onClick={() => setHistoryOpen((value) => !value)}>{historyOpen ? '收起历史结果' : `查看历史结果（${data.history.length}）`}</button>{historyOpen && <div className="mt-3 grid grid-cols-3 gap-2">{data.history.map((entry) => <OutputCard key={entry.output.id} entry={entry} final={false} onOpen={() => setSelected(entry)} />)}</div>}</div>}

    {selected && <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/55 p-4" role="dialog" aria-modal="true" aria-label={`${moduleName}结果审核`}>
      <div className="max-h-[92vh] w-full max-w-5xl overflow-auto rounded-2xl bg-white p-5 shadow-2xl dark:bg-gray-900">
        <div className="flex items-start justify-between gap-3"><div><h2 className="text-lg font-semibold text-gray-950 dark:text-white">{moduleName} · 结果审核</h2><p className="mt-1 text-xs text-gray-500">审核绑定输出 ID {selected.output.id.slice(0, 8)}，不会影响同模块其他图片。</p></div><button className="text-xl text-gray-400" onClick={() => setSelected(null)}>×</button></div>
        <div className="mt-4 grid gap-5 lg:grid-cols-[minmax(0,1.25fr)_minmax(320px,.75fr)]">
          <AuthenticatedImage url={selected.output.url} alt={`${moduleName}审核大图`} className="max-h-[68vh] w-full rounded-xl bg-gray-50 object-contain" placeholderClassName="min-h-80 rounded-xl" />
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-2 text-xs">{[
              ['状态', reviewLabel[selected.output.review_status || 'pending_review']], ['最终采用', selected.output.id === state?.current_final_output_id ? '是' : '否'],
              ['任务组', `#${selected.group.group_number}`], ['候选槽位', String(selected.task.slot_index || '-')],
              ['生成模式', selected.task.generation_mode === 'creative' ? `创意方向 ${selected.task.creative_direction_index || selected.task.slot_index}` : '标准生成'],
              ['模型', selected.task.model_code], ['尺寸', `${selected.output.width}×${selected.output.height}`],
              ['提交时间', time(selected.task.created_at)], ['完成时间', time(selected.task.finished_at)],
            ].map(([label, value]) => <div key={label} className="rounded-lg bg-gray-50 p-2.5 dark:bg-white/[0.03]"><div className="text-gray-400">{label}</div><div className="mt-1 break-words font-semibold text-gray-700 dark:text-gray-200">{value}</div></div>)}</div>
            {selected.task.plan_summary_cn && <details open={selected.task.generation_mode === 'creative'} className="rounded-xl border border-gray-200 p-3 dark:border-white/[0.08]"><summary className="cursor-pointer text-xs font-semibold">{selected.task.generation_mode === 'creative' ? '本张创意方案' : '本次方案快照'}</summary><p className="mt-3 max-h-44 overflow-auto whitespace-pre-wrap text-xs leading-5 text-gray-600 dark:text-gray-300">{selected.task.plan_summary_cn}</p></details>}
            <details className="rounded-xl border border-gray-200 p-3 dark:border-white/[0.08]"><summary className="cursor-pointer text-xs font-semibold">本次方向 Prompt</summary><p className="mt-3 max-h-56 overflow-auto whitespace-pre-wrap text-xs leading-5 text-gray-600 dark:text-gray-300">{selected.task.prompt_cn || selected.task.final_prompt}</p></details>
            <details className="rounded-xl border border-gray-200 p-3 dark:border-white/[0.08]"><summary className="cursor-pointer text-xs font-semibold">完整执行 Prompt 快照</summary><p className="mt-3 max-h-56 overflow-auto whitespace-pre-wrap text-xs leading-5 text-gray-600 dark:text-gray-300">{selected.task.final_prompt}</p></details>
            <details className="rounded-xl border border-gray-200 p-3 dark:border-white/[0.08]"><summary className="cursor-pointer text-xs font-semibold">本次输入素材（{selected.task.input_assets.length}）</summary><div className="mt-3 grid grid-cols-3 gap-2">{selected.task.input_assets.map((asset) => asset.url ? <AuthenticatedImage key={asset.asset_id} url={asset.url} alt={asset.filename} className="aspect-square w-full rounded-lg object-contain" placeholderClassName="aspect-square rounded-lg" /> : null)}</div></details>
            <div className="flex flex-wrap gap-2"><button className={button} onClick={() => void downloadServerOutput(selected.output)}>下载</button>{selected.task.generation_mode === 'creative' && <button className="rounded-lg bg-violet-600 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50" disabled={busy} onClick={() => void onAdoptDirection(selected, moduleStateVersion).then(() => setSelected(null))}>沿用此方向生成</button>}<button className={button} disabled={busy} onClick={() => void onApprove(selected, false).then(() => setSelected(null))}>仅审核通过</button><button className={primary} disabled={busy} onClick={() => void onApprove(selected, true).then(() => setSelected(null))}>通过并设为最终</button><button className="rounded-lg border border-red-200 px-3 py-1.5 text-xs font-semibold text-red-600 disabled:opacity-50" disabled={busy} onClick={() => { const isFinal = selected.output.id === state?.current_final_output_id; if (isFinal && !window.confirm('这张图片当前是最终采用版本。确认打回并清除最终采用状态吗？')) return; void onReject(selected, isFinal).then(() => setSelected(null)) }}>打回</button></div>
          </div>
        </div>
      </div>
    </div>}
  </section>
}
