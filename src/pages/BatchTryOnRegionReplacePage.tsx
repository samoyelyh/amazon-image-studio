import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import BatchTryOnRegionReplaceDialog from '../components/BatchTryOnRegionReplaceDialog'
import { getBatchTryOnReviewDetail, listBatchTryOnReviewDetails, type BatchTryOnReviewDetail } from '../lib/batchTryOnReviewApi'
import { appRoutes } from '../app/routes'
import type { BatchTryOnItem } from '../types'

function itemFromDetail(detail: BatchTryOnReviewDetail): BatchTryOnItem {
  const current = detail.current_version
  return {
    id: detail.client_item_id,
    batchId: detail.batch_id,
    templateId: detail.template_id ?? undefined,
    templateName: detail.template_name ?? undefined,
    garmentImageId: detail.garment_asset.id,
    garmentServerAssetId: detail.garment_asset.id,
    garmentFileName: detail.garment_asset.filename,
    index: 0,
    taskId: current?.task_id ?? undefined,
    serverOutputAssetId: current?.generated_asset_id ?? undefined,
    serverOutputFilename: current?.display_filename ?? undefined,
    serverOutputDownloadFilename: current?.download_filename ?? undefined,
    serverOutputDownloadUrl: current?.generated_asset?.download_url ?? undefined,
    serverVersionNumber: current?.version_number,
    serverReviewItemId: detail.item_id,
    serverReviewStatus: detail.review_status,
    serverCurrentVersionId: detail.current_version_id ?? undefined,
    serverApprovedVersionId: detail.approved_version_id ?? undefined,
    regenerationCount: detail.regeneration_count,
    status: current?.generation_status === 'succeeded' ? 'done' : current?.generation_status === 'failed' ? 'error' : 'running',
    error: current?.generation_status === 'failed' ? '生成失败' : undefined,
    createdAt: Date.parse(current?.created_at ?? '') || Date.now(),
  }
}

export default function BatchTryOnRegionReplacePage() {
  const navigate = useNavigate()
  const { itemId = '' } = useParams()
  const [searchParams] = useSearchParams()
  const [detail, setDetail] = useState<BatchTryOnReviewDetail | null>(null)
  const [details, setDetails] = useState<BatchTryOnReviewDetail[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    setLoading(true); setError('')
    void getBatchTryOnReviewDetail(itemId).then((loaded) => {
      if (cancelled) return
      setDetail(loaded)
      return listBatchTryOnReviewDetails(loaded.batch_id).then((batchDetails) => {
        if (!cancelled) setDetails(batchDetails)
      })
    }).catch((reason) => {
      if (!cancelled) setError(reason instanceof Error ? reason.message : '区域替换数据加载失败。')
    }).finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [itemId])

  const items = useMemo(() => (details.length ? details : detail ? [detail] : []).map(itemFromDetail), [detail, details])
  const returnToBatchTryOn = () => {
    const projectId = searchParams.get('project_id')
    navigate(projectId ? `${appRoutes.batchTryOn}?project_id=${encodeURIComponent(projectId)}` : appRoutes.batchTryOn)
  }
  const selectItem = (nextItemId: string) => {
    const projectId = searchParams.get('project_id')
    const suffix = projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''
    navigate(`/workspaces/batch-tryon/region-replace/${encodeURIComponent(nextItemId)}${suffix}`)
  }

  if (loading) return <div className="flex min-h-[60vh] items-center justify-center text-sm text-gray-500">正在加载区域替换画布…</div>
  if (error || !detail) return <div className="mx-auto mt-10 max-w-xl rounded-2xl border border-red-200 bg-red-50 p-6 text-sm text-red-700"><div className="font-semibold">区域替换画布无法打开</div><div className="mt-2">{error || '审核项不存在。'}</div><button type="button" onClick={returnToBatchTryOn} className="mt-4 rounded-lg bg-red-600 px-4 py-2 font-semibold text-white">返回批量套图</button></div>

  return <BatchTryOnRegionReplaceDialog
    pageMode
    detail={detail}
    items={items}
    selectedItemIds={new Set()}
    onClose={returnToBatchTryOn}
    onSelectItem={selectItem}
    onSubmitted={(changed) => {
      setDetail(changed)
      setDetails((current) => current.map((item) => item.item_id === changed.item_id ? changed : item))
    }}
  />
}
