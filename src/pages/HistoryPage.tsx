import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { listServerJobs, type JobOutput } from '../lib/jobsApi'
import { downloadServerOutput, downloadServerOutputZip } from '../lib/serverDownloads'
import AuthenticatedImage from '../components/AuthenticatedImage'

const workspaceLabel: Record<string, string> = {
  listing: 'Listing 图', batch_tryon: '批量套图', aplus: 'A+ 图', material_extract: '素材提取',
}

export default function HistoryPage() {
  const [message, setMessage] = useState('')
  const history = useQuery({ queryKey: ['server-jobs', 'succeeded'], queryFn: () => listServerJobs({ status: 'succeeded', limit: 100 }), refetchInterval: 10_000 })
  const outputs = history.data?.items.flatMap((job) => job.outputs.map((output) => ({ output, job }))) ?? []
  const downloadAll = async () => {
    try { setMessage('正在打包…'); await downloadServerOutputZip(outputs.map((item) => item.output), '生成历史.zip'); setMessage('下载已开始') }
    catch (error) { setMessage(error instanceof Error ? error.message : '下载失败') }
  }
  return <div className="mt-6 space-y-5">
    <section className="flex flex-col gap-4 rounded-2xl border border-gray-200 bg-white p-5 shadow-sm dark:border-white/[0.08] dark:bg-gray-900 sm:flex-row sm:items-center sm:justify-between"><div><h1 className="text-xl font-bold text-gray-950 dark:text-white">生成历史</h1><p className="mt-1 text-sm text-gray-500 dark:text-gray-400">成功结果已归档到团队素材中心，并通过同源鉴权接口展示。</p>{message && <div className="mt-2 text-xs text-gray-600 dark:text-gray-300">{message}</div>}</div>{outputs.length > 0 && <button onClick={() => void downloadAll()} className="rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white">批量下载全部</button>}</section>
    {history.isLoading && <div className="py-16 text-center text-sm text-gray-500">正在加载生成历史…</div>}
    {history.isError && <div className="rounded-xl bg-red-50 p-4 text-sm text-red-700">{history.error.message}</div>}
    {!history.isLoading && outputs.length === 0 && <div className="rounded-2xl border border-dashed border-gray-200 py-16 text-center text-sm text-gray-500 dark:border-white/[0.08]">暂无成功结果</div>}
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{outputs.map(({ output, job }) => <HistoryCard key={output.id} output={output} workspace={job.workspace_type} createdAt={job.created_at} onMessage={setMessage} />)}</div>
  </div>
}

function HistoryCard({ output, workspace, createdAt, onMessage }: { output: JobOutput; workspace: string; createdAt: string; onMessage: (value: string) => void }) {
  return <article className="overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm dark:border-white/[0.08] dark:bg-gray-900"><div className="aspect-square bg-gray-100 dark:bg-gray-950"><AuthenticatedImage src={output.url} alt={output.filename} loading="lazy" className="h-full w-full object-contain" /></div><div className="p-3"><div className="truncate text-sm font-semibold text-gray-900 dark:text-white">{output.filename}</div><div className="mt-1 text-xs text-gray-500">{workspaceLabel[workspace] ?? workspace} · {output.width}×{output.height}</div><div className="mt-1 text-xs text-gray-400">{new Date(createdAt).toLocaleString('zh-CN', { hour12: false })}</div><button onClick={() => void downloadServerOutput(output).catch((error) => onMessage(error.message))} className="mt-3 text-xs font-semibold text-blue-600 dark:text-blue-300">下载图片</button></div></article>
}
