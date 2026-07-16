import { useEffect, useState } from 'react'
import { ensureImageCached, ensureImageThumbnailCached } from '../store'

export function useBatchTryOnImageUrl(imageId?: string | null) {
  const [url, setUrl] = useState('')

  useEffect(() => {
    let cancelled = false
    setUrl('')
    if (!imageId) return () => { cancelled = true }

    void ensureImageThumbnailCached(imageId)
      .then((thumbnail) => thumbnail?.dataUrl || ensureImageCached(imageId))
      .then((nextUrl) => {
        if (!cancelled && nextUrl) setUrl(nextUrl)
      })
    return () => { cancelled = true }
  }, [imageId])

  return url
}

export function BatchTryOnImage({ imageId, alt, className = '' }: { imageId: string; alt: string; className?: string }) {
  const url = useBatchTryOnImageUrl(imageId)
  if (!url) {
    return <div className={`animate-pulse bg-gray-100 dark:bg-white/[0.06] ${className}`} aria-label={`${alt}加载中`} />
  }
  return <img src={url} alt={alt} className={className} />
}
