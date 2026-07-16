import { zipSync } from 'fflate'
import { getImage } from './db'

const DATA_URL_PATTERN = /^data:([^;,]+)?(?:;[^,]*)?;base64,(.*)$/s
const MIME_EXTENSION: Record<string, string> = {
  'image/jpeg': 'jpg',
  'image/png': 'png',
  'image/webp': 'webp',
}

export interface BatchTryOnDownloadItem {
  imageId: string
  garmentFileName: string
  index: number
}

export function sanitizeBatchTryOnFileBase(fileName: string) {
  const withoutExtension = fileName.replace(/\.[^.]+$/, '')
  return withoutExtension
    .normalize('NFKC')
    .replace(/[<>:"/\\|?*\u0000-\u001F]/g, '_')
    .replace(/[. ]+$/g, '')
    .trim()
    .slice(0, 100) || 'garment'
}

export function createBatchTryOnFileNames(
  items: Array<Pick<BatchTryOnDownloadItem, 'garmentFileName' | 'index'>>,
  extensions: string[] = [],
) {
  const used = new Set<string>()
  return items.map((item, itemIndex) => {
    const base = `${sanitizeBatchTryOnFileBase(item.garmentFileName)}_tryon_${String(item.index + 1).padStart(3, '0')}`
    const extension = extensions[itemIndex] || 'jpg'
    let candidate = `${base}.${extension}`
    let duplicateIndex = 2
    while (used.has(candidate.toLowerCase())) {
      candidate = `${base}_${duplicateIndex}.${extension}`
      duplicateIndex++
    }
    used.add(candidate.toLowerCase())
    return candidate
  })
}

export async function downloadBatchTryOnZip(items: BatchTryOnDownloadItem[], batchId: string) {
  if (items.length === 0) return { successCount: 0, failCount: 0 }

  const files: Array<{ bytes: Uint8Array; extension: string; item: BatchTryOnDownloadItem }> = []
  let failCount = 0
  for (const item of items) {
    const image = await getImage(item.imageId)
    const decoded = image ? decodeImageDataUrl(image.dataUrl) : null
    if (!decoded) {
      failCount++
      continue
    }
    files.push({ bytes: decoded.bytes, extension: decoded.extension, item })
  }

  if (files.length === 0) return { successCount: 0, failCount }
  const names = createBatchTryOnFileNames(files.map((file) => file.item), files.map((file) => file.extension))
  const zipEntries: Record<string, Uint8Array> = {}
  files.forEach((file, index) => {
    zipEntries[names[index]] = file.bytes
  })
  const zipped = zipSync(zipEntries, { level: 6 })
  const zipBytes = new Uint8Array(zipped.length)
  zipBytes.set(zipped)
  const blob = new Blob([zipBytes.buffer], { type: 'application/zip' })
  triggerDownload(blob, `batch-tryon_${sanitizeBatchTryOnFileBase(batchId)}.zip`)
  return { successCount: files.length, failCount }
}

function decodeImageDataUrl(dataUrl: string) {
  const match = dataUrl.match(DATA_URL_PATTERN)
  if (!match) return null
  const binary = atob(match[2])
  const bytes = new Uint8Array(binary.length)
  for (let index = 0; index < binary.length; index++) bytes[index] = binary.charCodeAt(index)
  return {
    bytes,
    extension: MIME_EXTENSION[(match[1] || '').toLowerCase()] || 'png',
  }
}

function triggerDownload(blob: Blob, fileName: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = fileName
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
}
