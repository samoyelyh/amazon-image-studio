import type { BatchTryOnItem, BatchTryOnItemStatus } from '../types'
import { BatchTryOnImage } from './BatchTryOnImage'

const STATUS_LABEL: Record<BatchTryOnItemStatus, string> = {
  pending: '待处理',
  running: '生成中',
  done: '已完成',
  error: '生成失败',
  stopped: '已停止',
}

const STATUS_CLASS: Record<BatchTryOnItemStatus, string> = {
  pending: 'bg-gray-100 text-gray-600 dark:bg-white/[0.07] dark:text-gray-300',
  running: 'bg-blue-50 text-blue-700 dark:bg-blue-500/10 dark:text-blue-200',
  done: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-200',
  error: 'bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-200',
  stopped: 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-200',
}

interface Props {
  items: BatchTryOnItem[]
  onView: (imageId: string) => void
  onDownload: (item: BatchTryOnItem) => void
  onRetry: (item: BatchTryOnItem) => void
}

export default function BatchTryOnQueue({ items, onView, onDownload, onRetry }: Props) {
  if (items.length === 0) {
    return <div className="rounded-xl border border-dashed border-gray-200 px-4 py-10 text-center text-sm text-gray-400 dark:border-white/[0.08]">上传服装图片后，任务会显示在这里。</div>
  }

  return (
    <div className="space-y-3">
      {items.map((item) => (
        <article key={item.id} className="grid gap-3 rounded-xl border border-gray-200 bg-white p-3 dark:border-white/[0.08] dark:bg-gray-950 sm:grid-cols-[64px_minmax(0,1fr)_120px] sm:items-center">
          <button type="button" onClick={() => onView(item.garmentImageId)} className="h-16 w-16 overflow-hidden rounded-lg bg-gray-100 dark:bg-gray-900" title="查看服装原图">
            <BatchTryOnImage imageId={item.garmentImageId} alt={item.garmentFileName} className="h-full w-full object-cover" />
          </button>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="truncate text-sm font-semibold text-gray-900 dark:text-gray-100" title={item.garmentFileName}>{item.garmentFileName}</span>
              <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${STATUS_CLASS[item.status]}`}>{STATUS_LABEL[item.status]}</span>
            </div>
            <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-gray-400">
              <span>序号 {String(item.index + 1).padStart(3, '0')}</span>
              {item.startedAt && <span>耗时 {formatElapsed(item.startedAt, item.finishedAt)}</span>}
              {item.taskId && <span className="max-w-48 truncate" title={item.taskId}>任务 {item.taskId}</span>}
            </div>
            {item.error && <div className="mt-2 rounded-lg bg-red-50 px-2.5 py-2 text-xs leading-relaxed text-red-700 dark:bg-red-500/10 dark:text-red-200">{item.error}</div>}
          </div>
          <div className="flex items-center gap-2 sm:flex-col sm:items-stretch">
            {item.outputImageId ? (
              <button type="button" onClick={() => onView(item.outputImageId!)} className="h-16 w-16 shrink-0 overflow-hidden rounded-lg border border-gray-200 bg-gray-100 dark:border-white/[0.08] dark:bg-gray-900 sm:h-20 sm:w-full" title="查看结果大图">
                <BatchTryOnImage imageId={item.outputImageId} alt={`${item.garmentFileName} 套图结果`} className="h-full w-full object-cover" />
              </button>
            ) : (
              <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-lg border border-dashed border-gray-200 bg-gray-50 text-[11px] text-gray-400 dark:border-white/[0.08] dark:bg-white/[0.03] sm:h-20 sm:w-full">暂无结果</div>
            )}
            <div className="flex flex-wrap gap-1.5">
              {item.outputImageId && <button type="button" onClick={() => onDownload(item)} className="rounded-md border border-gray-200 px-2 py-1 text-[11px] font-medium text-gray-700 transition hover:bg-gray-50 dark:border-white/[0.08] dark:text-gray-200 dark:hover:bg-white/[0.06]">下载结果</button>}
              {(item.status === 'error' || item.status === 'stopped') && <button type="button" onClick={() => onRetry(item)} className="rounded-md bg-blue-600 px-2 py-1 text-[11px] font-semibold text-white transition hover:bg-blue-500">单独重试</button>}
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
