import { useEffect, useState, type ImgHTMLAttributes } from 'react'
import { fetchAssetBlob } from '../lib/contentApi'

interface Props extends Omit<ImgHTMLAttributes<HTMLImageElement>, 'src'> {
  src: string | null | undefined
}

/**
 * Loads private server images with the same Bearer/refresh flow as API calls.
 * The blob URL is deliberately component-local and is never persisted.
 */
export default function AuthenticatedImage({ src, alt = '', ...props }: Props) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let cancelled = false
    let createdUrl: string | null = null
    setObjectUrl(null)
    setFailed(false)
    if (!src) return () => undefined

    if (src.startsWith('data:') || src.startsWith('blob:')) {
      setObjectUrl(src)
      return () => undefined
    }

    void fetchAssetBlob(src)
      .then((blob) => {
        if (cancelled) return
        createdUrl = URL.createObjectURL(blob)
        setObjectUrl(createdUrl)
      })
      .catch(() => {
        if (!cancelled) setFailed(true)
      })

    return () => {
      cancelled = true
      if (createdUrl) URL.revokeObjectURL(createdUrl)
    }
  }, [src])

  if (failed) return <div role="img" aria-label={`${alt} 加载失败`} className="flex h-full w-full items-center justify-center px-3 text-center text-xs text-red-500">图片加载失败，请刷新后重试</div>
  if (!objectUrl) return <div aria-label={`${alt} 加载中`} className="h-full w-full animate-pulse bg-gray-200/60 dark:bg-white/[0.05]" />
  return <img {...props} src={objectUrl} alt={alt} />
}
