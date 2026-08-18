import { useRef, useState } from 'react'
import type { BatchTryOnBatchDetailedAnalysisResponse } from '../lib/batchTryOnReviewApi'
import { summarizeBatchTryOnSelection, type SelectedBatchTryOnReviewItem } from '../lib/batchTryOnBulkActions'

interface Props {
  selected: SelectedBatchTryOnReviewItem[]
  invalidCount: number
  onClose: () => void
  onSubmit: (input: { autoRegenerate: boolean }) => Promise<BatchTryOnBatchDetailedAnalysisResponse>
}

export default function BatchTryOnBulkLunaDialog({ selected, invalidCount, onClose, onSubmit }: Props) {
  const [autoRegenerate, setAutoRegenerate] = useState(true)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const lock = useRef(false)
  const summary = summarizeBatchTryOnSelection(selected)

  const submit = async () => {
    if (!selected.length || lock.current) return
    if (!window.confirm(`将为 ${selected.length} 张图片分别执行 Luna 精细分析${autoRegenerate ? '，分析成功后自动重新生成' : ''}，是否继续？`)) return
    lock.current = true
    setBusy(true)
    setMessage('正在创建 Luna 批量分析任务…')
    try {
      const result = await onSubmit({ autoRegenerate })
      if (result.failed_count) {
        setMessage(`已提交 ${result.analysis_tasks.length} 张，失败 ${result.failed_count} 张：${result.errors.map((item) => item.message).join('；')}`)
        return
      }
      onClose()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Luna 批量分析提交失败')
    } finally {
      lock.current = false
      setBusy(false)
    }
  }

  return <div className="fixed inset-0 z-[115] flex items-center justify-center bg-gray-950/70 p-4" role="dialog" aria-modal="true" aria-label="Luna 批量精细分析并重新生成">
    <div className="w-full max-w-2xl rounded-2xl bg-white p-5 shadow-2xl dark:bg-gray-900">
      <div className="flex items-start justify-between gap-4"><div><h2 className="text-lg font-bold">Luna 批量精细分析</h2><p className="mt-2 text-sm text-gray-600 dark:text-gray-300">已选 {summary.itemCount} 张 · {summary.templateCount} 个模板 · {summary.garmentCount} 件服装</p></div><button type="button" disabled={busy} onClick={onClose} className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm dark:border-white/10">关闭</button></div>
      {invalidCount > 0 && <div className="mt-4 rounded-xl bg-amber-50 px-3 py-2.5 text-sm text-amber-800 dark:bg-amber-500/10 dark:text-amber-200">另有 {invalidCount} 张当前版本不可分析，本次会自动跳过。</div>}
      <div className="mt-4 rounded-xl border border-violet-200 bg-violet-50 p-3 text-sm leading-6 text-violet-800 dark:border-violet-500/30 dark:bg-violet-500/10 dark:text-violet-200">每张图片独立使用自己的模板图、实际服装参考图、图C（如有）和当前模板预设。Luna 只执行该预设原文，不会追加统一分析重点或其他包装提示词。</div>
      <label className="mt-4 flex items-start gap-3 rounded-xl border border-blue-200 p-3 dark:border-blue-500/30"><input type="checkbox" className="mt-1" checked={autoRegenerate} disabled={busy} onChange={(event) => setAutoRegenerate(event.target.checked)} /><span><span className="block text-sm font-bold">分析完成后自动重新生成图片</span><span className="mt-1 block text-xs leading-5 text-gray-500">推荐开启。每个 Luna 任务成功后，服务端自动把该图片的完整分析提示词提交到统一生图资源池；关闭页面或刷新不会中断。</span></span></label>
      {message && <div className={`mt-3 rounded-xl px-3 py-2.5 text-sm ${busy ? 'bg-blue-50 text-blue-700' : 'bg-red-50 text-red-700'}`}>{message}</div>}
      <div className="mt-5 flex justify-end gap-2"><button type="button" disabled={busy} onClick={onClose} className="rounded-xl border border-gray-200 px-4 py-2.5 text-sm font-semibold dark:border-white/10">取消</button><button type="button" disabled={busy || !selected.length} onClick={() => void submit()} className="rounded-xl bg-violet-600 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50">{busy ? '正在提交…' : `开始批量分析${autoRegenerate ? '并自动重生成' : ''}（${selected.length}）`}</button></div>
    </div>
  </div>
}
