import { useRef, useState } from 'react'
import type { BatchTryOnBatch } from '../types'
import {
  downloadErrorMessage, downloadSelectedBatchTryOnResultsZip, downloadSelectedBatchTryOnTemplateZip,
  withPartialExportConfirmation,
} from '../lib/serverDownloads'

export function currentQueueBatchIds(batch: BatchTryOnBatch): string[] {
  const production = batch.items.filter((item) => !item.id.startsWith('validation:'))
  const ids = production.map((item) => item.serverBatchId).filter((id): id is string => Boolean(id))
  return [...new Set(ids.length ? ids : [...(batch.serverBatchIds || []), batch.serverBatchId].filter((id): id is string => Boolean(id)))]
}

export function useBatchTryOnDownloads(notify: (message: string, type: 'success' | 'error') => void) {
  const inflight = useRef(false)
  const [busy, setBusy] = useState(false)
  const run = async (operation: (partial: boolean) => ReturnType<typeof downloadSelectedBatchTryOnResultsZip>) => {
    if (inflight.current) { notify('正在为你打包，请稍等一下，暂时不用重复点击。', 'success'); return }
    inflight.current = true
    setBusy(true)
    try {
      const result = await withPartialExportConfirmation(operation)
      if (result) notify(`已下载 ${result.exported} 张结果${result.skipped ? `；${result.skipped} 项未导出，清单已附在压缩包中` : ''}`, 'success')
    } catch (error) { notify(`打包失败：${downloadErrorMessage(error)}`, 'error') }
    finally { inflight.current = false; setBusy(false) }
  }
  return { busy,
    downloadQueue: (batch: BatchTryOnBatch) => run((partial) => downloadSelectedBatchTryOnResultsZip(currentQueueBatchIds(batch), partial)),
    downloadTemplate: (templateId: string, itemIds: string[], scope: 'approved' | 'all_succeeded') =>
      run((partial) => downloadSelectedBatchTryOnTemplateZip(templateId, itemIds, scope, partial)),
  }
}
