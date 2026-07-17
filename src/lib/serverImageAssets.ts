import { dataUrlToBlob } from './canvasImage'
import { storeImage } from './db'
import { uploadAsset, type Asset, type AssetCategory } from './contentApi'
import type { JobOutput } from './jobsApi'

function extensionForMime(mime: string) {
  if (mime === 'image/jpeg') return 'jpg'
  if (mime === 'image/webp') return 'webp'
  return 'png'
}

export async function uploadDataUrlAsset(
  dataUrl: string,
  category: AssetCategory,
  basename = 'reference',
): Promise<Asset> {
  const blob = await dataUrlToBlob(dataUrl)
  const extension = extensionForMime(blob.type)
  const file = new File([blob], `${basename}.${extension}`, { type: blob.type || `image/${extension}` })
  return uploadAsset(file, category)
}

export async function importServerOutput(output: JobOutput): Promise<string> {
  const response = await fetch(output.url)
  if (!response.ok) throw new Error(`生成结果下载失败（HTTP ${response.status}）`)
  const blob = await response.blob()
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(reader.error ?? new Error('生成结果读取失败'))
    reader.readAsDataURL(blob)
  })
  return storeImage(dataUrl, 'generated')
}
