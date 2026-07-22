import { zipSync } from 'fflate'
import type { JobOutput } from './jobsApi'
import { fetchAssetBlob } from './contentApi'

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
  saveBlob(await fetchAssetBlob(output.url), output.filename)
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
