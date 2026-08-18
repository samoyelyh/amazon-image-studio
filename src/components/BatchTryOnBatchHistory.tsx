import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useAuth } from '../app/AuthContext'
import {
  cancelServerBatch,
  hardDeleteServerBatch,
  isServerBatchCancelling,
  isWorkspaceShellBatch,
  listServerBatches,
  pauseServerBatch,
  resumeServerBatch,
  type ServerJobBatch,
} from '../lib/jobsApi'

const TERMINAL_STATUSES = new Set(['succeeded', 'failed', 'cancelled', 'partially_succeeded'])

const STATUS_LABELS: Record<string, string> = {
  draft: '草稿',
  queued: '等待队列',
  running: '生成中',
  paused: '已暂停',
  succeeded: '已完成',
  failed: '失败',
  cancelled: '已取消',
  cancel_requested: '取消中',
  partially_succeeded: '部分完成',
}

function terminalCount(batch: ServerJobBatch) {
  return Math.min(
    batch.total_jobs,
    batch.succeeded_jobs + batch.failed_jobs + batch.cancelled_jobs,
  )
}

function statusClass(status: string) {
  if (status === 'succeeded') return 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-200'
  if (status === 'failed' || status === 'cancelled') return 'bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-200'
  if (status === 'paused' || status === 'partially_succeeded' || status === 'cancel_requested') return 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-200'
  return 'bg-blue-50 text-blue-700 dark:bg-blue-500/10 dark:text-blue-200'
}

function formatTime(value: string | null) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'
}

export default function BatchTryOnBatchHistory({ projectId }: { projectId: string }) {
  const auth = useAuth()
  const queryClient = useQueryClient()
  const [expanded, setExpanded] = useState(true)
  const [busyKey, setBusyKey] = useState('')
  const [message, setMessage] = useState('')
  const queryKey = ['batch-tryon-batch-history', projectId]
  const batches = useQuery({
    queryKey,
    queryFn: () => listServerBatches({
      workspace_type: 'batch_tryon',
      operation_code: 'batch_tryon.generate',
      project_id: projectId,
      include_jobs: false,
      limit: 50,
    }),
    refetchInterval: 3_000,
  })

  const runAction = async (
    batch: ServerJobBatch,
    action: 'pause' | 'resume' | 'cancel',
  ) => {
    if (action === 'cancel' && !window.confirm(
      `确定取消批次“${batch.name || batch.id.slice(0, 8)}”吗？\n已完成的图片会保留，未开始的任务将被取消。`,
    )) return
    setBusyKey(`${batch.id}:${action}`)
    setMessage('')
    try {
      if (action === 'pause') await pauseServerBatch(batch.id)
      else if (action === 'resume') await resumeServerBatch(batch.id)
      else {
        const updated = await cancelServerBatch(batch.id)
        queryClient.setQueryData<Awaited<ReturnType<typeof listServerBatches>>>(queryKey, (current) => current ? {
          ...current,
          items: current.items.map((item) => item.id === updated.id ? updated : item),
        } : current)
      }
      setMessage(action === 'pause'
        ? '批次已暂停'
        : action === 'resume'
          ? '批次已继续'
          : '取消请求已提交。等待中的任务会立即取消；正在生成的图片会在本次上游请求结束后标记为已取消。')
      await queryClient.invalidateQueries({ queryKey })
      await queryClient.invalidateQueries({ queryKey: ['server-job-batches'] })
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '批次操作失败，请重试。')
    } finally {
      setBusyKey('')
    }
  }

  const permanentlyDelete = async (batch: ServerJobBatch) => {
    const name = batch.name || `批次 ${batch.id.slice(0, 8)}`
    if (!window.confirm(
      `永久删除“${name}”？\n\n将清除该批次的任务、审核版本、生成记录和仅属于该批次的生成图片。原始模板、服装、额度流水和审计日志会保留。`,
    )) return
    if (!window.confirm('这是不可恢复操作。确定要永久删除吗？')) return
    setBusyKey(`${batch.id}:hard-delete`)
    setMessage('')
    try {
      const result = await hardDeleteServerBatch(batch.id)
      queryClient.setQueryData<Awaited<ReturnType<typeof listServerBatches>>>(queryKey, (current) => current ? {
        ...current,
        total: Math.max(0, current.total - 1),
        items: current.items.filter((item) => item.id !== batch.id),
      } : current)
      const retained = result.retained_shared_assets
        ? `；${result.retained_shared_assets} 个被其他项目复用的素材已保留`
        : ''
      const storageWarning = result.storage_delete_failures
        ? `；${result.storage_delete_failures} 个对象存储文件清理失败，后台记录已删除`
        : ''
      setMessage(`已永久删除：${result.deleted_jobs} 个任务、${result.deleted_outputs} 条生成记录、${result.deleted_assets} 张专属生成图片${retained}${storageWarning}。`)
      await queryClient.invalidateQueries({ queryKey: ['server-job-batches'] })
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '永久删除失败，请重试。')
    } finally {
      setBusyKey('')
    }
  }

  const visibleBatches = (batches.data?.items || []).filter((item) => !isWorkspaceShellBatch(item))

  return (
    <section className="mt-4 overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm dark:border-white/[0.08] dark:bg-gray-950">
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3.5">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-bold text-gray-900 dark:text-gray-100">批次历史</h3>
            {batches.data && <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-500 dark:bg-white/[0.08] dark:text-gray-300">{visibleBatches.length}</span>}
          </div>
          <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">当前项目的生成批次会独立保留，可在这里暂停、继续或取消。</p>
        </div>
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => void batches.refetch()} disabled={batches.isFetching} className="rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs font-semibold text-gray-600 hover:bg-gray-50 disabled:opacity-50 dark:border-white/[0.1] dark:text-gray-300 dark:hover:bg-white/[0.05]">刷新</button>
          <button type="button" onClick={() => setExpanded((value) => !value)} className="rounded-lg px-2.5 py-1.5 text-xs font-semibold text-blue-600 hover:bg-blue-50 dark:text-blue-300 dark:hover:bg-blue-500/10">{expanded ? '收起' : '展开'}</button>
        </div>
      </div>

      {expanded && <div className="border-t border-gray-100 dark:border-white/[0.06]">
        {message && <div className="border-b border-gray-100 bg-gray-50 px-4 py-2 text-xs text-gray-600 dark:border-white/[0.06] dark:bg-white/[0.03] dark:text-gray-300">{message}</div>}
        {batches.isLoading && <div className="px-4 py-8 text-center text-sm text-gray-400">正在加载批次记录…</div>}
        {batches.isError && <div className="px-4 py-4 text-sm text-red-600">{batches.error.message}</div>}
        {!batches.isLoading && !batches.isError && !visibleBatches.length && <div className="px-4 py-8 text-center text-sm text-gray-400">当前项目还没有生成批次。</div>}
        <div className="divide-y divide-gray-100 dark:divide-white/[0.06]">
          {visibleBatches.map((item) => {
            const completed = terminalCount(item)
            const percentage = item.total_jobs ? Math.round(completed / item.total_jobs * 100) : 0
            const terminal = TERMINAL_STATUSES.has(item.status)
            const cancelling = isServerBatchCancelling(item)
            const displayStatus = cancelling ? 'cancel_requested' : item.status
            return <article key={item.id} className="px-4 py-3.5">
              <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <strong className="truncate text-sm text-gray-900 dark:text-gray-100">{item.name || `批次 ${item.id.slice(0, 8)}`}</strong>
                    <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${statusClass(displayStatus)}`}>{STATUS_LABELS[displayStatus] || displayStatus}</span>
                    <span className="text-sm font-bold tabular-nums text-gray-800 dark:text-gray-100">完成 {item.succeeded_jobs}/{item.total_jobs}</span>
                  </div>
                  <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-xs text-gray-500 dark:text-gray-400">
                    <span>{formatTime(item.created_at)}</span>
                    <span>已处理 {completed}/{item.total_jobs}</span>
                    <span>成功 {item.succeeded_jobs}</span>
                    <span>失败 {item.failed_jobs}</span>
                    <span>取消 {item.cancelled_jobs}</span>
                    <span>并发 {item.concurrency}</span>
                  </div>
                  <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-gray-100 dark:bg-white/[0.07]">
                    <div className="h-full rounded-full bg-blue-600 transition-all" style={{ width: `${percentage}%` }} />
                  </div>
                </div>
                {!terminal && !cancelling && <div className="flex shrink-0 items-center gap-2">
                  {item.status === 'paused'
                    ? auth.hasPermission('jobs.submit') && <button type="button" disabled={Boolean(busyKey)} onClick={() => void runAction(item, 'resume')} className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-500 disabled:opacity-50">继续</button>
                    : auth.hasPermission('jobs.cancel') && <button type="button" disabled={Boolean(busyKey)} onClick={() => void runAction(item, 'pause')} className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs font-semibold text-amber-700 hover:bg-amber-100 disabled:opacity-50 dark:border-amber-400/20 dark:bg-amber-500/10 dark:text-amber-200">暂停</button>}
                  {auth.hasPermission('jobs.cancel') && <button type="button" disabled={Boolean(busyKey)} onClick={() => void runAction(item, 'cancel')} className="rounded-lg border border-red-200 px-3 py-1.5 text-xs font-semibold text-red-600 hover:bg-red-50 disabled:opacity-50 dark:border-red-400/20 dark:text-red-300 dark:hover:bg-red-500/10">取消</button>}
                </div>}
                {cancelling && <span className="shrink-0 rounded-lg bg-amber-50 px-3 py-1.5 text-xs font-semibold text-amber-700 dark:bg-amber-500/10 dark:text-amber-200">正在取消，请稍候</span>}
                {terminal && auth.hasPermission('assets.delete') && auth.hasPermission('jobs.cancel') && <button
                  type="button"
                  disabled={Boolean(busyKey)}
                  onClick={() => void permanentlyDelete(item)}
                  className="shrink-0 rounded-lg border border-red-200 px-3 py-1.5 text-xs font-semibold text-red-600 hover:bg-red-50 disabled:opacity-50 dark:border-red-400/20 dark:text-red-300 dark:hover:bg-red-500/10"
                >永久删除</button>}
              </div>
            </article>
          })}
        </div>
      </div>}
    </section>
  )
}
