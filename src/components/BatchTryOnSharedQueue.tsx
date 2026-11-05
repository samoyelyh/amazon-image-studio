import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useAuth } from '../app/AuthContext'
import BatchTryOnQueueSettings from './BatchTryOnQueueSettings'
import {
  formatQueueWait, getSharedBatchTryOnQueue, restoreQueueBatch, type SharedQueueBoard, type SharedQueueEntry,
} from '../lib/batchTryOnSharedQueueApi'

const labels: Record<string, string> = { draft: '待配置', analyzing: 'AI分析准备中', running: '执行中', queued: '等待中',
  paused: '已暂停', completed: '已完成', cancelled: '已取消', failed: '有失败任务', archived: '已自动归档' }

export function SharedQueueView({ board, onOpen, onRestore }: { board: SharedQueueBoard; onOpen: (entry: SharedQueueEntry) => void; onRestore?: (entry: SharedQueueEntry) => void }) {
  return <div className="overflow-hidden rounded-xl border border-gray-200 dark:border-white/10">
    <table className="hidden w-full text-left text-xs xl:table">
      <thead className="bg-gray-50 text-gray-500 dark:bg-white/[0.035]"><tr>
        {['标签 / 创建人', '状态与进度', '运行 / 等待', '排队与预计等待', '访问权限'].map((name) => <th key={name} className="px-4 py-3 font-medium">{name}</th>)}
      </tr></thead>
      <tbody className="divide-y divide-gray-100 dark:divide-white/[0.06]">{board.entries.map((entry) => <tr key={entry.id}>
        <td className="max-w-[260px] px-4 py-4"><div className="truncate text-sm font-semibold text-gray-900 dark:text-gray-100">{entry.name}</div>
          <div className="mt-1 text-gray-500">{entry.creator_name} · {new Date(entry.created_at).toLocaleString('zh-CN', { hour12: false })}</div></td>
        <td className="min-w-[155px] px-4 py-4"><span className="rounded-md bg-gray-100 px-2 py-1 text-gray-600 dark:bg-white/5 dark:text-gray-300">{labels[entry.status] || entry.status}</span>
          <div className="mt-2 font-medium text-gray-800 dark:text-gray-200">{entry.total_count ? `完成 ${entry.completed_count}/${entry.total_count}` : '尚未创建图片任务'}</div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-gray-100 dark:bg-white/5"><div className="h-full bg-blue-600" style={{ width: `${entry.progress_percent}%` }} /></div>
          <div className="mt-1 text-[11px] text-gray-500">已处理 {entry.processed_count} · 失败 {entry.failed_count} · 取消 {entry.cancelled_count}</div></td>
        <td className="px-4 py-4 text-gray-600 dark:text-gray-300">运行 {entry.running_count} · 等待 {entry.waiting_count}
          <div className="mt-1 text-[11px] text-gray-500">重试 {entry.retrying_count} · 分析 {entry.analysis_running} · 样图/编辑 {entry.auxiliary_running}</div></td>
        <td className="max-w-[270px] px-4 py-4 text-gray-700 dark:text-gray-300"><div>{entry.ahead_count == null ? '不在可调度队列中' : `前方约 ${entry.ahead_count} 个共享资源请求`}</div>
          <div className="mt-1 font-medium">{formatQueueWait(entry.estimate)}</div><div className="mt-1 text-[11px] leading-5 text-gray-500">{entry.estimate.reason}</div></td>
        <td className="px-4 py-4">{entry.archived && entry.can_open && onRestore
          ? <button onClick={() => onRestore(entry)} className="rounded-lg border px-3 py-2 text-blue-600">恢复到队列</button> : entry.can_open && entry.navigation
          ? <button type="button" onClick={() => onOpen(entry)} className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 font-semibold text-blue-600">进入我的任务</button>
          : <button type="button" disabled aria-label={`${entry.name} 仅创建人可进入`} className="cursor-not-allowed rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-gray-400 dark:border-white/10 dark:bg-white/5">🔒 仅创建人可进入</button>}</td>
      </tr>)}</tbody>
    </table>
    <div className="divide-y divide-gray-100 xl:hidden dark:divide-white/10">{board.entries.map((entry) => <article key={entry.id} className="space-y-3 p-4">
      <div className="flex flex-wrap items-start justify-between gap-2"><div>
        <h3 className="text-sm font-semibold text-gray-900 dark:text-white">{entry.name}</h3>
        <p className="mt-1 text-xs text-gray-500">{entry.creator_name} · {new Date(entry.created_at).toLocaleString('zh-CN', { hour12: false })}</p>
      </div><span className="rounded-md bg-gray-100 px-2 py-1 text-xs text-gray-600 dark:bg-white/5 dark:text-gray-300">{labels[entry.status] || entry.status}</span></div>
      <div className="h-1.5 overflow-hidden rounded-full bg-gray-100 dark:bg-white/5"><div className="h-full bg-blue-600" style={{ width: `${entry.progress_percent}%` }} /></div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-600 dark:text-gray-300">
        <span>完成 {entry.completed_count}/{entry.total_count}</span><span>运行 {entry.running_count}</span><span>等待 {entry.waiting_count}</span>
        <span>失败 {entry.failed_count}</span><span>取消 {entry.cancelled_count}</span><span>重试 {entry.retrying_count}</span><span>分析 {entry.analysis_running}</span>
      </div>
      <div className="text-xs text-gray-600 dark:text-gray-300">{entry.ahead_count == null ? '不在可调度队列中' : `前方约 ${entry.ahead_count} 个共享资源请求`} · {formatQueueWait(entry.estimate)}
        <p className="mt-1 leading-5 text-gray-500">{entry.estimate.reason}</p></div>
      {entry.archived && entry.can_open && onRestore ? <button onClick={() => onRestore(entry)} className="rounded-lg border px-3 py-2 text-xs text-blue-600">恢复到队列</button> : entry.can_open && entry.navigation ? <button type="button" onClick={() => onOpen(entry)} className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-xs font-semibold text-blue-600">进入我的任务</button>
        : <button type="button" disabled aria-label={`${entry.name} 仅创建人可进入`} className="cursor-not-allowed rounded-lg border border-gray-200 px-3 py-2 text-xs text-gray-400 dark:border-white/10">🔒 仅创建人可进入</button>}
    </article>)}</div>
    {!board.entries.length && <div className="px-4 py-10 text-center text-sm text-gray-400">当前团队暂无批量套图标签或任务。</div>}
    {board.truncated && <p className="px-4 py-3 text-xs text-amber-700">只显示最近的部分标签；顶部统计以本次摘要范围为准。</p>}
  </div>
}

export default function BatchTryOnSharedQueue({ mode, onModeChange, onOpen }: {
  mode: 'mine' | 'all'; onModeChange: (mode: 'mine' | 'all') => void; onOpen: (entry: SharedQueueEntry) => void
}) {
  const auth = useAuth()
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [includeArchived, setIncludeArchived] = useState(false)
  const [notice, setNotice] = useState('')
  const queue = useQuery({ queryKey: ['batch-tryon', 'shared-queue', auth.identity?.organization?.id, auth.identity?.user.id, includeArchived],
    queryFn: ({ signal }) => getSharedBatchTryOnQueue(signal, includeArchived), enabled: Boolean(auth.identity?.organization),
    refetchInterval: 5_000, staleTime: 2_000, retry: 1 })
  const board = queue.data
  return <section className="mb-4 rounded-2xl border border-gray-200 bg-white p-4 shadow-sm dark:border-white/[0.08] dark:bg-gray-950" aria-label="团队生成队列">
    <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-sm font-semibold text-gray-900 dark:text-white">团队生成队列</h2>
      <p className="mt-1 text-xs text-gray-500">每5秒更新摘要；同事只可见状态，不可见图片、提示词或下载链接。</p></div>
      <div className="flex flex-wrap items-center gap-2"><button type="button" onClick={() => setSettingsOpen(true)} className="rounded-lg border border-gray-200 px-3 py-2 text-xs font-semibold text-gray-600 dark:border-white/10 dark:text-gray-300">队列清理设置</button><div className="flex rounded-lg bg-gray-100 p-1 dark:bg-white/5">{([['mine', '我的任务'], ['all', '全员队列']] as const).map(([value, label]) =>
        <button key={value} type="button" onClick={() => onModeChange(value)} aria-pressed={mode === value}
          className={`rounded-md px-4 py-2 text-xs font-semibold ${mode === value ? 'bg-white text-blue-600 shadow-sm dark:bg-gray-800' : 'text-gray-500'}`}>{label}</button>)}</div></div>
    </div>
    {board && <div className="my-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{[
      ['正在生成', `${board.running_count} 张`, `另有 ${board.analysis_running} 个AI分析执行中`],
      ['等待生图', `${board.waiting_count} 张`, '分析与图片不重复累计'],
      ['实际资源占用', `${board.capacity.in_use} / ${board.capacity.effective}`, `配置容量 ${board.capacity.configured}；${board.capacity.reason}`],
      ['预计等待', !board.capacity.effective ? '等待资源恢复' : board.waiting_count ? '按标签显示区间' : '暂无排队', '综合历史耗时与共享槽位，不使用页面目标并发计算'],
    ].map(([label, value, description]) => <div key={label} className="rounded-xl border border-gray-100 bg-gray-50/60 p-3 dark:border-white/5 dark:bg-white/[0.025]">
      <div className="text-xs text-gray-500">{label}</div><div className="mt-1 text-xl font-semibold text-gray-900 dark:text-white">{value}</div><div className="mt-1 text-[11px] leading-5 text-gray-500">{description}</div></div>)}</div>}
    {queue.isError && <p role="alert" className="mt-3 text-xs text-red-600">全员队列读取失败，原有任务不受影响。<button type="button" onClick={() => void queue.refetch()} className="ml-2 underline">重新读取</button></p>}
    {mode === 'all' && <label className="mb-3 flex items-center gap-2 text-xs text-gray-500"><input type="checkbox" checked={includeArchived} onChange={(e) => setIncludeArchived(e.target.checked)} />显示已自动归档的批次（永久删除不可恢复）</label>}
    {notice && <p role="status" className="my-2 text-xs text-gray-500">{notice}</p>}
    {mode === 'all' && (board ? <SharedQueueView board={board} onOpen={onOpen} onRestore={(entry) => {
      void restoreQueueBatch(entry.id).then(() => { setNotice('已恢复到队列，暂停任务请由创建人手动继续。'); void queue.refetch() }).catch((e) => setNotice(e.message))
    }} /> : <p className="py-5 text-xs text-gray-500">正在读取队列摘要…</p>)}
    {settingsOpen && <BatchTryOnQueueSettings onClose={() => setSettingsOpen(false)} onChanged={() => void queue.refetch()} />}
  </section>
}
