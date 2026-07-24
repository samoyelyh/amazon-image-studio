import type { BatchTryOnItem, BatchTryOnItemStatus, BatchTryOnReviewStatus } from '../types'
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

interface Props {
  items: BatchTryOnItem[]
  onView: (imageId: string) => void
  onDownload: (item: BatchTryOnItem) => void
  onRetry: (item: BatchTryOnItem) => void
  onReview: (item: BatchTryOnItem) => void
}

export default function BatchTryOnQueue({ items, onView, onDownload, onRetry, onReview }: Props) {
  if (items.length === 0) {
    return <div className="rounded-xl border border-dashed border-gray-200 px-4 py-10 text-center text-sm text-gray-400 dark:border-white/[0.08]">上传服装图片后，任务会显示在这里。</div>
  }

  return (
    <div className="space-y-3">
      {items.map((item) => (
        <article
          key={item.id}
          onClick={() => item.serverReviewItemId && onReview(item)}
          className={`grid gap-3 rounded-xl border border-gray-200 bg-white p-3 dark:border-white/[0.08] dark:bg-gray-950 sm:grid-cols-[136px_minmax(0,1fr)_140px] sm:items-center ${item.serverReviewItemId ? 'cursor-pointer transition hover:border-blue-300 hover:shadow-sm dark:hover:border-blue-500/40' : ''}`}
        >
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
              <span className="truncate text-sm font-semibold text-gray-900 dark:text-gray-100" title={item.templateName}>模板：{item.templateName || '默认模板'}</span>
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
      ))}
    </div>
  )
}

function formatElapsed(startedAt: number, finishedAt?: number) {
  const elapsedMs = Math.max(0, (finishedAt || Date.now()) - startedAt)
  if (elapsedMs < 1000) return `${elapsedMs} ms`
  const seconds = Math.round(elapsedMs / 100) / 10
  return `${seconds} 秒`
}
