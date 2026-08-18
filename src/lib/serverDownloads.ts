import { zipSync } from 'fflate'
import type { JobOutput } from './jobsApi'
import { fetchAssetBlob } from './contentApi'
import { authenticatedFetchResponse } from './authApi'

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

function responseFilename(response: Response): string | null {
  const header = response.headers.get('Content-Disposition')
  if (!header) return null
  const encoded = header.match(/filename\\*=UTF-8''([^;]+)/i)?.[1]
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
  const response = await authenticatedFetchResponse(url, init)
  saveBlob(await response.blob(), responseFilename(response) || filename || 'download')
}

export async function downloadBatchTryOnResultsZip(batchId: string) {
  await downloadAuthenticatedFile(
    `/job-batches/${batchId}/batch-tryon-results.zip`,
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
) {
  await downloadAuthenticatedFile(
    `/batch-tryon/templates/${encodeURIComponent(templateId)}/download`,
    'batch-tryon-template-results.zip',
    {
      method: 'POST',
      body: JSON.stringify({ item_ids: reviewItemIds, scope }),
    },
  )
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
