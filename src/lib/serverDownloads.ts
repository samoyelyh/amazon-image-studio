import { zipSync } from 'fflate'
import type { JobOutput } from './jobsApi'
import { fetchAssetBlob } from './contentApi'
import { authenticatedFetchResponse } from './authApi'
import { AuthApiError } from './authApi'
import { randomUuid } from './randomUuid'

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1_000)
}

export async function downloadServerOutput(output: JobOutput) {
  saveBlob(
    await fetchAssetBlob(output.download_url || output.url),
    output.download_filename || output.filename,
  )
}

export function responseFilename(response: Response): string | null {
  const header = response.headers.get('Content-Disposition')
  if (!header) return null
  const encoded = header.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
  if (encoded) {
    try {
      return decodeURIComponent(encoded)
    } catch {
      // Fall through to the ASCII filename.
    }
  }
  return header.match(/filename=\"?([^\";]+)\"?/i)?.[1] ?? null
}

export async function downloadAuthenticatedFile(url: string, filename?: string, init: RequestInit = {}) {
  const clientRequestId = randomUuid()
  const headers = new Headers(init.headers)
  headers.set('X-Request-ID', clientRequestId)
  let response: Response
  try { response = await authenticatedFetchResponse(url, { ...init, headers }) } catch (error) {
    if (error instanceof AuthApiError) {
      error.requestId ||= clientRequestId
      throw error
    }
    throw new AuthApiError(0, 'download.network_error', '下载连接中断或服务不可用，请重试。', { stage: 'request' }, clientRequestId)
  }
  const requestId = response.headers.get('X-Request-ID') || clientRequestId
  try {
    const blob = await response.blob()
    const expected = response.headers.get('Content-Length')
    if (!blob.size || (expected && Number(expected) !== blob.size)) throw new Error('下载文件不完整，请重试。')
    if (response.headers.get('Content-Type')?.includes('application/zip')) {
      const start = new Uint8Array(await blob.slice(0, 4).arrayBuffer())
      const tail = new Uint8Array(await blob.slice(Math.max(0, blob.size - 65557)).arrayBuffer())
      const hasEnd = tail.some((value, i) => value === 0x50 && tail[i + 1] === 0x4b && tail[i + 2] === 0x05 && tail[i + 3] === 0x06)
      if (start[0] !== 0x50 || start[1] !== 0x4b || !hasEnd) throw new Error('压缩包不完整，未保存损坏文件，请重试。')
    }
    saveBlob(blob, responseFilename(response) || filename || 'download')
    return { exported: Number(response.headers.get('X-Batch-Try-On-Exported') || 0),
      skipped: Number(response.headers.get('X-Batch-Try-On-Skipped') || 0), requestId }
  } catch (error) {
    throw new AuthApiError(response.status, 'download.interrupted',
      `${error instanceof Error ? error.message : '下载中断'}${requestId ? `（请求编号：${requestId}）` : ''}`,
      { stage: 'receive_or_save' }, requestId)
  }
}

export async function downloadBatchTryOnResultsZip(batchId: string, allowPartial = false) {
  return downloadAuthenticatedFile(
    `/job-batches/${batchId}/batch-tryon-results.zip?allow_partial=${allowPartial}`,
    'batch-tryon-results.zip',
  )
}

export async function downloadBatchTryOnTemplateZip(
  batchId: string,
  templateId: string,
  scope: 'approved' | 'all_succeeded' = 'approved',
) {
  await downloadAuthenticatedFile(
    `/batch-tryon/batches/${encodeURIComponent(batchId)}/templates/${encodeURIComponent(templateId)}/download?scope=${scope}`,
    'batch-tryon-template-results.zip',
  )
}

export async function downloadSelectedBatchTryOnTemplateZip(
  templateId: string,
  reviewItemIds: string[],
  scope: 'approved' | 'all_succeeded' = 'approved',
  allowPartial = false,
) {
  return downloadAuthenticatedFile(
    `/batch-tryon/templates/${encodeURIComponent(templateId)}/download`,
    'batch-tryon-template-results.zip',
    {
      method: 'POST',
      body: JSON.stringify({ item_ids: reviewItemIds, scope, allow_partial: allowPartial }),
    },
  )
}

export function downloadSelectedBatchTryOnResultsZip(batchIds: string[], allowPartial = false) {
  return downloadAuthenticatedFile('/batch-tryon/exports/download', 'batch-tryon-results.zip', {
    method: 'POST', body: JSON.stringify({ batch_ids: [...new Set(batchIds)], allow_partial: allowPartial }),
  })
}

export async function withPartialExportConfirmation<T>(download: (allowPartial: boolean) => Promise<T>): Promise<T | null> {
  try { return await download(false) } catch (error) {
    if (!(error instanceof AuthApiError) || error.code !== 'batch_tryon.export_partial_confirmation_required') throw error
    if (!window.confirm(`${error.message}\n\n我们会在压缩包里附上未导出项清单，方便你稍后补下载。`)) return null
    return download(true)
  }
}

export function downloadErrorMessage(error: unknown): string {
  if (error instanceof AuthApiError) {
    return `${error.message}${error.requestId && !error.message.includes(error.requestId) ? `（请求编号：${error.requestId}）` : ''}`
  }
  return error instanceof Error ? error.message : '下载失败，请重试。'
}

export async function downloadServerOutputZip(outputs: JobOutput[], filename: string) {
  if (!outputs.length) throw new Error('没有可下载的成功结果')
  const files: Record<string, Uint8Array> = {}
  for (const [index, output] of outputs.entries()) {
    const safeName = output.filename.replace(/[\\/:*?"<>|]/g, '_')
    files[`${String(index + 1).padStart(3, '0')}-${safeName}`] = new Uint8Array(await (await fetchAssetBlob(output.url)).arrayBuffer())
  }
  saveBlob(new Blob([zipSync(files, { level: 0 }) as BlobPart], { type: 'application/zip' }), filename)
}
