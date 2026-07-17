import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { useAuth } from '../app/AuthContext'
import { cancelServerBatch, cancelServerJob, listServerBatches, listServerJobs, type ServerJob } from '../lib/jobsApi'
import { downloadServerOutput, downloadServerOutputZip } from '../lib/serverDownloads'

const statusLabel: Record<string, string> = {
  pending: '等待调度', dispatched: '已入队', running: '生成中', retry_waiting: '等待重试',
  succeeded: '已完成', failed: '失败', cancelled: '已取消', queued: '排队中', paused: '已暂停', partially_succeeded: '部分成功',
}
const workspaceLabel: Record<string, string> = { listing: 'Listing 图', batch_tryon: '批量套图', aplus: 'A+ 图' }

function time(value: string | null) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'
}

function statusClass(status: string) {
  if (status === 'succeeded') return 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-200'
  if (status === 'failed' || status === 'cancelled') return 'bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-200'
  if (status === 'partially_succeeded' || status === 'paused') return 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-200'
  return 'bg-blue-50 text-blue-700 dark:bg-blue-500/10 dark:text-blue-200'
}

export default function TasksPage() {
  const auth = useAuth()
  const queryClient = useQueryClient()
  const [message, setMessage] = useState('')
  const batches = useQuery({ queryKey: ['server-job-batches'], queryFn: () => listServerBatches({ limit: 50 }), refetchInterval: 3_000 })
  const jobs = useQuery({ queryKey: ['server-jobs'], queryFn: () => listServerJobs({ limit: 100 }), refetchInterval: 3_000 })
  const batchedIds = useMemo(() => new Set(batches.data?.items.flatMap((batch) => batch.jobs.map((job) => job.id)) ?? []), [batches.data])
  const standaloneJobs = jobs.data?.items.filter((job) => !batchedIds.has(job.id)) ?? []
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['server-jobs'] })
    void queryClient.invalidateQueries({ queryKey: ['server-job-batches'] })
  }
  const cancelJob = useMutation({ mutationFn: cancelServerJob, onSuccess: () => { setMessage('已提交取消请求'); refresh() }, onError: (error) => setMessage(error.message) })
  const cancelBatch = useMutation({ mutationFn: cancelServerBatch, onSuccess: () => { setMessage('批次取消请求已提交'); refresh() }, onError: (error) => setMessage(error.message) })

  const downloadBatch = async (name: string, batchJobs: ServerJob[]) => {
    try {
      setMessage('正在打包成功结果…')
      await downloadServerOutputZip(batchJobs.flatMap((job) => job.outputs), `${name || '生成批次'}.zip`)
      setMessage('下载已开始')
    } catch (error) { setMessage(error instanceof Error ? error.message : '下载失败') }
  }

  return (
    <div className="mt-6 space-y-5">
      <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm dark:border-white/[0.08] dark:bg-gray-900">
        <h1 className="text-xl font-bold text-gray-950 dark:text-white">任务中心</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">服务端统一执行 Listing、批量套图与 A+ 任务；刷新或关闭页面不会中断生成。</p>
        {message && <div className="mt-3 text-sm text-gray-600 dark:text-gray-300">{message}</div>}
      </section>

      {(batches.isLoading || jobs.isLoading) && <div className="rounded-2xl border border-gray-200 bg-white py-16 text-center text-sm text-gray-500 dark:border-white/[0.08] dark:bg-gray-900">正在同步任务…</div>}
      {(batches.isError || jobs.isError) && <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{batches.error?.message || jobs.error?.message}</div>}

      {batches.data?.items.map((batch) => {
        const completed = batch.succeeded_jobs + batch.failed_jobs + batch.cancelled_jobs
        const canCancel = !['succeeded', 'failed', 'cancelled', 'partially_succeeded'].includes(batch.status)
        return <section key={batch.id} className="overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm dark:border-white/[0.08] dark:bg-gray-900">
          <div className="flex flex-col gap-3 border-b border-gray-100 px-5 py-4 dark:border-white/[0.06] sm:flex-row sm:items-center sm:justify-between">
            <div><div className="flex flex-wrap items-center gap-2"><h2 className="font-bold text-gray-950 dark:text-white">{batch.name || '未命名批次'}</h2><span className={`rounded-full px-2 py-1 text-xs font-semibold ${statusClass(batch.status)}`}>{statusLabel[batch.status] ?? batch.status}</span></div><div className="mt-1 text-xs text-gray-500">{workspaceLabel[batch.workspace_type]} · {time(batch.created_at)} · 并发 {batch.concurrency}</div></div>
            <div className="flex gap-2">
              {batch.succeeded_jobs > 0 && <button onClick={() => void downloadBatch(batch.name || '生成批次', batch.jobs)} className="rounded-xl border border-emerald-200 px-3 py-2 text-xs font-semibold text-emerald-700 dark:border-emerald-400/20 dark:text-emerald-200">批量下载</button>}
              {auth.hasPermission('jobs.cancel') && canCancel && <button onClick={() => cancelBatch.mutate(batch.id)} disabled={cancelBatch.isPending} className="rounded-xl border border-red-200 px-3 py-2 text-xs font-semibold text-red-600 disabled:opacity-50">取消批次</button>}
            </div>
          </div>
          <div className="px-5 py-4"><div className="flex justify-between text-xs text-gray-500"><span>完成 {completed}/{batch.total_jobs}</span><span>成功 {batch.succeeded_jobs} · 失败 {batch.failed_jobs} · 取消 {batch.cancelled_jobs}</span></div><div className="mt-2 h-2 overflow-hidden rounded-full bg-gray-100 dark:bg-white/[0.06]"><div className="h-full rounded-full bg-blue-600 transition-all" style={{ width: `${batch.total_jobs ? completed / batch.total_jobs * 100 : 0}%` }} /></div></div>
          <div className="divide-y divide-gray-100 dark:divide-white/[0.06]">{batch.jobs.map((job, index) => <JobRow key={job.id} job={job} index={index} canCancel={auth.hasPermission('jobs.cancel')} onCancel={() => cancelJob.mutate(job.id)} onMessage={setMessage} />)}</div>
        </section>
      })}

      {standaloneJobs.length > 0 && <section className="overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm dark:border-white/[0.08] dark:bg-gray-900"><div className="border-b border-gray-100 px-5 py-4 font-bold text-gray-950 dark:border-white/[0.06] dark:text-white">单任务</div><div className="divide-y divide-gray-100 dark:divide-white/[0.06]">{standaloneJobs.map((job, index) => <JobRow key={job.id} job={job} index={index} canCancel={auth.hasPermission('jobs.cancel')} onCancel={() => cancelJob.mutate(job.id)} onMessage={setMessage} />)}</div></section>}
      {!batches.isLoading && !jobs.isLoading && !batches.data?.items.length && !standaloneJobs.length && <div className="rounded-2xl border border-dashed border-gray-200 py-16 text-center text-sm text-gray-500 dark:border-white/[0.08]">暂无服务端任务</div>}
    </div>
  )
}

function JobRow({ job, index, canCancel, onCancel, onMessage }: { job: ServerJob; index: number; canCancel: boolean; onCancel: () => void; onMessage: (value: string) => void }) {
  const active = !['succeeded', 'failed', 'cancelled'].includes(job.status)
  return <div className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center sm:justify-between"><div className="min-w-0"><div className="flex items-center gap-2"><span className="text-sm font-semibold text-gray-900 dark:text-white">#{index + 1} {job.client_item_id || job.operation_code}</span><span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${statusClass(job.status)}`}>{statusLabel[job.status] ?? job.status}</span></div><div className="mt-1 text-xs text-gray-500">尝试 {job.attempts}/{job.max_attempts} · {job.error_message || `进度 ${job.progress}%`}</div></div><div className="flex flex-wrap gap-2">{job.outputs.map((output) => <button key={output.id} onClick={() => void downloadServerOutput(output).catch((error) => onMessage(error.message))} className="rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs font-semibold text-gray-700 dark:border-white/[0.1] dark:text-gray-200">下载结果</button>)}{canCancel && active && <button onClick={onCancel} className="rounded-lg px-2.5 py-1.5 text-xs font-semibold text-red-600">取消</button>}</div></div>
}
