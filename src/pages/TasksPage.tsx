import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useAuth } from '../app/AuthContext'
import { cancelServerBatch, cancelServerJob, getServerBatch, listServerBatches, listServerJobs, type ServerJob, type ServerJobBatch } from '../lib/jobsApi'
import { downloadBatchTryOnResultsZip, downloadServerOutput, downloadServerOutputZip, withPartialExportConfirmation, downloadErrorMessage } from '../lib/serverDownloads'
import { DownloadIcon, HistoryIcon, RefreshIcon } from '../components/icons'
import {taskMetrics,taskStatusGroup as statusGroup,type TaskFilter as Filter} from '../lib/taskPresentation'

const statusLabel: Record<string, string> = {
  pending: '等待队列', dispatched: '等待队列', waiting_for_resource: '等待通道', running: '生成中', retry_waiting: '等待重试',
  succeeded: '已完成', failed: '失败', cancelled: '已取消', queued: '等待队列', paused: '已暂停', partially_succeeded: '部分成功',
  dispatching: '正在分发', waiting_resource: '等待通道', retrying: '正在重试',
}
const workspaceLabel: Record<string, string> = { listing: 'Listing 图', batch_tryon: '批量套图', aplus: 'A+ 图', material_extract: '素材提取' }
function time(value: string | null) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—' }
function statusClass(status: string) {
  if (status === 'succeeded') return 'bg-emerald-50 text-emerald-700'
  if (status === 'failed' || status === 'cancelled') return 'bg-red-50 text-red-700'
  if (status === 'partially_succeeded' || status === 'paused') return 'bg-amber-50 text-amber-700'
  return 'bg-stone-100 text-stone-600'
}
export default function TasksPage() {
  const auth = useAuth()
  const queryClient = useQueryClient()
  const [message, setMessage] = useState('')
  const [filter, setFilter] = useState<Filter>('all')
  const batches = useQuery({ queryKey: ['server-job-batches'], queryFn: () => listServerBatches({ limit: 50 }), refetchInterval: 3_000 })
  const jobs = useQuery({ queryKey: ['server-jobs'], queryFn: () => listServerJobs({ limit: 100 }), refetchInterval: 3_000 })
  const standaloneJobs = jobs.data?.items.filter((job) => !job.batch_id) ?? []
  const requestedBatch = new URLSearchParams(window.location.search).get('batch_id')
  const focusedBatch = useQuery({ queryKey: ['server-job-batches', requestedBatch], queryFn: () => getServerBatch(requestedBatch!), enabled: !!requestedBatch, refetchInterval: 3000 })
  const visibleBatches = focusedBatch.data ? [focusedBatch.data, ...(batches.data?.items || []).filter((batch) => batch.id !== focusedBatch.data.id)] : batches.data?.items || []
  useEffect(() => { if (requestedBatch && batches.data) document.getElementById(`batch-${requestedBatch}`)?.scrollIntoView({ block: 'center' }) }, [requestedBatch, batches.data, focusedBatch.data])
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['server-jobs'] })
    void queryClient.invalidateQueries({ queryKey: ['server-job-batches'] })
  }
  const cancelJob = useMutation({ mutationFn: cancelServerJob, onSuccess: () => { setMessage('已提交取消请求'); refresh() }, onError: (error) => setMessage(error.message) })
  const cancelBatch = useMutation({ mutationFn: cancelServerBatch, onSuccess: () => { setMessage('批次取消请求已提交'); refresh() }, onError: (error) => setMessage(error.message) })

  const downloadBatch = async (batch: ServerJobBatch) => {
    try {
      setMessage('正在打包成功结果…')
      if (batch.workspace_type === 'batch_tryon') {
        const result = await withPartialExportConfirmation((partial) => downloadBatchTryOnResultsZip(batch.id, partial))
        if (!result) { setMessage('已取消下载'); return }
      } else await downloadServerOutputZip(batch.jobs.flatMap((job) => job.outputs), `${batch.name || '生成批次'}.zip`)
      setMessage('下载已开始')
    } catch (error) { setMessage(downloadErrorMessage(error)) }
  }

  const metrics=taskMetrics(visibleBatches,standaloneJobs)
  const {active:activeCount,succeeded:successCount,failed:failedCount,outputs:outputCount}=metrics
  const filteredBatches = visibleBatches.filter((batch) => filter === 'all' || statusGroup(batch.status) === filter)
  const filteredStandalone = standaloneJobs.filter((job) => filter === 'all' || statusGroup(job.status) === filter)

  return <div className="studio-page mx-auto max-w-[1400px]">
    <header className="flex flex-wrap items-end justify-between gap-4"><div><p className="text-xs font-medium tracking-[0.14em] text-gray-500">TASK CENTER</p><h1 className="mt-2 text-2xl font-semibold tracking-[-0.03em] text-gray-950">任务与生成</h1><p className="mt-2 text-sm text-gray-500">查看生成进度、处理失败任务并下载结果，离开页面不会中断任务。</p></div><button onClick={refresh} className="inline-flex min-h-10 items-center gap-2 rounded-full border border-black/10 bg-white px-4 text-xs font-medium text-gray-700 shadow-sm hover:bg-stone-50"><RefreshIcon className="h-4 w-4" />刷新状态</button></header>
    <div className="mt-7 grid grid-cols-2 gap-3 lg:grid-cols-4">{[
      ['进行中', activeCount, 'text-stone-900'], ['已成功', successCount, 'text-emerald-700'], ['失败', failedCount, 'text-red-600'], ['可下载结果', outputCount, 'text-stone-900'],
    ].map(([label, value, color]) => <div key={String(label)} className="rounded-2xl border border-black/[0.07] bg-white p-4 shadow-sm"><p className="text-xs text-gray-500">{label}</p><p className={`mt-2 text-2xl font-semibold ${color}`}>{value}</p></div>)}</div>
    <div className="mt-6 flex flex-wrap items-center justify-between gap-3"><div aria-label="任务状态筛选" className="flex flex-wrap gap-1 rounded-2xl border border-black/[0.07] bg-white p-1">{([['all', '全部'], ['active', '进行中'], ['succeeded', '已完成'], ['failed', '失败'], ['cancelled','已取消'], ['paused','已暂停']] as const).map(([value, label]) => <button key={value} type="button" aria-pressed={filter===value} onClick={() => setFilter(value)} className="studio-filter">{label}</button>)}</div>{message && <p role="status" className="text-xs text-gray-600">{message}</p>}</div>
    {(batches.isLoading || jobs.isLoading) && <div className="mt-5 rounded-2xl border border-black/[0.07] bg-white py-16 text-center text-sm text-gray-500">正在同步任务…</div>}
    {(batches.isError || jobs.isError) && <div className="mt-5 rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{batches.error?.message || jobs.error?.message}</div>}
    {focusedBatch.error && <p role="alert" className="mt-4 text-sm text-red-600">当前任务无法打开：{focusedBatch.error.message}</p>}
    <div className="mt-5 space-y-4">{filteredBatches.map((batch) => {
      const completed = batch.succeeded_jobs + batch.failed_jobs + batch.cancelled_jobs
      const canCancel = !['succeeded', 'failed', 'cancelled', 'partially_succeeded'].includes(batch.status)
      return <section key={batch.id} id={`batch-${batch.id}`} className={`overflow-hidden rounded-[20px] border bg-white shadow-sm ${requestedBatch === batch.id ? 'border-stone-500 ring-2 ring-stone-200' : 'border-black/[0.07]'}`}>
        <div className="flex flex-col gap-3 border-b border-black/[0.06] px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
          <div><div className="flex flex-wrap items-center gap-2"><h2 className="text-sm font-semibold text-gray-900">{batch.name || '未命名批次'}</h2><span className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${statusClass(batch.status)}`}>{statusLabel[batch.status] ?? batch.status}</span></div><p className="mt-1.5 text-xs text-gray-500">{workspaceLabel[batch.workspace_type]} · {time(batch.created_at)} · 并发 {batch.concurrency}</p></div>
          <div className="flex gap-2">{batch.succeeded_jobs > 0 && <button onClick={() => void downloadBatch(batch)} className="inline-flex min-h-9 items-center gap-1.5 rounded-full border border-black/10 px-3 text-xs font-medium text-gray-700"><DownloadIcon className="h-3.5 w-3.5" />下载结果</button>}{auth.hasPermission('jobs.cancel') && canCancel && <button onClick={() => cancelBatch.mutate(batch.id)} disabled={cancelBatch.isPending} className="min-h-9 rounded-full border border-red-200 px-3 text-xs font-medium text-red-600 disabled:opacity-50">取消批次</button>}</div>
        </div>
        <div className="px-4 py-4 sm:px-5"><div className="flex justify-between text-xs text-gray-500"><span>完成 {completed}/{batch.total_jobs}</span><span>成功 {batch.succeeded_jobs} · 失败 {batch.failed_jobs} · 取消 {batch.cancelled_jobs}</span></div><div className="mt-2.5 h-1.5 overflow-hidden rounded-full bg-stone-100"><div className="h-full rounded-full bg-stone-700 transition-all" style={{ width: `${batch.total_jobs ? completed / batch.total_jobs * 100 : 0}%` }} /></div></div>
        <div className="divide-y divide-black/[0.055] border-t border-black/[0.055]">{batch.jobs.map((job, index) => <JobRow key={job.id} job={job} index={index} canCancel={auth.hasPermission('jobs.cancel')} onCancel={() => cancelJob.mutate(job.id)} onMessage={setMessage} />)}</div>
      </section>
    })}</div>
    {filteredStandalone.length > 0 && <section className="mt-5 overflow-hidden rounded-[20px] border border-black/[0.07] bg-white shadow-sm"><div className="flex items-center gap-2 border-b border-black/[0.06] px-5 py-4 text-sm font-semibold"><HistoryIcon className="h-4 w-4 text-gray-400" />单任务</div><div className="divide-y divide-black/[0.055]">{filteredStandalone.map((job, index) => <JobRow key={job.id} job={job} index={index} canCancel={auth.hasPermission('jobs.cancel')} onCancel={() => cancelJob.mutate(job.id)} onMessage={setMessage} />)}</div></section>}
    {!batches.isLoading && !jobs.isLoading && !filteredBatches.length && !filteredStandalone.length && <div className="mt-5 rounded-[20px] border border-dashed border-black/10 py-16 text-center text-sm text-gray-500">{filter === 'all' ? '暂无服务端任务' : '当前筛选下没有任务'}</div>}
  </div>
}

function JobRow({ job, index, canCancel, onCancel, onMessage }: { job: ServerJob; index: number; canCancel: boolean; onCancel: () => void; onMessage: (value: string) => void }) {
  const active = !['succeeded', 'failed', 'cancelled'].includes(job.status)
  const waiting = ['pending', 'queued', 'dispatched', 'waiting_for_resource', 'retry_waiting'].includes(job.status)
  const detail = waiting ? (statusLabel[job.status] ?? '等待队列中') : job.error_message || `进度 ${job.progress}%`
  return <div className="flex flex-col gap-3 px-4 py-3.5 sm:flex-row sm:items-center sm:justify-between sm:px-5"><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><span className="text-xs font-medium text-gray-800">#{index + 1} {job.client_item_id || job.operation_code}</span><span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${statusClass(job.status)}`}>{statusLabel[job.status] ?? job.status}</span></div><p className="mt-1 text-[11px] text-gray-500">尝试 {job.attempts}/{job.max_attempts} · {detail}</p></div><div className="flex flex-wrap gap-2">{job.outputs.map((output) => <button key={output.id} onClick={() => void downloadServerOutput(output).catch((error) => onMessage(error.message))} className="inline-flex min-h-8 items-center gap-1 rounded-full border border-black/10 px-2.5 text-[11px] font-medium text-gray-700"><DownloadIcon className="h-3 w-3" />下载</button>)}{canCancel && active && <button onClick={onCancel} className="min-h-8 rounded-full px-2.5 text-[11px] font-medium text-red-600">取消</button>}</div></div>
}
