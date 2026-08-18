import { useEffect, useState } from 'react'
import { fetchAssetBlob, getAsset } from '../lib/contentApi'
import { ensureImageCached, ensureImageThumbnailCached } from '../store'

export function useBatchTryOnImageUrl(imageId?: string | null, serverAssetId?: string | null) {
  const [url, setUrl] = useState('')
  const [error, setError] = useState('')
  const [retryVersion, setRetryVersion] = useState(0)

  useEffect(() => {
    let cancelled = false
    let objectUrl = ''
    setUrl('')
    setError('')
    if (!imageId && !serverAssetId) {
      setError('图片引用不存在')
      return () => { cancelled = true }
    }

    void (async () => {
      try {
        const localUrl = imageId
          ? (await ensureImageThumbnailCached(imageId))?.dataUrl || await ensureImageCached(imageId)
          : undefined
        if (localUrl) {
          if (!cancelled) setUrl(localUrl)
          return
        }
        if (!serverAssetId) throw new Error('本地图片缓存不存在')
        const asset = await getAsset(serverAssetId)
        if (!asset.url) throw new Error('服务端图片地址不存在')
        const blob = await fetchAssetBlob(asset.url)
        objectUrl = URL.createObjectURL(blob)
        if (!cancelled) setUrl(objectUrl)
      } catch (reason) {
        if (!cancelled) setError(reason instanceof Error ? reason.message : '图片加载失败')
      }
    })()

    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [imageId, retryVersion, serverAssetId])

  return { url, error, retry: () => setRetryVersion((value) => value + 1) }
}

export function BatchTryOnImage({ imageId, serverAssetId, alt, className = '' }: {
  imageId?: string | null
  serverAssetId?: string | null
  alt: string
  className?: string
}) {
  const { url, error, retry } = useBatchTryOnImageUrl(imageId, serverAssetId)
  if (error) {
    return <div onClick={(event) => { event.stopPropagation(); retry() }} className={`flex cursor-pointer flex-col items-center justify-center bg-red-50 px-2 text-center text-[11px] text-red-600 dark:bg-red-500/10 dark:text-red-200 ${className}`} aria-label={`${alt}加载失败，点击重试`}>
      <span>图片加载失败</span>
      <span className="mt-1 underline">点击重试</span>
    </div>
  }
  if (!url) {
    return <div className={`animate-pulse bg-gray-100 dark:bg-white/[0.06] ${className}`} aria-label={`${alt}加载中`} />
  }
  return <img src={url} alt={alt} className={className} />
}
