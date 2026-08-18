import { useMemo, useState } from 'react'
import type { BatchTryOnItem, BatchTryOnItemStatus, BatchTryOnReviewStatus } from '../types'
import { isBatchTryOnBulkRegeneratable } from '../lib/batchTryOnBulkActions'
import { BatchTryOnImage } from './BatchTryOnImage'

const STATUS_LABEL: Record<BatchTryOnItemStatus, string> = {
  pending: '待处理',
  queued: '等待队列中',
  retry_waiting: '等待队列中',
  running: '生成中',
  done: '已完成',
  error: '生成失败',
  stopped: '已停止',
}

const STATUS_CLASS: Record<BatchTryOnItemStatus, string> = {
  pending: 'bg-gray-100 text-gray-600 dark:bg-white/[0.07] dark:text-gray-300',
  queued: 'bg-slate-100 text-slate-700 dark:bg-slate-500/10 dark:text-slate-200',
  retry_waiting: 'bg-slate-100 text-slate-700 dark:bg-slate-500/10 dark:text-slate-200',
  running: 'bg-blue-50 text-blue-700 dark:bg-blue-500/10 dark:text-blue-200',
  done: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-200',
  error: 'bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-200',
  stopped: 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-200',
}

const REVIEW_LABEL: Record<BatchTryOnReviewStatus, string> = {
  pending: '待审核',
  approved: '已通过',
  rejected: '已打回',
  regenerating: '重新生成中',
  generation_failed: '生成失败',
}

const REVIEW_CLASS: Record<BatchTryOnReviewStatus, string> = {
  pending: 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-200',
  approved: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-200',
  rejected: 'bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-200',
  regenerating: 'bg-blue-50 text-blue-700 dark:bg-blue-500/10 dark:text-blue-200',
  generation_failed: 'bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-200',
}

type ResultFilter = 'all' | 'pending_review' | 'succeeded'

interface Props {
  items: BatchTryOnItem[]
  selectedItemIds: Set<string>
  canBulkApprove: boolean
  canBulkRegenerate: boolean
  onView: (imageId: string) => void
  onDownload: (item: BatchTryOnItem) => void
  onRetry: (item: BatchTryOnItem) => void
  onReview: (item: BatchTryOnItem) => void
  onToggleSelection: (item: BatchTryOnItem, selected: boolean) => void
  onSelectItems: (items: BatchTryOnItem[]) => void
  onClearSelection: () => void
  onInvertSelection: (items: BatchTryOnItem[]) => void
  onBulkRegenerate: () => void
  onBulkLunaAnalyze: () => void
  onBulkRegenerateItems: (items: BatchTryOnItem[]) => void
  onBulkApprove: () => void
  onDownloadTemplate: (
    templateId: string,
    scope: 'approved' | 'all_succeeded',
    templateName: string,
    reviewItemIds: string[],
  ) => void
}

export default function BatchTryOnQueue({
  items,
  selectedItemIds,
  canBulkApprove,
  canBulkRegenerate,
  onView,
  onDownload,
  onRetry,
  onReview,
  onToggleSelection,
  onSelectItems,
  onClearSelection,
  onInvertSelection,
  onBulkRegenerate,
  onBulkLunaAnalyze,
  onBulkRegenerateItems,
  onBulkApprove,
  onDownloadTemplate,
}: Props) {
  const [filter, setFilter] = useState<ResultFilter>('all')
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const filteredItems = useMemo(() => items.filter((item) => {
    if (filter === 'pending_review') return item.serverReviewStatus === 'pending'
    if (filter === 'succeeded') return item.status === 'done' && Boolean(item.outputImageId)
    return true
  }), [filter, items])
  const groups = useMemo(() => {
    const result = new Map<string, { groupId: string; templateId: string; templateName: string; serverBatchId?: string; items: BatchTryOnItem[] }>()
    for (const item of filteredItems) {
      const templateId = item.templateId || 'default'
      const groupId = `${item.serverBatchId || 'unsubmitted'}:${templateId}`
      const group = result.get(groupId) || {
        groupId,
        templateId,
        templateName: item.templateName || '默认模板',
        serverBatchId: item.serverBatchId,
        items: [],
      }
      group.items.push(item)
      result.set(groupId, group)
    }
    return [...result.values()]
  }, [filteredItems])
  const visibleSelectable = filteredItems.filter(isBatchTryOnBulkRegeneratable)

  if (items.length === 0) {
    return <div className="rounded-xl border border-dashed border-gray-200 px-4 py-10 text-center text-sm text-gray-400 dark:border-white/[0.08]">上传服装图片后，任务会显示在这里。</div>
  }

  return (
    <div className="space-y-4">
      <div className="sticky top-0 z-10 rounded-xl border border-blue-100 bg-white/95 p-3 shadow-sm backdrop-blur dark:border-blue-500/20 dark:bg-gray-950/95">
        <div className="flex flex-wrap items-center gap-2">
          <span className="mr-1 text-sm font-bold text-blue-700 dark:text-blue-200">已选择 {selectedItemIds.size} 张</span>
          <button type="button" onClick={() => onSelectItems(visibleSelectable)} className="rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs font-semibold dark:border-white/[0.1]">全选当前筛选</button>
          <button type="button" onClick={() => onSelectItems(visibleSelectable)} className="rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs font-semibold dark:border-white/[0.1]">全选当前页</button>
          <button type="button" onClick={() => onInvertSelection(visibleSelectable)} className="rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs font-semibold dark:border-white/[0.1]">反选可选</button>
          <button type="button" onClick={onClearSelection} className="rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs font-semibold dark:border-white/[0.1]">清空选择</button>
          <span className="mx-1 hidden h-5 w-px bg-gray-200 sm:block dark:bg-white/[0.1]" />
          <button type="button" onClick={onBulkApprove} disabled={!canBulkApprove} className="rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-bold text-white disabled:opacity-40">批量审核通过</button>
          <button type="button" onClick={onBulkRegenerate} disabled={!canBulkRegenerate} className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-bold text-white disabled:opacity-40">批量附加要求重新生成</button>
          <button type="button" onClick={onBulkLunaAnalyze} disabled={!canBulkRegenerate} className="rounded-lg bg-violet-600 px-3 py-1.5 text-xs font-bold text-white disabled:opacity-40">Luna 批量分析并重生成</button>
          <label className="ml-auto flex items-center gap-2 text-xs text-gray-500 dark:text-gray-300">
            筛选
            <select value={filter} onChange={(event) => setFilter(event.target.value as ResultFilter)} className="rounded-lg border border-gray-200 bg-white px-2 py-1.5 outline-none dark:border-white/[0.1] dark:bg-gray-900">
              <option value="all">全部结果</option>
              <option value="pending_review">只看待审核</option>
              <option value="succeeded">只看生成成功</option>
            </select>
          </label>
        </div>
      </div>

      {groups.map((group) => {
        const succeeded = group.items.filter((item) => item.status === 'done').length
        const pending = group.items.filter((item) => item.serverReviewStatus === 'pending').length
        const approved = group.items.filter((item) => item.serverReviewStatus === 'approved').length
        const selectable = group.items.filter(isBatchTryOnBulkRegeneratable)
        const isCollapsed = collapsed.has(group.groupId)
        return (
          <section key={group.groupId} className="overflow-hidden rounded-2xl border border-gray-200 dark:border-white/[0.08]">
            <header className="bg-gray-50 px-3 py-3 dark:bg-white/[0.035]">
              <div className="flex flex-wrap items-center gap-2">
                <button type="button" onClick={() => setCollapsed((current) => {
                  const next = new Set(current)
                  if (next.has(group.groupId)) next.delete(group.groupId)
                  else next.add(group.groupId)
                  return next
                })} className="mr-auto text-left">
                  <div className="text-sm font-bold text-gray-900 dark:text-gray-100">{group.templateName}</div>
                  {group.serverBatchId && <div className="mt-0.5 text-[11px] text-gray-400">任务组 {group.serverBatchId.slice(0, 8)}</div>}
                  <div className="mt-1 text-xs text-gray-500 dark:text-gray-400">成功 {succeeded}/{group.items.length} · 待审核 {pending} · 已通过 {approved}</div>
                </button>
                <button type="button" onClick={() => onSelectItems(selectable)} className="rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-semibold dark:border-white/[0.1] dark:bg-gray-900">全选该模板</button>
                <button type="button" disabled={!canBulkRegenerate || !selectable.length} onClick={() => onBulkRegenerateItems(selectable)} className="rounded-lg bg-blue-600 px-2.5 py-1.5 text-xs font-semibold text-white disabled:opacity-40">该模板批量重生成</button>
                {group.templateId !== 'default' && <>
                  <button type="button" onClick={() => onDownloadTemplate(group.templateId, 'approved', group.templateName, group.items.flatMap((item) => item.serverReviewItemId ? [item.serverReviewItemId] : []))} className="rounded-lg border border-emerald-200 bg-emerald-50 px-2.5 py-1.5 text-xs font-semibold text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-200">下载审核通过</button>
                  <button type="button" onClick={() => onDownloadTemplate(group.templateId, 'all_succeeded', group.templateName, group.items.flatMap((item) => item.serverReviewItemId ? [item.serverReviewItemId] : []))} className="rounded-lg border border-blue-200 bg-blue-50 px-2.5 py-1.5 text-xs font-semibold text-blue-700 dark:border-blue-500/30 dark:bg-blue-500/10 dark:text-blue-200">下载全部成功</button>
                </>}
                <span className="text-xs text-gray-400">{isCollapsed ? '展开' : '收起'}</span>
              </div>
            </header>
            {!isCollapsed && <div className="space-y-3 p-3">
              {group.items.map((item) => {
                const selectionId = item.serverReviewItemId
                const selectableItem = isBatchTryOnBulkRegeneratable(item)
                const selected = Boolean(selectionId && selectedItemIds.has(selectionId))
                return (
                  <article
                    key={item.id}
                    onClick={() => item.serverReviewItemId && onReview(item)}
                    className={`grid gap-3 rounded-xl border bg-white p-3 dark:bg-gray-950 sm:grid-cols-[28px_136px_minmax(0,1fr)_140px] sm:items-center ${selected ? 'border-blue-400 ring-2 ring-blue-500/10' : 'border-gray-200 dark:border-white/[0.08]'} ${item.serverReviewItemId ? 'cursor-pointer transition hover:border-blue-300 hover:shadow-sm dark:hover:border-blue-500/40' : ''}`}
                  >
                    <label onClick={(event) => event.stopPropagation()} className="flex h-8 items-center justify-center" title={selectableItem ? '选择当前结果' : '只有生成成功且输入素材完整的当前版本可批量重新生成'}>
                      <input
                        type="checkbox"
                        checked={selected}
                        disabled={!selectableItem}
                        onChange={(event) => onToggleSelection(item, event.target.checked)}
                        className="h-4 w-4 rounded border-gray-300 text-blue-600"
                      />
                    </label>
                    <div className="flex gap-2">
                      {item.templateImageId && <button type="button" onClick={(event) => { event.stopPropagation(); onView(item.templateImageId!) }} className="h-16 w-16 overflow-hidden rounded-lg bg-gray-100 dark:bg-gray-900" title="查看模板图">
                        <BatchTryOnImage imageId={item.templateImageId} alt={item.templateName || '模板图'} className="h-full w-full object-cover" />
                      </button>}
                      <button type="button" onClick={(event) => { event.stopPropagation(); onView(item.garmentImageId) }} className="h-16 w-16 overflow-hidden rounded-lg bg-gray-100 dark:bg-gray-900" title="查看服装原图">
                        <BatchTryOnImage imageId={item.garmentImageId} alt={item.garmentFileName} className="h-full w-full object-cover" />
                      </button>
                    </div>
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="truncate text-sm font-semibold text-gray-900 dark:text-gray-100" title={item.templateName}>{item.templateName || '默认模板'}</span>
                        <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${STATUS_CLASS[item.status]}`}>{STATUS_LABEL[item.status]}</span>
                        {item.serverReviewStatus && <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${REVIEW_CLASS[item.serverReviewStatus]}`}>{REVIEW_LABEL[item.serverReviewStatus]}</span>}
                      </div>
                      <div className="mt-1 truncate text-xs font-medium text-gray-700 dark:text-gray-200" title={item.garmentFileName}>服装：{item.garmentFileName}</div>
                      <div className="mt-1 truncate text-xs font-medium text-gray-600 dark:text-gray-300" title={item.serverOutputFilename}>
                        生成结果：{item.serverOutputFilename || '等待生成'}
                      </div>
                      {item.presetSummary && <div className="mt-1 truncate text-[11px] text-violet-600 dark:text-violet-300" title={item.presetSummary}>预设：{item.presetSummary}</div>}
                      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-gray-400">
                        <span>序号 {String(item.index + 1).padStart(3, '0')}</span>
                        <span>版本 v{item.serverVersionNumber ?? Math.max(1, (item.regenerationCount ?? 0) + 1)}</span>
                        {item.startedAt && <span>耗时 {formatElapsed(item.startedAt, item.finishedAt)}</span>}
                        {item.taskId && <span className="max-w-48 truncate" title={item.taskId}>任务 {item.taskId}</span>}
                      </div>
                      {item.error && (item.status === 'error' || item.status === 'stopped') && <div className="mt-2 rounded-lg bg-red-50 px-2.5 py-2 text-xs leading-relaxed text-red-700 dark:bg-red-500/10 dark:text-red-200">{item.error}</div>}
                    </div>
                    <div className="flex items-center gap-2 sm:flex-col sm:items-stretch">
                      {item.outputImageId ? (
                        <button type="button" onClick={(event) => { event.stopPropagation(); onView(item.outputImageId!) }} className="h-16 w-16 shrink-0 overflow-hidden rounded-lg border border-gray-200 bg-gray-100 dark:border-white/[0.08] dark:bg-gray-900 sm:h-20 sm:w-full" title="查看结果大图">
                          <BatchTryOnImage imageId={item.outputImageId} alt={`${item.garmentFileName} 套图结果`} className="h-full w-full object-cover" />
                        </button>
                      ) : (
                        <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-lg border border-dashed border-gray-200 bg-gray-50 text-[11px] text-gray-400 dark:border-white/[0.08] dark:bg-white/[0.03] sm:h-20 sm:w-full">暂无结果</div>
                      )}
                      <div className="flex flex-wrap gap-1.5">
                        {item.serverReviewItemId && <button type="button" onClick={(event) => { event.stopPropagation(); onReview(item) }} className="rounded-md bg-blue-600 px-2 py-1 text-[11px] font-semibold text-white transition hover:bg-blue-500">{item.serverReviewStatus === 'approved' ? '查看审核结果' : item.status === 'error' ? '查看并重试' : '对比审核'}</button>}
                        {item.outputImageId && <button type="button" onClick={(event) => { event.stopPropagation(); onDownload(item) }} className="rounded-md border border-gray-200 px-2 py-1 text-[11px] font-medium text-gray-700 transition hover:bg-gray-50 dark:border-white/[0.08] dark:text-gray-200 dark:hover:bg-white/[0.06]">下载结果</button>}
                        {(item.status === 'error' || item.status === 'stopped') && <button type="button" onClick={(event) => { event.stopPropagation(); onRetry(item) }} className="rounded-md border border-blue-200 px-2 py-1 text-[11px] font-semibold text-blue-700 transition hover:bg-blue-50 dark:border-blue-500/30 dark:text-blue-200">单独重试</button>}
                      </div>
                    </div>
                  </article>
                )
              })}
            </div>}
          </section>
        )
      })}
      {!filteredItems.length && <div className="rounded-xl border border-dashed border-gray-200 px-4 py-8 text-center text-sm text-gray-400 dark:border-white/[0.08]">当前筛选条件下没有结果。</div>}
    </div>
  )
}

function formatElapsed(startedAt: number, finishedAt?: number) {
  const elapsedMs = Math.max(0, (finishedAt || Date.now()) - startedAt)
  if (elapsedMs < 1000) return `${elapsedMs} ms`
  const seconds = Math.round(elapsedMs / 100) / 10
  return `${seconds} 秒`
}
