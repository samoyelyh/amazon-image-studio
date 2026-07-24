import { dataUrlToBlob } from './canvasImage'
import { storeImage } from './db'
import { fetchAssetBlob, uploadAsset, type Asset, type UploadAssetCategory } from './contentApi'
import type { JobOutput } from './jobsApi'

function extensionForMime(mime: string) {
  if (mime === 'image/jpeg') return 'jpg'
  if (mime === 'image/webp') return 'webp'
  return 'png'
}

export async function uploadDataUrlAsset(
  dataUrl: string,
  category: UploadAssetCategory,
  filename = 'reference',
): Promise<Asset> {
  const blob = await dataUrlToBlob(dataUrl)
  const extension = extensionForMime(blob.type)
  const resolvedFilename = /\.(?:png|jpe?g|webp)$/i.test(filename) ? filename : `${filename}.${extension}`
  const file = new File([blob], resolvedFilename, { type: blob.type || `image/${extension}` })
  return uploadAsset(file, category)
}

export async function importServerOutput(output: JobOutput): Promise<string> {
  const blob = await fetchAssetBlob(output.url)
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(reader.error ?? new Error('生成结果读取失败'))
    reader.readAsDataURL(blob)
  })
  return storeImage(dataUrl, 'generated')
}

export async function importServerAsset(asset: Asset): Promise<string> {
  if (!asset.url) throw new Error('服务端图片地址不存在')
  const blob = await fetchAssetBlob(asset.url)
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(reader.error ?? new Error('服务端图片读取失败'))
    reader.readAsDataURL(blob)
  })
  return storeImage(dataUrl, 'generated')
}
