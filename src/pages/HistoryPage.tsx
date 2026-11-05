import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { listServerJobs, type JobOutput } from '../lib/jobsApi'
import { downloadServerOutput, downloadServerOutputZip } from '../lib/serverDownloads'
import AuthenticatedImage from '../components/AuthenticatedImage'
import { DownloadIcon } from '../components/icons'

const workspaceLabel: Record<string, string> = { listing: 'Listing 图', batch_tryon: '批量套图', aplus: 'A+ 图', material_extract: '素材提取' }

export default function HistoryPage() {
  const [message, setMessage] = useState('')
  const history = useQuery({ queryKey: ['server-jobs', 'succeeded'], queryFn: () => listServerJobs({ status: 'succeeded', limit: 100 }), refetchInterval: 10_000 })
  const outputs = history.data?.items.flatMap((job) => job.outputs.map((output) => ({ output, job }))) ?? []
  const downloadAll = async () => {
    try { setMessage('正在打包…'); await downloadServerOutputZip(outputs.map((item) => item.output), '生成历史.zip'); setMessage('下载已开始') }
    catch (error) { setMessage(error instanceof Error ? error.message : '下载失败') }
  }
  return <div className="mx-auto max-w-[1500px] pb-8 pt-7 sm:pt-9">
    <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between"><div><p className="text-xs font-medium text-gray-500">CREATION HISTORY</p><h1 className="mt-2 text-2xl font-semibold tracking-[-0.03em] text-white">生成历史</h1><p className="mt-2 text-sm text-gray-500">查看、下载和复用团队已经完成的图片作品。</p>{message && <p className="mt-2 text-xs text-gray-300">{message}</p>}</div>{outputs.length > 0 && <button onClick={() => void downloadAll()} className="inline-flex min-h-10 items-center justify-center gap-2 rounded-full bg-white px-4 text-xs font-semibold text-gray-950"><DownloadIcon className="h-4 w-4" />下载全部</button>}</header>
    {history.isLoading && <div className="py-20 text-center text-sm text-gray-500">正在加载生成历史…</div>}
    {history.isError && <div className="mt-5 rounded-2xl bg-red-500/10 p-4 text-sm text-red-300">{history.error.message}</div>}
    {!history.isLoading && outputs.length === 0 && <div className="mt-6 rounded-[20px] border border-dashed border-white/10 py-20 text-center text-sm text-gray-500">暂无成功结果</div>}
    <div className="mt-6 grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-3 2xl:grid-cols-4">{outputs.map(({ output, job }) => <HistoryCard key={output.id} output={output} workspace={job.workspace_type} createdAt={job.created_at} onMessage={setMessage} />)}</div>
  </div>
}

function HistoryCard({ output, workspace, createdAt, onMessage }: { output: JobOutput; workspace: string; createdAt: string; onMessage: (value: string) => void }) {
  return <article className="lovart-image-card group">
    <div className="relative aspect-square overflow-hidden bg-[#242424]"><AuthenticatedImage src={output.url} alt={output.filename} loading="lazy" className="h-full w-full object-contain" /><button aria-label={`下载 ${output.filename}`} onClick={() => void downloadServerOutput(output).catch((error) => onMessage(error.message))} className="absolute bottom-3 right-3 flex h-9 w-9 items-center justify-center rounded-full bg-black/55 text-white opacity-100 backdrop-blur transition hover:bg-black/75 sm:opacity-0 sm:group-hover:opacity-100"><DownloadIcon className="h-4 w-4" /></button></div>
    <div className="p-3.5"><div className="truncate text-xs font-medium text-gray-200">{output.filename}</div><div className="mt-1.5 flex items-center justify-between gap-2 text-[10px] text-gray-500"><span>{workspaceLabel[workspace] ?? workspace} · {output.width}×{output.height}</span><span>{new Date(createdAt).toLocaleDateString('zh-CN')}</span></div></div>
  </article>
}
