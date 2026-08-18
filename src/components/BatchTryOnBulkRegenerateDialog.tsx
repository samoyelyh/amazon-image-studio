import { useRef, useState } from 'react'
import type {
  BatchTryOnBatchRegenerateResponse,
} from '../lib/batchTryOnReviewApi'
import {
  summarizeBatchTryOnSelection,
  type SelectedBatchTryOnReviewItem,
} from '../lib/batchTryOnBulkActions'

interface Props {
  selected: SelectedBatchTryOnReviewItem[]
  invalidCount: number
  onClose: () => void
  onSubmit: (
    items: SelectedBatchTryOnReviewItem[],
    reviewNotes: string,
  ) => Promise<BatchTryOnBatchRegenerateResponse>
}

const EXAMPLE = `保持模特、人物脸部、姿势和背景不变；
只替换服装；
服装上的文字、图案、数字、条纹和配色必须与原服装图一致；
衣服自然贴合身体，不要改变人物体型。`

export default function BatchTryOnBulkRegenerateDialog({
  selected,
  invalidCount,
  onClose,
  onSubmit,
}: Props) {
  const [reviewNotes, setReviewNotes] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const submitLock = useRef(false)
  const summary = summarizeBatchTryOnSelection(selected)

  const submit = async () => {
    const notes = reviewNotes.trim()
    if (!notes) {
      setMessage('请输入本次批量重新生成的附加要求')
      return
    }
    if (!selected.length) {
      setMessage('当前选择中没有可重新生成的图片')
      return
    }
    if (!window.confirm(`将为 ${selected.length} 张图片分别创建新的重新生成版本，是否继续？`)) return
    if (submitLock.current) return
    submitLock.current = true
    setBusy(true)
    setMessage('正在创建批量重新生成任务...')
    try {
      const result = await onSubmit(selected, notes)
      if (result.failed_count) {
        setMessage(
          `成功创建 ${result.created_count} 个，失败 ${result.failed_count} 个：`
          + result.errors.map((error) => error.message).join('；'),
        )
        return
      }
      onClose()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '批量重新生成提交失败')
    } finally {
      submitLock.current = false
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[110] flex items-center justify-center bg-gray-950/70 p-4" role="dialog" aria-modal="true" aria-label="批量附加要求重新生成">
      <div className="w-full max-w-2xl rounded-2xl bg-white p-5 shadow-2xl dark:bg-gray-900">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-bold text-gray-950 dark:text-white">批量附加要求重新生成</h2>
            <div className="mt-2 text-sm text-gray-600 dark:text-gray-300">
              本次选择：{summary.itemCount} 张图片 · 涉及模板：{summary.templateCount} 个 · 涉及服装：{summary.garmentCount} 件
            </div>
          </div>
          <button type="button" disabled={busy} onClick={onClose} className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm dark:border-white/[0.1]">关闭</button>
        </div>
        {invalidCount > 0 && (
          <div className="mt-4 rounded-xl bg-amber-50 px-3 py-2.5 text-sm text-amber-800 dark:bg-amber-500/10 dark:text-amber-200">
            共选择 {summary.itemCount + invalidCount} 张，可重新生成 {summary.itemCount} 张，不可重新生成 {invalidCount} 张。本次仅处理可重新生成项；你也可以取消操作。
          </div>
        )}
        <label className="mt-4 block text-sm font-bold text-gray-900 dark:text-gray-100">
          请输入本次批量重新生成的补充要求
          <textarea
            value={reviewNotes}
            disabled={busy}
            onChange={(event) => setReviewNotes(event.target.value)}
            placeholder={EXAMPLE}
            className="mt-2 min-h-44 w-full resize-y rounded-xl border border-gray-200 bg-gray-50 px-3 py-2.5 text-sm font-normal outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-500/20 disabled:opacity-60 dark:border-white/[0.1] dark:bg-gray-950 dark:text-white"
          />
        </label>
        {message && (
          <div className={`mt-3 rounded-xl px-3 py-2.5 text-sm ${busy ? 'bg-blue-50 text-blue-700 dark:bg-blue-500/10 dark:text-blue-200' : 'bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-200'}`}>
            {message}
          </div>
        )}
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" disabled={busy} onClick={onClose} className="rounded-xl border border-gray-200 px-4 py-2.5 text-sm font-semibold text-gray-700 disabled:opacity-50 dark:border-white/[0.1] dark:text-gray-200">取消</button>
          <button type="button" disabled={busy} onClick={() => void submit()} className="rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50">
            {busy ? '正在提交…' : `确认批量重新生成（${selected.length}）`}
          </button>
        </div>
      </div>
    </div>
  )
}
