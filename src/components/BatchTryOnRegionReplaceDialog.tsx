import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import {
  approveBatchTryOnRegionReplaceVersion,
  discardBatchTryOnRegionReplaceVersion,
  getBatchTryOnReviewDetail,
  regionReplaceBatchTryOnVersion,
  type BatchTryOnRegionReplaceType,
  type BatchTryOnReviewAsset,
  type BatchTryOnReviewDetail,
} from '../lib/batchTryOnReviewApi'
import {
  DEFAULT_REGION_REPLACE_PROMPT,
  FULL_REGION_BOUNDS,
  loadImageElement,
  normalizeRegionBounds,
  renderRegionReplaceFrameFiles,
  validRegionBounds,
  type RegionBounds,
  type RegionPoint,
} from '../lib/batchRegionReplace'
import { fetchAssetBlob, uploadRegionReplaceReference } from '../lib/contentApi'
import { randomUuid } from '../lib/randomUuid'
import type { BatchTryOnItem } from '../types'

type Scope = 'current' | 'template' | 'selected'
type MainView = 'edit' | 'intermediate' | 'result'
type RegionReplaceResultStatus = 'processing' | 'success' | 'approved' | 'failed'

interface BaseSnapshot {
  versionId: string
  asset: BatchTryOnReviewAsset
}

interface RegionReplaceResult {
  status: RegionReplaceResultStatus
  versionId?: string
  jobId?: string
  message?: string
}

function resultFromDetail(detail: BatchTryOnReviewDetail): RegionReplaceResult | undefined {
  const candidate = detail.versions.find((version) => (
    version.retry_mode === 'region_replace'
    && version.review_status !== 'rejected'
    && (version.parent_version_id === detail.current_version_id || version.id === detail.current_version_id)
  ))
  if (!candidate) return undefined
  if (candidate.review_status === 'approved' && candidate.id === detail.current_version_id) {
    return { status: 'approved', versionId: candidate.id, jobId: candidate.task_id ?? undefined }
  }
  if (candidate.generation_status === 'succeeded' && candidate.generated_asset) {
    return { status: 'success', versionId: candidate.id, jobId: candidate.task_id ?? undefined }
  }
  if (['failed', 'cancelled', 'stopped'].includes(candidate.generation_status)) {
    return { status: 'failed', versionId: candidate.id, jobId: candidate.task_id ?? undefined, message: '区域替换生成失败，基础结果仍已保留。' }
  }
  return { status: 'processing', versionId: candidate.id, jobId: candidate.task_id ?? undefined }
}

function latestDiscardableRegionCandidate(detail: BatchTryOnReviewDetail) {
  return detail.versions
    .filter((version) => (
      version.retry_mode === 'region_replace'
      && version.review_status !== 'approved'
      && ['succeeded', 'failed', 'cancelled', 'stopped'].includes(version.generation_status)
    ))
    .sort((left, right) => right.version_number - left.version_number)[0] ?? null
}

interface Props {
  detail: BatchTryOnReviewDetail
  items: BatchTryOnItem[]
  selectedItemIds: Set<string>
  pageMode?: boolean
  onSelectItem?: (itemId: string) => void
  onClose: () => void
  onSubmitted: (detail: BatchTryOnReviewDetail, taskId?: string) => void
}

const REGION_OPTIONS: Array<{ value: BatchTryOnRegionReplaceType; label: string }> = [
  { value: 'back_name', label: '背部姓名' },
  { value: 'back_number', label: '背部号码' },
  { value: 'wearer_left_shoulder_number', label: '穿着者左肩号码' },
  { value: 'wearer_right_shoulder_number', label: '穿着者右肩号码' },
  { value: 'custom_region', label: '自定义区域' },
]

export default function BatchTryOnRegionReplaceDialog({
  detail, items, selectedItemIds, pageMode = false, onSelectItem, onClose, onSubmitted,
}: Props) {
  const [scope, setScope] = useState<Scope>('current')
  const [regionType, setRegionType] = useState<BatchTryOnRegionReplaceType>('back_number')
  const [prompt, setPrompt] = useState(DEFAULT_REGION_REPLACE_PROMPT)
  const [editMode, setEditMode] = useState<'texture_protect' | 'normal_edit'>('texture_protect')
  const [edgeFeatherPx, setEdgeFeatherPx] = useState(24)
  const [coreInsetPx, setCoreInsetPx] = useState(12)
  const [sourceMode, setSourceMode] = useState<'garment' | 'image_c'>(detail.image_c_asset ? 'image_c' : 'garment')
  const [intermediatePreviewUrl, setIntermediatePreviewUrl] = useState<string | null>(null)
  const [defaultTargetFrame, setDefaultTargetFrame] = useState<RegionBounds | null>(null)
  const [defaultSourceFrame, setDefaultSourceFrame] = useState<RegionBounds>(FULL_REGION_BOUNDS)
  const [targetOverrides, setTargetOverrides] = useState<Record<string, RegionBounds | null>>({})
  const [sourceOverrides, setSourceOverrides] = useState<Record<string, RegionBounds>>({})
  const [detailCache, setDetailCache] = useState<Record<string, BatchTryOnReviewDetail>>({ [detail.item_id]: detail })
  const [previewItemIds, setPreviewItemIds] = useState<string[]>([detail.item_id])
  const [baseSnapshots, setBaseSnapshots] = useState<Record<string, BaseSnapshot>>(() => {
    const snapshot = baseSnapshotFromDetail(detail)
    return snapshot ? { [detail.item_id]: snapshot } : {}
  })
  const [editingItemId, setEditingItemId] = useState(detail.item_id)
  const [mainView, setMainView] = useState<MainView>('edit')
  const [loadingPreview, setLoadingPreview] = useState(false)
  const [navigating, setNavigating] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [approving, setApproving] = useState(false)
  const [discarding, setDiscarding] = useState(false)
  const [message, setMessage] = useState('')
  const [results, setResults] = useState<Record<string, RegionReplaceResult>>(() => {
    const initial = resultFromDetail(detail)
    return initial ? { [detail.item_id]: initial } : {}
  })

  const editingDetail = detailCache[editingItemId] ?? detail
  const editingSourceAsset = sourceMode === 'image_c' && editingDetail.image_c_asset
    ? editingDetail.image_c_asset
    : editingDetail.garment_asset
  const previewDetails = previewItemIds
    .map((itemId) => detailCache[itemId])
    .filter((item): item is BatchTryOnReviewDetail => Boolean(item))
  const editingBase = baseSnapshots[editingItemId] ?? baseSnapshotFromDetail(editingDetail)
  const editingResult = results[editingItemId]
  const editingResultVersion = editingResult?.versionId
    ? editingDetail.versions.find((version) => version.id === editingResult.versionId) ?? null
    : null
  const currentReplacementAsset = editingResultVersion?.generation_status === 'succeeded'
    ? editingResultVersion.generated_asset
    : null
  const targetFrame = targetOverrides[editingDetail.item_id] ?? defaultTargetFrame
  const sourceFrame = sourceOverrides[editingDetail.item_id] ?? defaultSourceFrame
  const setTargetFrame = (value: RegionBounds | null) => {
    if (editingDetail.item_id === detail.item_id) setDefaultTargetFrame(value)
    else setTargetOverrides((current) => ({ ...current, [editingDetail.item_id]: value }))
  }
  const setSourceFrame = (value: RegionBounds | null) => {
    const next = value ?? FULL_REGION_BOUNDS
    if (editingDetail.item_id === detail.item_id) setDefaultSourceFrame(next)
    else setSourceOverrides((current) => ({ ...current, [editingDetail.item_id]: next }))
  }

  const navigationIds = useMemo(() => {
    const eligible = items
      .filter((item) => (
        Boolean(item.serverReviewItemId)
        && item.status === 'done'
        && item.serverReviewStatus === 'approved'
      ))
      .map((item) => item.serverReviewItemId!)
    return eligible.includes(detail.item_id) ? eligible : [detail.item_id, ...eligible]
  }, [detail.item_id, items])
  const navigationIndex = navigationIds.indexOf(editingItemId)

  const scopeIds = useMemo(() => {
    if (scope === 'current') return [editingItemId]
    if (scope === 'template') {
      return items.filter((item) => item.serverReviewItemId && item.templateId === editingDetail.template_id)
        .map((item) => item.serverReviewItemId!)
    }
    return [...selectedItemIds]
  }, [editingDetail.template_id, editingItemId, items, scope, selectedItemIds])

  const submissionDetails = scope === 'current' ? [editingDetail] : previewDetails

  const rememberDetails = useCallback((loaded: BatchTryOnReviewDetail[]) => {
    setDetailCache((current) => {
      const next = { ...current }
      loaded.forEach((item) => { next[item.item_id] = item })
      return next
    })
    setBaseSnapshots((current) => {
      const next = { ...current }
      loaded.forEach((item) => {
        if (!next[item.item_id]) {
          const snapshot = baseSnapshotFromDetail(item)
          if (snapshot) next[item.item_id] = snapshot
        }
      })
      return next
    })
  }, [])

  useEffect(() => {
    setDetailCache({ [detail.item_id]: detail })
    const snapshot = baseSnapshotFromDetail(detail)
    setBaseSnapshots(snapshot ? { [detail.item_id]: snapshot } : {})
    setPreviewItemIds([detail.item_id])
    setEditingItemId(detail.item_id)
    const initialResult = resultFromDetail(detail)
    setMainView(initialResult ? 'result' : 'edit')
    setResults(initialResult ? { [detail.item_id]: initialResult } : {})
  }, [detail.item_id])

  useEffect(() => {
    if (sourceMode === 'image_c' && !editingDetail.image_c_asset) setSourceMode('garment')
  }, [editingDetail.image_c_asset, sourceMode])

  useEffect(() => () => {
    if (intermediatePreviewUrl) URL.revokeObjectURL(intermediatePreviewUrl)
  }, [intermediatePreviewUrl])

  const navigate = useCallback(async (direction: -1 | 1) => {
    if (navigating || submitting || navigationIndex < 0) return
    const targetId = navigationIds[navigationIndex + direction]
    if (!targetId) return
    setNavigating(true); setMessage('')
    try {
      let nextDetail = detailCache[targetId]
      if (!nextDetail) nextDetail = await getBatchTryOnReviewDetail(targetId)
      rememberDetails([nextDetail])
      setEditingItemId(targetId)
      if (pageMode && onSelectItem) onSelectItem(targetId)
      if (scope === 'current') setPreviewItemIds([targetId])
      setMainView(results[targetId] ? 'result' : 'edit')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '下一张图片加载失败。')
    } finally {
      setNavigating(false)
    }
  }, [detailCache, navigationIds, navigationIndex, navigating, onSelectItem, pageMode, rememberDetails, results, scope, submitting])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (target?.closest('input, textarea, select, [contenteditable="true"]')) return
      if (event.key === 'ArrowLeft') { event.preventDefault(); void navigate(-1) }
      if (event.key === 'ArrowRight') { event.preventDefault(); void navigate(1) }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [navigate])

  const processingKey = Object.entries(results)
    .filter(([, result]) => result.status === 'processing')
    .map(([itemId]) => itemId)
    .sort()
    .join(',')

  useEffect(() => {
    if (!processingKey) return
    let cancelled = false
    let timer: number | undefined
    const itemIds = processingKey.split(',').filter(Boolean)
    const poll = async () => {
      await Promise.all(itemIds.map(async (itemId) => {
        try {
          const fresh = await getBatchTryOnReviewDetail(itemId)
          if (cancelled) return
          rememberDetails([fresh])
          onSubmitted(fresh)
          const trackedVersionId = results[itemId]?.versionId
          const version = fresh.versions.find((candidate) => candidate.id === trackedVersionId)
          if (!version) {
            setResults((current) => ({ ...current, [itemId]: { ...current[itemId], status: 'failed', message: '区域替换候选版本不存在，请重新提交。' } }))
          } else if (version.generation_status === 'succeeded' && version.generated_asset) {
            setResults((current) => ({ ...current, [itemId]: { ...current[itemId], status: 'success' } }))
            if (itemId === editingItemId) setMainView('result')
          } else if (['failed', 'cancelled', 'stopped'].includes(version.generation_status)) {
            setResults((current) => ({ ...current, [itemId]: { ...current[itemId], status: 'failed', message: '区域替换生成失败，基础结果仍已保留。' } }))
          }
        } catch (error) {
          if (!cancelled) {
            setResults((current) => ({
              ...current,
              [itemId]: { ...current[itemId], status: 'failed', message: error instanceof Error ? error.message : '结果状态查询失败。' },
            }))
          }
        }
      }))
      if (!cancelled) timer = window.setTimeout(poll, 2000)
    }
    void poll()
    return () => { cancelled = true; if (timer) window.clearTimeout(timer) }
    // results is intentionally represented by processingKey to avoid restarting polling on every detail refresh.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [processingKey, rememberDetails])

  const approveReplacement = async () => {
    const versionId = editingResult?.versionId
    if (!versionId || editingResult.status !== 'success' || approving) return
    setApproving(true); setMessage('')
    try {
      const changed = await approveBatchTryOnRegionReplaceVersion(editingItemId, versionId)
      rememberDetails([changed])
      const nextSnapshot = baseSnapshotFromDetail(changed)
      if (nextSnapshot) setBaseSnapshots((current) => ({ ...current, [editingItemId]: nextSnapshot }))
      setResults((current) => ({ ...current, [editingItemId]: { ...current[editingItemId], status: 'approved' } }))
      onSubmitted(changed)
      setMessage('区域替换已确认完成，并已成为当前生成结果的最新版本。')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '区域替换确认完成失败。')
    } finally {
      setApproving(false)
    }
  }

  const discardReplacement = async () => {
    if (!editingResult || !['success', 'failed'].includes(editingResult.status) || discarding) return
    setDiscarding(true); setMessage('')
    try {
      let versionId = editingResult.versionId
      if (!versionId) {
        const fresh = await getBatchTryOnReviewDetail(editingItemId)
        rememberDetails([fresh])
        versionId = latestDiscardableRegionCandidate(fresh)?.id
      }
      if (!versionId) {
        setResults((current) => {
          const next = { ...current }
          delete next[editingItemId]
          return next
        })
        setMainView('edit')
        setMessage('本次失败发生在候选创建之前，已清除本地失败状态，可以重新调整后提交。')
        return
      }
      const changed = await discardBatchTryOnRegionReplaceVersion(editingItemId, versionId)
      rememberDetails([changed])
      setResults((current) => {
        const next = { ...current }
        delete next[editingItemId]
        return next
      })
      setMainView('edit')
      onSubmitted(changed)
      setMessage('已放弃未完成的区域替换候选，可以重新涂抹并提交。')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '放弃区域替换候选失败。')
    } finally {
      setDiscarding(false)
    }
  }

  const loadPreview = async () => {
    setLoadingPreview(true); setMessage('')
    try {
      const uniqueIds = [...new Set(scopeIds.length ? scopeIds : [detail.item_id])]
      const loaded = await Promise.all(uniqueIds.map((id) => detailCache[id] ?? getBatchTryOnReviewDetail(id)))
      const eligible = loaded.filter((item) => (
        item.review_status === 'approved'
        && item.approved_version_id === item.current_version_id
        && item.current_version?.review_status === 'approved'
        && item.current_version.generation_status === 'succeeded'
        && item.current_version.generated_asset
      ))
      if (!eligible.length) throw new Error('所选范围没有已审核通过、可执行区域替换的结果。')
      rememberDetails(eligible)
      setPreviewItemIds(eligible.map((item) => item.item_id))
      if (!eligible.some((item) => item.item_id === editingItemId)) setEditingItemId(eligible[0].item_id)
      const missingC = eligible.filter((item) => !item.image_c_asset)
      if (missingC.length) setMessage(`${missingC.length} 张图片没有图C字体参考，将不会提交。`)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '批量预览加载失败。')
    } finally {
      setLoadingPreview(false)
    }
  }

  const submit = async () => {
    if (submitting) return
    if (!prompt.trim()) { setMessage('请填写区域替换 Prompt。'); return }
    if (!validRegionBounds(targetFrame)) { setMessage('请先在当前结果图上框选目标替换区域。'); return }
    setSubmitting(true); setMessage('')
    setResults((current) => ({ ...current, ...Object.fromEntries(submissionDetails.map((item) => [item.item_id, { status: 'processing' as const }])) }))
    setMainView('result')
    let succeeded = 0
    for (const target of submissionDetails) {
      try {
        const snapshot = baseSnapshots[target.item_id] ?? baseSnapshotFromDetail(target)
        const version = snapshot ? target.versions.find((item) => item.id === snapshot.versionId) ?? target.current_version : target.current_version
        const baseAsset = snapshot?.asset ?? version?.generated_asset
        const imageC = sourceMode === 'image_c' && target.image_c_asset ? target.image_c_asset : target.garment_asset
        if (!version || version.generation_status !== 'succeeded' || !baseAsset) throw new Error('基础结果尚未生成成功。')
        if (!imageC) throw new Error('当前服装没有图C字体参考。')
        const itemTargetFrame = targetOverrides[target.item_id] ?? defaultTargetFrame
        const itemSourceFrame = sourceOverrides[target.item_id] ?? defaultSourceFrame
        if (!validRegionBounds(itemTargetFrame)) throw new Error('当前图片尚未设置目标框。')
        if (!validRegionBounds(itemSourceFrame)) throw new Error('当前图片尚未设置图C来源框。')
        const [baseBlob, imageCBlob] = await Promise.all([
          fetchAssetBlob(baseAsset.preview_url),
          fetchAssetBlob(imageC.preview_url),
        ])
        const rendered = await renderRegionReplaceFrameFiles(baseBlob, imageCBlob, itemTargetFrame, itemSourceFrame, {
          editMode,
          edgeFeatherPx,
          coreInsetPx,
        })
        const sourceMetadata = {
          ...rendered.sourceMetadata,
          source_role: sourceMode,
        }
        if (target.item_id === editingItemId) {
          setIntermediatePreviewUrl((current) => {
            if (current) URL.revokeObjectURL(current)
            return URL.createObjectURL(rendered.intermediatePreview)
          })
        }
        const targetMask = await uploadRegionReplaceReference(rendered.targetMask, {
          sourceAssetId: baseAsset.id,
          assetRole: 'target_edit_mask',
          transformMetadata: rendered.targetMetadata,
        })
        const sourceMask = rendered.sourceMask
          ? await uploadRegionReplaceReference(rendered.sourceMask, {
            sourceAssetId: imageC.id,
            assetRole: 'source_reference_mask',
            transformMetadata: sourceMetadata,
          })
          : null
        const patch = await uploadRegionReplaceReference(rendered.referencePatch, {
          sourceAssetId: imageC.id,
          assetRole: 'reference_patch',
          transformMetadata: sourceMetadata,
        })
        const response = await regionReplaceBatchTryOnVersion(target.item_id, {
          source_version_id: snapshot?.versionId ?? version.id,
          target_mask_asset_id: targetMask.id,
          image_c_asset_id: imageC.id,
          source_reference_mask_asset_id: sourceMask?.id ?? null,
          reference_patch_asset_id: patch.id,
          edit_region_type: regionType,
          edit_prompt: prompt.trim(),
          target_mask_metadata: rendered.targetMetadata,
          source_reference_metadata: sourceMetadata,
          idempotency_key: `region-replace:${randomUuid()}`,
        })
        succeeded += 1
        rememberDetails([response.review])
        setResults((current) => ({ ...current, [target.item_id]: {
          status: 'processing',
          versionId: response.job.review_version_id ?? undefined,
          jobId: response.job.id,
        } }))
        onSubmitted(response.review)
      } catch (error) {
        const text = error instanceof Error ? error.message : '提交失败'
        setResults((current) => ({ ...current, [target.item_id]: { status: 'failed', message: text } }))
      }
    }
    setMessage(`区域替换已提交 ${succeeded} 张，失败 ${submissionDetails.length - succeeded} 张。结果完成后会自动显示，基础结果和历史版本均保留。`)
    setSubmitting(false)
  }

  const previewIntermediate = async () => {
    if (!validRegionBounds(targetFrame) || !validRegionBounds(sourceFrame)) {
      setMessage('请先设置结果图目标框和来源图框。'); return
    }
    setMessage('')
    try {
      const baseAsset = editingBase?.asset
      if (!baseAsset) throw new Error('当前基础结果不可用。')
      const [baseBlob, sourceBlob] = await Promise.all([
        fetchAssetBlob(baseAsset.preview_url),
        fetchAssetBlob(editingSourceAsset.preview_url),
      ])
      const rendered = await renderRegionReplaceFrameFiles(baseBlob, sourceBlob, targetFrame, sourceFrame, {
        editMode, edgeFeatherPx, coreInsetPx,
      })
      setIntermediatePreviewUrl((current) => {
        if (current) URL.revokeObjectURL(current)
        return URL.createObjectURL(rendered.intermediatePreview)
      })
      setMainView('intermediate')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '中间覆盖图预览失败。')
    }
  }

  return <div className={pageMode ? 'min-h-[calc(100vh-7rem)] bg-gray-100 p-3 dark:bg-gray-950 sm:p-5' : 'fixed inset-0 z-[130] flex items-center justify-center bg-gray-950/80 p-3'} role={pageMode ? 'region' : 'dialog'} aria-modal={pageMode ? undefined : true} aria-label="区域涂抹替换">
    <div className={pageMode ? 'mx-auto flex min-h-[calc(100vh-9rem)] w-full max-w-[1800px] flex-col overflow-hidden rounded-2xl border border-gray-200 bg-gray-50 shadow-sm dark:border-white/10 dark:bg-gray-950' : 'flex h-[95vh] w-full max-w-[1680px] flex-col overflow-hidden rounded-2xl bg-gray-50 shadow-2xl dark:bg-gray-950'}>
      <header className="flex items-start justify-between border-b border-gray-200 bg-white px-5 py-4 dark:border-white/10 dark:bg-gray-900">
        <div><div className="flex flex-wrap items-center gap-2"><h2 className="text-lg font-bold text-gray-950 dark:text-white">纹理保护换图</h2><span className="rounded-full bg-gray-100 px-2 py-1 text-xs font-semibold text-gray-600 dark:bg-white/10 dark:text-gray-300">区域覆盖 + AI 融图</span><span className="rounded-full bg-gray-100 px-2 py-1 text-xs font-semibold text-gray-600 dark:bg-white/10 dark:text-gray-300">第 {Math.max(0, navigationIndex) + 1} 张 / 共 {navigationIds.length} 张</span></div><p className="mt-1 text-xs text-gray-500">程序负责商品纹理真实性，image-2 只负责边缘、褶皱、透视和光影融合；确认后才会替换当前生成结果。</p></div>
        <button type="button" onClick={onClose} disabled={submitting} className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm disabled:opacity-50 dark:border-white/10">{pageMode ? '返回批量套图' : '关闭'}</button>
      </header>
      <div className="grid min-h-0 flex-1 gap-3 overflow-auto p-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_340px]">
        <div className="flex min-h-[520px] flex-col">
          <div className="mb-2 flex rounded-xl border border-gray-200 bg-white p-1 dark:border-white/10 dark:bg-gray-900">
            <button type="button" onClick={() => setMainView('edit')} className={`flex-1 rounded-lg px-3 py-2 text-xs font-semibold ${mainView === 'edit' ? 'bg-blue-600 text-white' : 'text-gray-600 dark:text-gray-300'}`}>框选替换区域</button>
            <button type="button" onClick={() => void previewIntermediate()} className={`flex-1 rounded-lg px-3 py-2 text-xs font-semibold ${mainView === 'intermediate' ? 'bg-blue-600 text-white' : 'text-gray-600 dark:text-gray-300'}`}>中间覆盖图</button>
            <button type="button" onClick={() => setMainView('result')} className={`flex-1 rounded-lg px-3 py-2 text-xs font-semibold ${mainView === 'result' ? 'bg-blue-600 text-white' : 'text-gray-600 dark:text-gray-300'}`}>AI 融合结果{editingResult?.status === 'processing' ? '（生成中）' : editingResult?.status === 'success' ? '（待确认）' : editingResult?.status === 'approved' ? '（已完成）' : ''}</button>
          </div>
          {mainView === 'edit'
            ? <FrameSelectionCanvas title="结果图目标框" subtitle="拖拽创建框；框内用于覆盖，框外严格保留。" asset={editingBase?.asset ?? null} bounds={targetFrame} onChange={setTargetFrame} frameColor="#ef4444" />
            : mainView === 'intermediate'
              ? <IntermediatePreview url={intermediatePreviewUrl} onBack={() => setMainView('edit')} />
              : <RegionReplacementResult baseAsset={editingBase?.asset ?? null} resultAsset={currentReplacementAsset} result={editingResult} approving={approving} discarding={discarding} onApprove={() => void approveReplacement()} onDiscard={() => void discardReplacement()} onBackToEdit={() => setMainView('edit')} />}
        </div>
        <div className="flex min-h-[520px] flex-col gap-2"><div className="flex rounded-xl border border-gray-200 bg-white p-1 dark:border-white/10 dark:bg-gray-900"><button type="button" onClick={() => setSourceMode('garment')} className={`flex-1 rounded-lg px-3 py-2 text-xs font-semibold ${sourceMode === 'garment' ? 'bg-blue-600 text-white' : 'text-gray-600 dark:text-gray-300'}`}>图B 服装原图</button><button type="button" disabled={!editingDetail.image_c_asset} onClick={() => setSourceMode('image_c')} className={`flex-1 rounded-lg px-3 py-2 text-xs font-semibold disabled:opacity-40 ${sourceMode === 'image_c' ? 'bg-blue-600 text-white' : 'text-gray-600 dark:text-gray-300'}`}>图C 辅助参考</button></div><FrameSelectionCanvas title={`${sourceMode === 'image_c' ? '图C' : '图B'}覆盖来源框`} subtitle="来源框可与目标框尺寸、比例不同，后端自动映射。" asset={editingSourceAsset} bounds={sourceFrame} onChange={setSourceFrame} frameColor="#2563eb" allowFullImage /></div>
        <aside className="space-y-3">
          <section className="rounded-2xl border border-gray-200 bg-white p-4 dark:border-white/10 dark:bg-gray-900">
            <div className="text-xs font-semibold text-gray-700 dark:text-gray-200">编辑模式</div>
            <div className="mt-2 grid grid-cols-2 gap-2">
              <button type="button" onClick={() => setEditMode('texture_protect')} className={`rounded-xl border px-3 py-2 text-left text-xs font-semibold ${editMode === 'texture_protect' ? 'border-blue-500 bg-blue-50 text-blue-700 dark:bg-blue-500/10 dark:text-blue-200' : 'border-gray-200 dark:border-white/10'}`}><span className="block">纹理保护融合</span><span className="mt-1 block text-[10px] font-normal opacity-75">推荐 · AI只处理融合环</span></button>
              <button type="button" onClick={() => setEditMode('normal_edit')} className={`rounded-xl border px-3 py-2 text-left text-xs font-semibold ${editMode === 'normal_edit' ? 'border-blue-500 bg-blue-50 text-blue-700 dark:bg-blue-500/10 dark:text-blue-200' : 'border-gray-200 dark:border-white/10'}`}><span className="block">普通 AI 编辑</span><span className="mt-1 block text-[10px] font-normal opacity-75">整个目标框可被重绘</span></button>
            </div>
            {editMode === 'texture_protect' && <div className="mt-3 space-y-3">
              <RangeField label="边缘融合范围" value={edgeFeatherPx} min={4} max={64} suffix="px" onChange={setEdgeFeatherPx} />
              <RangeField label="核心保护内缩" value={coreInsetPx} min={0} max={48} suffix="px" onChange={setCoreInsetPx} />
              <div className="rounded-lg bg-emerald-50 px-3 py-2 text-[11px] leading-5 text-emerald-800 dark:bg-emerald-500/10 dark:text-emerald-200">程序先把来源选区精确覆盖到目标框；核心区由中间覆盖图锁定，image-2 只处理外围融合环。</div>
            </div>}
          </section>
          <section className="rounded-2xl border border-gray-200 bg-white p-4 dark:border-white/10 dark:bg-gray-900">
            <label className="text-xs font-semibold text-gray-700 dark:text-gray-200">区域类型</label>
            <select value={regionType} onChange={(event) => setRegionType(event.target.value as BatchTryOnRegionReplaceType)} className="mt-2 h-10 w-full rounded-xl border border-gray-200 bg-white px-3 text-sm dark:border-white/10 dark:bg-gray-950">
              {REGION_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
            <label className="mt-4 block text-xs font-semibold text-gray-700 dark:text-gray-200">编辑 Prompt</label>
            <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} rows={9} className="mt-2 w-full resize-y rounded-xl border border-gray-200 bg-white px-3 py-2 text-xs leading-5 dark:border-white/10 dark:bg-gray-950" />
          </section>
          <section className="rounded-2xl border border-gray-200 bg-white p-4 dark:border-white/10 dark:bg-gray-900">
            <div className="text-xs font-semibold text-gray-700 dark:text-gray-200">应用范围</div>
            <div className="mt-2 grid gap-2">{([
              ['current', '当前图片'], ['template', '当前模板下全部图片'], ['selected', `任务队列已选图片（${selectedItemIds.size}）`],
            ] as Array<[Scope, string]>).map(([value, label]) => <label key={value} className="flex items-center gap-2 text-xs"><input type="radio" checked={scope === value} onChange={() => setScope(value)} />{label}</label>)}</div>
            <button type="button" onClick={() => void loadPreview()} disabled={loadingPreview || submitting} className="mt-3 w-full rounded-xl border border-blue-200 bg-blue-50 px-3 py-2 text-sm font-semibold text-blue-700 disabled:opacity-50 dark:border-blue-500/30 dark:bg-blue-500/10 dark:text-blue-200">{loadingPreview ? '加载中…' : '生成批量预览'}</button>
          </section>
          <section className="rounded-2xl border border-gray-200 bg-white p-4 dark:border-white/10 dark:bg-gray-900">
            <div className="flex items-center justify-between text-xs font-semibold"><span>批量预览</span><span>{previewDetails.length} 张</span></div>
            <div className="mt-3 max-h-64 space-y-2 overflow-auto">{previewDetails.map((item) => <button key={item.item_id} type="button" onClick={() => setEditingItemId(item.item_id)} className={`flex w-full items-center gap-2 rounded-xl border p-2 text-left ${editingDetail.item_id === item.item_id ? 'border-blue-500 bg-blue-50 dark:bg-blue-500/10' : 'border-gray-200 dark:border-white/10'}`}>
              <RegionPreview asset={baseSnapshots[item.item_id]?.asset ?? item.current_version?.generated_asset ?? null} bounds={targetOverrides[item.item_id] ?? defaultTargetFrame} />
              <span className="min-w-0 flex-1"><span className="block truncate text-xs font-semibold">{item.current_version?.display_filename ?? item.garment_asset.filename}</span><span className="block truncate text-[11px] text-gray-500">{item.image_c_asset ? '图C已就绪' : '缺少图C'} · {targetOverrides[item.item_id] ? '单独调整' : '统一框位'}</span></span>
              <span className={`text-[11px] ${results[item.item_id]?.status === 'failed' ? 'text-red-600' : results[item.item_id]?.status === 'approved' ? 'text-emerald-600' : results[item.item_id]?.status === 'success' ? 'text-amber-600' : results[item.item_id]?.status === 'processing' ? 'text-blue-600' : 'text-gray-400'}`}>{results[item.item_id]?.status === 'approved' ? '已通过' : results[item.item_id]?.status === 'success' ? '待审核' : results[item.item_id]?.status === 'processing' ? '生成中' : results[item.item_id]?.status === 'failed' ? '失败' : '调整'}</span>
            </button>)}</div>
          </section>
          {message && <div className="rounded-xl bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800 dark:bg-amber-500/10 dark:text-amber-200">{message}</div>}
        </aside>
      </div>
      <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-gray-200 bg-white px-5 py-3 dark:border-white/10 dark:bg-gray-900">
        <div className="text-xs text-gray-500">可用左右方向键切换；两个框位相互独立，后端按目标框执行像素级自适应迁移后再调用 image-2 融合。</div>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={() => void navigate(-1)} disabled={navigating || submitting || navigationIndex <= 0} className="rounded-xl border border-gray-200 px-4 py-2.5 text-sm font-semibold disabled:opacity-40 dark:border-white/10">上一张</button>
          <button type="button" onClick={() => void submit()} disabled={submitting || Boolean(editingResult && editingResult.status !== 'approved') || !validRegionBounds(targetFrame)} title={editingResult && editingResult.status !== 'approved' ? '请先确认完成或放弃当前区域替换候选。' : undefined} className="rounded-xl bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white disabled:opacity-40">{submitting ? '正在批量提交…' : `执行区域替换（${submissionDetails.length}）`}</button>
          <button type="button" onClick={() => void navigate(1)} disabled={navigating || submitting || navigationIndex < 0 || navigationIndex >= navigationIds.length - 1} className="rounded-xl border border-gray-200 px-4 py-2.5 text-sm font-semibold disabled:opacity-40 dark:border-white/10">下一张</button>
        </div>
      </footer>
    </div>
  </div>
}

function RangeField({ label, value, min, max, suffix, onChange }: { label: string; value: number; min: number; max: number; suffix: string; onChange: (value: number) => void }) {
  return <label className="block"><span className="flex items-center justify-between text-[11px] text-gray-500"><span>{label}</span><span className="font-semibold text-gray-700 dark:text-gray-200">{value}{suffix}</span></span><input type="range" min={min} max={max} value={value} onChange={(event) => onChange(Number(event.target.value))} className="mt-1 w-full" /></label>
}

function baseSnapshotFromDetail(detail: BatchTryOnReviewDetail): BaseSnapshot | null {
  const version = detail.current_version
  if (!version || version.generation_status !== 'succeeded' || !version.generated_asset) return null
  return { versionId: version.id, asset: version.generated_asset }
}

function IntermediatePreview({ url, onBack }: { url: string | null; onBack: () => void }) {
  return <section className="flex min-h-[520px] flex-1 flex-col rounded-2xl border border-gray-200 bg-white p-3 dark:border-white/10 dark:bg-gray-900"><div><h3 className="text-sm font-bold">像素覆盖中间图</h3><p className="mt-1 text-xs text-gray-500">这是程序实际提交给 image-2 的底图；可先确认来源内容、位置和缩放是否正确。</p></div><div className="mt-3 flex min-h-0 flex-1 items-center justify-center overflow-hidden rounded-xl bg-gray-100 dark:bg-black/30">{url ? <img src={url} alt="像素覆盖中间图" className="max-h-full max-w-full object-contain" /> : <div className="text-sm text-gray-500">请先设置两个框位，再生成中间覆盖图。</div>}</div><div className="mt-3 flex justify-end"><button type="button" onClick={onBack} className="rounded-lg border border-gray-200 px-4 py-2 text-xs font-semibold dark:border-white/10">返回调整框位</button></div></section>
}

function RegionReplacementResult({ baseAsset, resultAsset, result, approving, discarding, onApprove, onDiscard, onBackToEdit }: {
  baseAsset: BatchTryOnReviewAsset | null
  resultAsset: BatchTryOnReviewAsset | null
  result?: RegionReplaceResult
  approving: boolean
  discarding: boolean
  onApprove: () => void
  onDiscard: () => void
  onBackToEdit: () => void
}) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let cancelled = false
    let created: string | null = null
    setObjectUrl(null); setFailed(false)
    if (!resultAsset) return () => undefined
    void fetchAssetBlob(resultAsset.preview_url).then((blob) => {
      if (cancelled) return
      created = URL.createObjectURL(blob)
      setObjectUrl(created)
    }).catch(() => { if (!cancelled) setFailed(true) })
    return () => { cancelled = true; if (created) URL.revokeObjectURL(created) }
  }, [resultAsset?.id])

  return <section className="flex min-h-[520px] flex-1 flex-col rounded-2xl border border-gray-200 bg-white p-3 dark:border-white/10 dark:bg-gray-900">
    <div className="flex items-start justify-between gap-3"><div><h3 className="text-sm font-bold">区域替换待确认结果</h3><p className="mt-1 text-xs text-gray-500">确认完成后替换当前结果；不满意请放弃，不会占用普通审核版本栏。</p></div>{resultAsset && <a href={objectUrl ?? undefined} download={resultAsset.download_filename || resultAsset.filename} className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-semibold dark:border-white/10">下载候选图</a>}</div>
    <div className="mt-3 flex min-h-0 flex-1 items-center justify-center overflow-hidden rounded-xl bg-gray-100 dark:bg-black/30">
      {objectUrl && <img src={objectUrl} alt="区域替换结果" className="max-h-full max-w-full object-contain" />}
      {!objectUrl && result?.status === 'processing' && <div className="px-6 text-center text-sm text-blue-600"><div className="mx-auto mb-3 h-8 w-8 animate-spin rounded-full border-2 border-blue-200 border-t-blue-600" />区域替换生成中，完成后会自动显示…</div>}
      {!objectUrl && result?.status === 'failed' && <div className="max-w-sm px-6 text-center text-sm text-red-600"><div className="font-semibold">区域替换失败</div><div className="mt-2 text-xs leading-5">{result.message || '基础结果仍已保留，可返回修改蒙版后重试。'}</div></div>}
      {!objectUrl && failed && <div className="px-6 text-center text-sm text-red-600">替换结果图片加载失败，请稍后重试。</div>}
      {!objectUrl && !result && !failed && <div className="max-w-sm px-6 text-center text-sm text-gray-500">提交区域替换后，生成结果会显示在这里。<button type="button" onClick={onBackToEdit} className="mt-3 block w-full text-sm font-semibold text-blue-600">返回涂抹目标区域</button></div>}
    </div>
    {result?.status === 'success' && <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-3 dark:border-amber-500/20 dark:bg-amber-500/10"><span className="text-xs text-amber-800 dark:text-amber-200">当前替换尚未确认，不会进入普通审核版本栏。</span><div className="flex gap-2"><button type="button" onClick={onDiscard} disabled={approving || discarding} className="rounded-lg border border-amber-300 bg-white px-4 py-2 text-xs font-semibold text-amber-800 disabled:opacity-50 dark:bg-transparent dark:text-amber-200">{discarding ? '正在放弃…' : '放弃本次替换'}</button><button type="button" onClick={onApprove} disabled={approving || discarding} className="rounded-lg bg-emerald-600 px-4 py-2 text-xs font-semibold text-white disabled:opacity-50">{approving ? '正在确认…' : '确认完成并设为最新版本'}</button></div></div>}
    {result?.status === 'failed' && <div className="mt-3 flex justify-end"><button type="button" onClick={onDiscard} disabled={discarding} className="rounded-lg border border-gray-300 px-4 py-2 text-xs font-semibold disabled:opacity-50">{discarding ? '正在清理…' : '放弃失败候选并重新涂抹'}</button></div>}
    {result?.status === 'approved' && <div className="mt-3 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-3 text-xs font-semibold text-emerald-700 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-200">已确认完成，当前图片已切换为这个最新版本。</div>}
    {baseAsset && <div className="mt-3 text-xs text-gray-500">基础结果：{baseAsset.display_filename || baseAsset.filename}</div>}
  </section>
}

function FrameSelectionCanvas({ title, subtitle, asset, bounds, onChange, frameColor, allowFullImage = false }: {
  title: string
  subtitle: string
  asset: BatchTryOnReviewAsset | null
  bounds: RegionBounds | null
  onChange: (value: RegionBounds | null) => void
  frameColor: string
  allowFullImage?: boolean
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const imageRef = useRef<HTMLImageElement | null>(null)
  const [loading, setLoading] = useState(false)
  const interactionRef = useRef<{
    mode: 'create' | 'move' | 'nw' | 'ne' | 'sw' | 'se'
    start: RegionPoint
    initial: RegionBounds | null
  } | null>(null)
  const boundsRef = useRef(bounds)

  useEffect(() => { boundsRef.current = bounds }, [bounds])

  const redraw = () => {
    const canvas = canvasRef.current
    const image = imageRef.current
    if (!canvas || !image) return
    const context = canvas.getContext('2d')
    if (!context) return
    context.clearRect(0, 0, canvas.width, canvas.height)
    context.drawImage(image, 0, 0, canvas.width, canvas.height)
    if (!validRegionBounds(bounds)) return
    const frame = normalizeRegionBounds(bounds)
    const x = frame.x * canvas.width
    const y = frame.y * canvas.height
    const width = frame.width * canvas.width
    const height = frame.height * canvas.height
    context.save()
    context.fillStyle = 'rgba(15, 23, 42, 0.42)'
    context.beginPath()
    context.rect(0, 0, canvas.width, canvas.height)
    context.rect(x, y, width, height)
    context.fill('evenodd')
    context.globalAlpha = 0.18
    context.fillStyle = frameColor
    context.fillRect(x, y, width, height)
    context.globalAlpha = 1
    context.strokeStyle = frameColor
    context.lineWidth = Math.max(2, Math.min(canvas.width, canvas.height) * 0.006)
    context.strokeRect(x, y, width, height)
    const handleSize = Math.max(8, Math.min(canvas.width, canvas.height) * 0.025)
    ;[[x, y], [x + width, y], [x, y + height], [x + width, y + height]].forEach(([hx, hy]) => {
      context.fillStyle = '#fff'
      context.fillRect(hx - handleSize / 2, hy - handleSize / 2, handleSize, handleSize)
      context.strokeStyle = frameColor
      context.strokeRect(hx - handleSize / 2, hy - handleSize / 2, handleSize, handleSize)
    })
    context.restore()
  }

  useEffect(() => {
    let cancelled = false
    imageRef.current = null
    if (!asset) return
    setLoading(true)
    void fetchAssetBlob(asset.preview_url).then(loadImageElement).then((image) => {
      if (cancelled) return
      imageRef.current = image
      const canvas = canvasRef.current
      if (canvas) {
        const max = 900
        const scale = Math.min(1, max / Math.max(image.width, image.height))
        canvas.width = Math.max(1, Math.round(image.width * scale))
        canvas.height = Math.max(1, Math.round(image.height * scale))
      }
      setLoading(false)
      requestAnimationFrame(redraw)
    }).catch(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [asset?.id])

  useEffect(redraw, [bounds, frameColor])

  const point = (event: ReactPointerEvent<HTMLCanvasElement>): RegionPoint => {
    const rect = event.currentTarget.getBoundingClientRect()
    return {
      x: Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
      y: Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)),
    }
  }
  const down = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    if (!asset) return
    event.currentTarget.setPointerCapture(event.pointerId)
    const start = point(event)
    const frame = boundsRef.current && validRegionBounds(boundsRef.current)
      ? normalizeRegionBounds(boundsRef.current)
      : null
    let mode: 'create' | 'move' | 'nw' | 'ne' | 'sw' | 'se' = 'create'
    if (frame) {
      const threshold = 0.04
      const corners: Array<['nw' | 'ne' | 'sw' | 'se', number, number]> = [
        ['nw', frame.x, frame.y], ['ne', frame.x + frame.width, frame.y],
        ['sw', frame.x, frame.y + frame.height], ['se', frame.x + frame.width, frame.y + frame.height],
      ]
      const corner = corners.find(([, x, y]) => Math.abs(start.x - x) <= threshold && Math.abs(start.y - y) <= threshold)
      if (corner) mode = corner[0]
      else if (start.x >= frame.x && start.x <= frame.x + frame.width && start.y >= frame.y && start.y <= frame.y + frame.height) mode = 'move'
    }
    interactionRef.current = { mode, start, initial: frame }
    if (mode === 'create') onChange({ x: start.x, y: start.y, width: 0.001, height: 0.001 })
  }
  const move = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    const interaction = interactionRef.current
    if (!interaction || !event.currentTarget.hasPointerCapture(event.pointerId)) return
    const current = point(event)
    const initial = interaction.initial
    let next: RegionBounds
    if (interaction.mode === 'create' || !initial) {
      next = normalizeRegionBounds({
        x: interaction.start.x,
        y: interaction.start.y,
        width: current.x - interaction.start.x,
        height: current.y - interaction.start.y,
      })
    } else if (interaction.mode === 'move') {
      const x = Math.max(0, Math.min(1 - initial.width, initial.x + current.x - interaction.start.x))
      const y = Math.max(0, Math.min(1 - initial.height, initial.y + current.y - interaction.start.y))
      next = normalizeRegionBounds({ ...initial, x, y })
    } else {
      const left = interaction.mode.includes('w') ? current.x : initial.x
      const right = interaction.mode.includes('e') ? current.x : initial.x + initial.width
      const top = interaction.mode.startsWith('n') ? current.y : initial.y
      const bottom = interaction.mode.startsWith('s') ? current.y : initial.y + initial.height
      next = normalizeRegionBounds({ x: left, y: top, width: right - left, height: bottom - top })
    }
    boundsRef.current = next
    onChange(next)
  }
  const up = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
    interactionRef.current = null
    if (!validRegionBounds(boundsRef.current)) onChange(null)
  }

  return <section className="flex min-h-[520px] flex-col rounded-2xl border border-gray-200 bg-white p-3 dark:border-white/10 dark:bg-gray-900">
    <div className="flex flex-wrap items-start justify-between gap-2"><div><h3 className="text-sm font-bold">{title}</h3><p className="mt-1 text-xs text-gray-500">{subtitle}</p></div><div className="flex gap-1">{allowFullImage && <button type="button" onClick={() => onChange(FULL_REGION_BOUNDS)} className="rounded-lg bg-gray-100 px-2.5 py-1.5 text-xs font-semibold dark:bg-white/10">选择整张</button>}<button type="button" onClick={() => onChange(allowFullImage ? FULL_REGION_BOUNDS : null)} className="rounded-lg bg-gray-100 px-2.5 py-1.5 text-xs font-semibold dark:bg-white/10">重置</button></div></div>
    <div className="mt-3 flex items-center justify-between rounded-lg bg-gray-50 px-3 py-2 text-[11px] text-gray-500 dark:bg-white/5"><span>{validRegionBounds(bounds) ? `位置 ${Math.round(bounds.x * 100)}%, ${Math.round(bounds.y * 100)}%` : '尚未框选'}</span><span>{validRegionBounds(bounds) ? `大小 ${Math.round(bounds.width * 100)}% × ${Math.round(bounds.height * 100)}%` : '拖拽图片开始框选'}</span></div>
    <div className="mt-3 flex min-h-0 flex-1 items-center justify-center overflow-hidden rounded-xl bg-gray-100 dark:bg-black/30">{asset ? <canvas ref={canvasRef} onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up} className="max-h-full max-w-full touch-none cursor-crosshair object-contain" /> : <div className="px-6 text-center text-sm text-gray-500">{loading ? '图片加载中…' : '当前没有可用图片'}</div>}</div>
  </section>
}

function RegionPreview({ asset, bounds }: { asset: BatchTryOnReviewAsset | null; bounds: RegionBounds | null }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  useEffect(() => {
    let cancelled = false
    if (!asset || !canvasRef.current) return
    void fetchAssetBlob(asset.preview_url).then(loadImageElement).then((image) => {
      if (cancelled || !canvasRef.current) return
      const canvas = canvasRef.current
      const context = canvas.getContext('2d')
      if (!context) return
      canvas.width = 96; canvas.height = 72
      const scale = Math.max(canvas.width / image.width, canvas.height / image.height)
      const width = image.width * scale; const height = image.height * scale
      context.drawImage(image, (canvas.width - width) / 2, (canvas.height - height) / 2, width, height)
      if (validRegionBounds(bounds)) {
        context.strokeStyle = '#ef4444'; context.lineWidth = 2
        context.strokeRect(bounds.x * canvas.width, bounds.y * canvas.height, bounds.width * canvas.width, bounds.height * canvas.height)
      }
    })
    return () => { cancelled = true }
  }, [asset?.id, bounds])
  return <canvas ref={canvasRef} className="h-12 w-16 shrink-0 rounded-md bg-gray-100 object-cover" />
}
