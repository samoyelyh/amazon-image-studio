import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode, type WheelEvent } from 'react'
import { fetchAssetBlob } from '../lib/contentApi'
import {
  approveBatchTryOnVersion,
  getBatchTryOnReviewDetail,
  regenerateBatchTryOnVersion,
  type BatchTryOnReviewAsset,
  type BatchTryOnReviewDetail,
} from '../lib/batchTryOnReviewApi'
import { randomUuid } from '../lib/randomUuid'
import { downloadAuthenticatedFile } from '../lib/serverDownloads'
import type { BatchTryOnItem } from '../types'
import { findAdjacentReviewItem, getReviewableQueueItems } from '../lib/batchTryOnReviewQueue'
import {
  useBatchTryOnReviewShortcuts,
  type ReviewShortcutNoticeTone,
} from '../hooks/useBatchTryOnReviewShortcuts'

const REVIEW_LABEL: Record<string, string> = {
  pending: '待审核', approved: '已通过', rejected: '已打回', regenerating: '重新生成中', generation_failed: '生成失败',
}
const GENERATION_LABEL: Record<string, string> = {
  queued: '排队中', dispatching: '排队中', running: '生成中', retry_waiting: '等待重试', succeeded: '生成成功', failed: '生成失败', cancelled: '已取消',
}
const QUICK_NOTES = [
  '图案不一致', '颜色不一致', '文字错误', '数字错误', 'Logo错误', '衣领错误', '袖子错误',
  '下摆被遮挡', '版型不一致', '模特脸部改变', '姿势改变', '背景改变', '构图比例错误',
]

interface Props {
  itemId: string
  items: BatchTryOnItem[]
  canApprove: boolean
  canRegenerate: boolean
  onClose: () => void
  onSelectItem: (reviewItemId: string) => void
  onChanged: (detail: BatchTryOnReviewDetail, taskId?: string) => void
  onAdvance: (currentReviewItemId: string) => boolean
}

export default function BatchTryOnReviewDialog({
  itemId, items, canApprove, canRegenerate, onClose, onSelectItem, onChanged, onAdvance,
}: Props) {
  const queryClient = useQueryClient()
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null)
  const [showModel, setShowModel] = useState(false)
  const [showNotes, setShowNotes] = useState(false)
  const [reviewNotes, setReviewNotes] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [notice, setNotice] = useState<{ message: string; tone: ReviewShortcutNoticeTone } | null>(null)
  const [completed, setCompleted] = useState(false)
  const [syncZoom, setSyncZoom] = useState(false)
  const [sharedZoom, setSharedZoom] = useState(1)
  const submitLockRef = useRef(false)
  const noticeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const cancelConfirmationRef = useRef<(message?: string) => void>(() => undefined)
  const detailQuery = useQuery({
    queryKey: ['batch-tryon-review', itemId],
    queryFn: ({ signal }) => getBatchTryOnReviewDetail(itemId, signal),
    refetchInterval: (query) => query.state.data?.review_status === 'regenerating' ? 2_000 : false,
  })
  const detail = detailQuery.data
  const orderedReviewItems = useMemo(() => getReviewableQueueItems(items), [items])
  const localIndex = orderedReviewItems.findIndex((item) => item.serverReviewItemId === itemId)

  useEffect(() => {
    setSelectedVersionId(null)
    setShowModel(false)
    setShowNotes(false)
    setReviewNotes('')
    setMessage('')
    setCompleted(false)
    setSharedZoom(1)
    submitLockRef.current = false
  }, [itemId])

  useEffect(() => {
    if (detail?.current_version_id) setSelectedVersionId(detail.current_version_id)
  }, [detail?.current_version_id])

  useEffect(() => {
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = previous
      if (noticeTimerRef.current) clearTimeout(noticeTimerRef.current)
    }
  }, [])

  const selectedVersion = detail?.versions.find((version) => version.id === selectedVersionId)
    ?? detail?.current_version
    ?? detail?.versions[0]
  const currentVersion = detail?.current_version
  const reviewable = Boolean(
    canApprove
    && detail?.review_status === 'pending'
    && currentVersion
    && currentVersion.generation_status === 'succeeded'
    && currentVersion.review_status === 'pending'
    && currentVersion.generated_asset
    && currentVersion.id === selectedVersion?.id,
  )
  const regeneratable = Boolean(
    canRegenerate
    && currentVersion
    && ['succeeded', 'failed', 'cancelled'].includes(currentVersion.generation_status)
    && currentVersion.id === selectedVersion?.id,
  )

  const showNotice = (noticeMessage: string, tone: ReviewShortcutNoticeTone = 'info') => {
    setNotice({ message: noticeMessage, tone })
    if (noticeTimerRef.current) clearTimeout(noticeTimerRef.current)
    noticeTimerRef.current = setTimeout(() => setNotice(null), tone === 'warning' ? 3_500 : 2_000)
  }

  const confirmUnsaved = () => !reviewNotes.trim() || window.confirm('当前修改要求尚未提交，确认离开吗？')
  const selectManual = (direction: -1 | 1) => {
    if (busy) return
    const nextId = findAdjacentReviewItem(items, itemId, direction)?.serverReviewItemId
    if (!nextId) {
      showNotice(direction < 0 ? '已经是第一张' : '已经是最后一张')
      return
    }
    if (!confirmUnsaved()) return
    cancelConfirmationRef.current()
    void queryClient.cancelQueries({ queryKey: ['batch-tryon-review', itemId] })
    onSelectItem(nextId)
  }

  const advance = (changed: BatchTryOnReviewDetail, taskId?: string) => {
    // Keep the dialog in sync immediately. Invalidating alone leaves the old
    // pending review visible long enough for the same approval to be submitted
    // repeatedly, especially when there is no next pending item.
    queryClient.setQueryData(['batch-tryon-review', changed.item_id], changed)
    onChanged(changed, taskId)
    void queryClient.invalidateQueries({ queryKey: ['server-job-batches'] })
    if (!onAdvance(itemId)) setCompleted(true)
  }

  const approve = async () => {
    if (!currentVersion || !reviewable || submitLockRef.current) return
    const submittedItemId = itemId
    const submittedVersionId = currentVersion.id
    submitLockRef.current = true
    setBusy(true); setMessage('')
    try {
      const changed = await approveBatchTryOnVersion(submittedItemId, submittedVersionId)
      if (changed.item_id !== submittedItemId || changed.approved_version_id !== submittedVersionId) {
        throw new Error('审核响应与当前图片不一致，已停止更新页面，请刷新后重试。')
      }
      showNotice('已审核通过，正在进入下一张', 'success')
      advance(changed)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '审核通过失败')
    } finally {
      submitLockRef.current = false
      setBusy(false)
    }
  }

  const regenerate = async (withNotes: boolean, skipDirectConfirmation = false) => {
    if (!currentVersion || !regeneratable || submitLockRef.current) return
    const notes = reviewNotes.trim()
    if (withNotes && !notes) {
      setMessage('请先填写本次修改要求。')
      return
    }
    if (!withNotes && !skipDirectConfirmation && !window.confirm('确认重新生成当前图片吗？\n\n系统将沿用当前模特底图、服装原图、尺寸、模型和基础提示词，创建一个新的生成版本。')) return
    const submittedItemId = itemId
    const submittedVersionId = currentVersion.id
    submitLockRef.current = true
    setBusy(true); setMessage('')
    try {
      const result = await regenerateBatchTryOnVersion(submittedItemId, {
        source_version_id: submittedVersionId,
        retry_mode: withNotes ? 'with_review_notes' : 'direct',
        review_notes: withNotes ? notes : null,
        idempotency_key: `review:${randomUuid()}`,
      })
      const createdVersion = result.review.current_version
      if (
        result.review.item_id !== submittedItemId
        || !createdVersion
        || createdVersion.parent_version_id !== submittedVersionId
      ) {
        throw new Error('重新生成响应与当前图片不一致，已停止更新页面，请刷新后查看任务。')
      }
      showNotice('已提交重新生成，正在进入下一张', 'success')
      advance(result.review, result.job.id)
    } catch (error) {
      const text = error instanceof Error ? error.message : '重新生成失败'
      setMessage(/额度不足|quota\.insufficient/i.test(text) ? '当前可用额度不足，无法重新生成。' : text)
    } finally {
      submitLockRef.current = false
      setBusy(false)
    }
  }

  const approveUnavailableMessage = getApproveUnavailableMessage(detail)
  const regenerateUnavailableMessage = getRegenerateUnavailableMessage(detail)
  const {
    deleteConfirmation,
    remainingSeconds,
    cancelDeleteConfirmation,
  } = useBatchTryOnReviewShortcuts({
    enabled: !completed,
    currentItemId: itemId,
    currentVersionId: selectedVersion?.id ?? null,
    isBusy: busy || submitLockRef.current,
    hasApprovePermission: canApprove,
    hasRegeneratePermission: canRegenerate,
    canApprove: reviewable,
    canRegenerate: regeneratable,
    approveUnavailableMessage,
    regenerateUnavailableMessage,
    onPrevious: () => selectManual(-1),
    onNext: () => selectManual(1),
    onApprove: () => { void approve() },
    onConfirmRegenerate: () => { void regenerate(false, true) },
    onNotice: showNotice,
  })
  cancelConfirmationRef.current = cancelDeleteConfirmation

  const addQuickNote = (note: string) => {
    setReviewNotes((current) => `${current.trim()}${current.trim() ? '\n' : ''}${note}。`)
  }

  const approvedItem = orderedReviewItems.find((item) => item.serverReviewStatus === 'approved')

  return (
    <div className="fixed inset-0 z-[100] flex bg-gray-950/70" role="dialog" aria-modal="true" aria-label="批量套图对比审核">
      <div className="flex h-full w-full flex-col bg-gray-50 dark:bg-gray-950">
        <header className="shrink-0 border-b border-gray-200 bg-white px-4 py-3 dark:border-white/[0.08] dark:bg-gray-900 sm:px-6">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-lg font-bold text-gray-950 dark:text-white">图片对比审核</h2>
                <span className="rounded-full bg-gray-100 px-2 py-1 text-xs font-semibold text-gray-700 dark:bg-white/[0.07] dark:text-gray-200">第 {Math.max(0, localIndex) + 1} 张 / 共 {orderedReviewItems.length} 张</span>
              </div>
              {detail && <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-500 dark:text-gray-400">
                <span className="max-w-64 truncate" title={detail.template_name || detail.model_asset.filename}>模板：{detail.template_name || detail.model_asset.filename}</span>
                <span className="max-w-64 truncate" title={detail.garment_asset.filename}>服装：{detail.garment_asset.filename}</span>
                <span className="max-w-64 truncate" title={currentVersion?.display_filename ?? ''}>生成结果：{currentVersion?.display_filename ?? '—'}</span>
                <span>生成：{GENERATION_LABEL[currentVersion?.generation_status ?? ''] ?? currentVersion?.generation_status ?? '—'}</span>
                <span>审核：{REVIEW_LABEL[detail.review_status] ?? detail.review_status}</span>
                <span>版本：v{currentVersion?.version_number ?? '—'}</span>
                <span>重新生成：{detail.regeneration_count} 次</span>
                <span>创建：{formatTime(currentVersion?.created_at)}</span>
                <span>生成耗时：{formatDuration(currentVersion?.generation_duration_ms)}</span>
                {detail.preset_summary && <span className="max-w-full truncate text-violet-600 dark:text-violet-300" title={detail.preset_summary}>预设：{detail.preset_summary}</span>}
              </div>}
            </div>
            <button type="button" onClick={() => {
              if (!confirmUnsaved()) return
              cancelDeleteConfirmation()
              onClose()
            }} className="rounded-xl border border-gray-200 px-3 py-2 text-sm font-semibold text-gray-700 dark:border-white/[0.1] dark:text-gray-200">关闭</button>
          </div>
        </header>

        <main className="min-h-0 flex-1 overflow-y-auto p-4 pb-44 sm:p-6 sm:pb-44">
          {detailQuery.isLoading && <div className="flex h-full min-h-96 items-center justify-center text-sm text-gray-500">正在加载当前任务图片…</div>}
          {detailQuery.isError && <div className="mx-auto mt-16 max-w-xl rounded-2xl bg-red-50 p-5 text-center text-sm text-red-700">{detailQuery.error.message}</div>}
          {completed && <div className="mx-auto mt-16 max-w-xl rounded-3xl border border-emerald-200 bg-emerald-50 p-8 text-center dark:border-emerald-500/20 dark:bg-emerald-500/10">
            <h3 className="text-lg font-bold text-emerald-800 dark:text-emerald-200">当前批次已没有待审核图片。</h3>
            <div className="mt-5 flex flex-wrap justify-center gap-2">
              <button type="button" onClick={onClose} className="rounded-xl bg-emerald-600 px-4 py-2 text-sm font-semibold text-white">关闭审核窗口</button>
              <button type="button" onClick={onClose} className="rounded-xl border border-emerald-300 px-4 py-2 text-sm font-semibold text-emerald-800 dark:text-emerald-200">查看全部任务</button>
              {approvedItem?.serverReviewItemId && <button type="button" onClick={() => { setCompleted(false); onSelectItem(approvedItem.serverReviewItemId!) }} className="rounded-xl border border-emerald-300 px-4 py-2 text-sm font-semibold text-emerald-800 dark:text-emerald-200">查看已通过任务</button>}
            </div>
          </div>}
          {!completed && detail && <>
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap gap-2">
                {detail.versions.map((version) => <button key={version.id} type="button" onClick={() => {
                  cancelDeleteConfirmation()
                  setSelectedVersionId(version.id)
                }} className={`rounded-xl px-3 py-2 text-xs font-semibold ${selectedVersion?.id === version.id ? 'bg-blue-600 text-white' : 'border border-gray-200 bg-white text-gray-700 dark:border-white/[0.1] dark:bg-gray-900 dark:text-gray-200'}`}>v{version.version_number} · {GENERATION_LABEL[version.generation_status] ?? version.generation_status} · {REVIEW_LABEL[version.review_status] ?? version.review_status}</button>)}
              </div>
              <label className="flex items-center gap-2 text-xs font-semibold text-gray-600 dark:text-gray-300"><input type="checkbox" checked={syncZoom} onChange={(event) => setSyncZoom(event.target.checked)} />同步缩放</label>
            </div>
            <div className="grid gap-4 xl:grid-cols-2">
              <ReviewImageViewer key={`result-${selectedVersion?.generated_asset?.id ?? selectedVersion?.id}`} title="生成结果" asset={selectedVersion?.generated_asset ?? null} subtitle={selectedVersion ? `${selectedVersion.display_filename ?? '等待生成'} · v${selectedVersion.version_number}` : '暂无版本'} controlledZoom={syncZoom ? sharedZoom : undefined} onZoom={syncZoom ? setSharedZoom : undefined} allowDownload />
              <ReviewImageViewer key={`garment-${detail.garment_asset.id}`} title="服装原图" asset={detail.garment_asset} subtitle={detail.garment_asset.filename} controlledZoom={syncZoom ? sharedZoom : undefined} onZoom={syncZoom ? setSharedZoom : undefined} />
            </div>
            <section className="mt-4 rounded-2xl border border-gray-200 bg-white dark:border-white/[0.08] dark:bg-gray-900">
              <button type="button" onClick={() => setShowModel((value) => !value)} className="flex w-full items-center justify-between px-4 py-3 text-sm font-semibold text-gray-800 dark:text-gray-100"><span>查看模特底图</span><span>{showModel ? '收起' : '展开'}</span></button>
              {showModel && <div className="border-t border-gray-100 p-4 dark:border-white/[0.06]"><div className="mx-auto max-w-2xl"><ReviewImageViewer key={`model-${detail.model_asset.id}`} title="模特底图" asset={detail.model_asset} subtitle={detail.model_asset.filename} /></div></div>}
            </section>
            {showNotes && <section className="mt-4 rounded-2xl border border-blue-200 bg-blue-50/50 p-4 dark:border-blue-500/20 dark:bg-blue-500/5">
              <label className="text-sm font-bold text-gray-900 dark:text-white">本次修改要求</label>
              <textarea value={reviewNotes} onChange={(event) => setReviewNotes(event.target.value)} className="mt-2 min-h-32 w-full rounded-xl border border-gray-200 bg-white px-3 py-2.5 text-sm outline-none focus:border-blue-400 dark:border-white/[0.1] dark:bg-gray-950 dark:text-white" placeholder="请具体说明需要修正的问题，不能覆盖系统基础约束。" />
              <div className="mt-3 flex flex-wrap gap-2">{QUICK_NOTES.map((note) => <button key={note} type="button" onClick={() => addQuickNote(note)} className="rounded-full border border-blue-200 bg-white px-2.5 py-1 text-xs text-blue-700 dark:border-blue-500/30 dark:bg-gray-900 dark:text-blue-200">{note}</button>)}</div>
              <button type="button" disabled={busy || !reviewNotes.trim()} onClick={() => void regenerate(true)} className="mt-4 rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50">{busy ? '正在提交…' : '打回并重新生成'}</button>
            </section>}
            {message && <div className="mt-4 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-500/10 dark:text-red-200">{message}</div>}
            {notice && <div className={`mt-4 rounded-xl px-4 py-3 text-sm ${
              notice.tone === 'success'
                ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-200'
                : notice.tone === 'warning'
                  ? 'bg-amber-50 text-amber-800 dark:bg-amber-500/10 dark:text-amber-200'
                  : 'bg-blue-50 text-blue-700 dark:bg-blue-500/10 dark:text-blue-200'
            }`}>{notice.message}</div>}
          </>}
        </main>

        {!completed && <footer className="absolute inset-x-0 bottom-0 border-t border-gray-200 bg-white/95 px-4 py-3 shadow-[0_-8px_24px_rgba(0,0,0,0.08)] backdrop-blur dark:border-white/[0.08] dark:bg-gray-900/95 sm:px-6">
          {deleteConfirmation.armed && <div className="mx-auto mb-3 flex max-w-4xl flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-amber-900 dark:border-amber-500/40 dark:bg-amber-500/15 dark:text-amber-100">
            <div>
              <div className="text-sm font-bold">确认重新生成当前图片？</div>
              <div className="mt-1 text-xs">
                再次按 <Kbd>Delete</Kbd> 确认重新生成，按 <Kbd>Esc</Kbd> 取消；{Math.max(1, remainingSeconds)} 秒后自动取消。
              </div>
              {reviewNotes.trim() && <div className="mt-1 text-xs font-semibold">当前存在未提交的修改要求，Delete 将执行不带附加提示词的直接重新生成。</div>}
            </div>
            <button type="button" onClick={() => cancelDeleteConfirmation('已取消重新生成')} className="rounded-lg border border-amber-400 px-3 py-1.5 text-xs font-semibold">取消</button>
          </div>}
          <div className="flex flex-wrap items-center justify-center gap-2">
            <button type="button" disabled={orderedReviewItems.length < 2 || busy} onClick={() => selectManual(-1)} className="rounded-xl border border-gray-200 px-4 py-2.5 text-sm font-semibold text-gray-700 disabled:opacity-40 dark:border-white/[0.1] dark:text-gray-200">上一张</button>
            <button type="button" disabled={!reviewable || busy} onClick={() => void approve()} className="rounded-xl bg-emerald-600 px-5 py-2.5 text-sm font-semibold text-white disabled:opacity-40">{busy ? '处理中…' : '审核通过'}</button>
            <button type="button" disabled={!regeneratable || busy} onClick={() => void regenerate(false)} className="rounded-xl border border-amber-300 bg-amber-50 px-4 py-2.5 text-sm font-semibold text-amber-800 disabled:opacity-40 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">直接重新生成</button>
            <button type="button" disabled={!regeneratable || busy} onClick={() => setShowNotes((value) => !value)} className="rounded-xl border border-blue-200 bg-blue-50 px-4 py-2.5 text-sm font-semibold text-blue-700 disabled:opacity-40 dark:border-blue-500/30 dark:bg-blue-500/10 dark:text-blue-200">附加要求重新生成</button>
            <button type="button" disabled={orderedReviewItems.length < 2 || busy} onClick={() => selectManual(1)} className="rounded-xl border border-gray-200 px-4 py-2.5 text-sm font-semibold text-gray-700 disabled:opacity-40 dark:border-white/[0.1] dark:text-gray-200">下一张</button>
            {!canApprove && !canRegenerate && <span className="ml-2 text-xs text-gray-500">当前账号仅可查看，不能执行审核或重新生成。</span>}
          </div>
          <div className="mt-2 flex flex-wrap items-center justify-center gap-x-4 gap-y-1 text-[11px] text-gray-500 dark:text-gray-400">
            <span><Kbd>←</Kbd> 上一张</span>
            <span><Kbd>→</Kbd> 下一张</span>
            {canApprove && <span><Kbd>Enter</Kbd> 审核通过</span>}
            {canRegenerate && <span className={deleteConfirmation.armed ? 'font-bold text-amber-700 dark:text-amber-200' : ''}><Kbd>Delete</Kbd> {deleteConfirmation.armed ? '再次按下确认重新生成' : '重新生成'}</span>}
            {deleteConfirmation.armed && <span><Kbd>Esc</Kbd> 取消确认</span>}
          </div>
        </footer>}
      </div>
    </div>
  )
}

function ReviewImageViewer({ title, asset, subtitle, controlledZoom, onZoom, allowDownload = false }: {
  title: string
  asset: BatchTryOnReviewAsset | null
  subtitle: string
  controlledZoom?: number
  onZoom?: (zoom: number) => void
  allowDownload?: boolean
}) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)
  const [localZoom, setLocalZoom] = useState(1)
  const [position, setPosition] = useState({ x: 0, y: 0 })
  const drag = useRef<{ x: number; y: number; originX: number; originY: number } | null>(null)
  const zoom = controlledZoom ?? localZoom

  useEffect(() => {
    let cancelled = false
    let created: string | null = null
    setObjectUrl(null); setFailed(false); setPosition({ x: 0, y: 0 }); setLocalZoom(1)
    if (!asset) return () => undefined
    void fetchAssetBlob(asset.preview_url).then((blob) => {
      if (cancelled) return
      created = URL.createObjectURL(blob)
      setObjectUrl(created)
    }).catch(() => { if (!cancelled) setFailed(true) })
    return () => { cancelled = true; if (created) URL.revokeObjectURL(created) }
  }, [asset])

  const changeZoom = (next: number) => {
    const clamped = Math.min(5, Math.max(0.25, Math.round(next * 100) / 100))
    if (onZoom) onZoom(clamped)
    else setLocalZoom(clamped)
  }
  const reset = (actual = false) => {
    changeZoom(1)
    setPosition({ x: 0, y: 0 })
    if (actual) setLocalZoom(1)
  }
  const pointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!objectUrl) return
    event.currentTarget.setPointerCapture(event.pointerId)
    drag.current = { x: event.clientX, y: event.clientY, originX: position.x, originY: position.y }
  }
  const pointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!drag.current) return
    setPosition({ x: drag.current.originX + event.clientX - drag.current.x, y: drag.current.originY + event.clientY - drag.current.y })
  }
  const wheel = (event: WheelEvent<HTMLDivElement>) => {
    event.preventDefault()
    changeZoom(zoom + (event.deltaY < 0 ? 0.15 : -0.15))
  }
  const download = async () => {
    if (!asset) return
    await downloadAuthenticatedFile(asset.download_url, asset.download_filename)
  }

  return <section className="overflow-hidden rounded-2xl border border-gray-200 bg-white dark:border-white/[0.08] dark:bg-gray-900">
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-gray-100 px-4 py-3 dark:border-white/[0.06]">
      <div><h3 className="text-sm font-bold text-gray-900 dark:text-white">{title}</h3><div className="mt-0.5 max-w-72 truncate text-xs text-gray-500" title={subtitle}>{subtitle}{asset ? ` · ${asset.width}×${asset.height}` : ''}</div></div>
      <div className="flex flex-wrap gap-1.5 text-[11px]">
        <button type="button" onClick={() => reset()} className="rounded-lg border border-gray-200 px-2 py-1 dark:border-white/[0.1]">适应窗口</button>
        <button type="button" onClick={() => reset(true)} className="rounded-lg border border-gray-200 px-2 py-1 dark:border-white/[0.1]">恢复100%</button>
        <button type="button" disabled={!objectUrl} onClick={() => changeZoom(zoom + 0.5)} className="rounded-lg border border-gray-200 px-2 py-1 disabled:opacity-40 dark:border-white/[0.1]">放大查看</button>
        <button type="button" disabled={!objectUrl} onClick={() => objectUrl && window.open(objectUrl, '_blank', 'noopener,noreferrer')} className="rounded-lg border border-gray-200 px-2 py-1 disabled:opacity-40 dark:border-white/[0.1]">新窗口查看</button>
        {allowDownload && <button type="button" disabled={!objectUrl} onClick={() => void download()} className="rounded-lg bg-blue-600 px-2 py-1 font-semibold text-white disabled:opacity-40">下载</button>}
      </div>
    </div>
    <div onWheel={wheel} onDoubleClick={() => objectUrl && changeZoom(zoom < 2 ? 2 : 1)} onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={() => { drag.current = null }} onPointerCancel={() => { drag.current = null }} className="relative flex h-[54vh] min-h-80 cursor-grab touch-none items-center justify-center overflow-hidden bg-gray-100 active:cursor-grabbing dark:bg-gray-950" title="双击放大或恢复，滚轮缩放，拖拽移动">
      {!asset && <div className="px-6 text-center text-sm text-gray-500">当前版本尚未生成结果</div>}
      {asset && !objectUrl && !failed && <div className="absolute inset-0 animate-pulse bg-gray-200/60 dark:bg-white/[0.04]" />}
      {failed && <div className="px-6 text-center text-sm text-red-500">图片加载失败，请稍后重试</div>}
      {objectUrl && <img draggable={false} src={objectUrl} alt={title} className="max-h-full max-w-full select-none object-contain will-change-transform" style={{ transform: `translate(${position.x}px, ${position.y}px) scale(${zoom})` }} />}
      <div className="pointer-events-none absolute bottom-3 right-3 rounded-lg bg-gray-950/65 px-2 py-1 text-xs font-semibold text-white">{Math.round(zoom * 100)}%</div>
    </div>
  </section>
}

function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="rounded border border-current/25 bg-white/70 px-1.5 py-0.5 font-mono text-[10px] font-semibold shadow-sm dark:bg-gray-950/50">{children}</kbd>
}

function getApproveUnavailableMessage(detail?: BatchTryOnReviewDetail) {
  if (!detail?.current_version) return '当前图片信息尚未加载完成，不能审核通过。'
  if (detail.review_status === 'approved' || detail.current_version.review_status === 'approved') return '当前图片已经审核通过。'
  if (detail.review_status === 'regenerating') return '当前图片正在重新生成，不能审核通过。'
  if (detail.current_version.generation_status !== 'succeeded') return '当前图片尚未生成完成，不能审核通过。'
  if (!detail.current_version.generated_asset) return '当前图片没有有效生成结果，不能审核通过。'
  return '当前版本不是最新版本，不能审核通过。'
}

function getRegenerateUnavailableMessage(detail?: BatchTryOnReviewDetail) {
  if (!detail?.current_version) return '当前图片信息尚未加载完成，不能重新生成。'
  if (['queued', 'dispatching', 'running', 'retry_waiting'].includes(detail.current_version.generation_status)) {
    return '当前图片仍在生成或排队中，暂时不能重新生成。'
  }
  return '当前版本不是最新版本，不能重新生成。'
}

function formatTime(value?: string | null) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'
}

function formatDuration(value?: number | null) {
  if (value == null) return '—'
  if (value < 1000) return `${value} ms`
  return `${Math.round(value / 100) / 10} 秒`
}
