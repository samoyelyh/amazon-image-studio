import { useEffect, useState } from 'react'
import { fetchAssetBlob } from '../../lib/contentApi'

interface Props {
  url: string | null
  alt: string
  className?: string
  placeholderClassName?: string
  unavailableText?: string
  allowZoom?: boolean
}

export default function AuthenticatedImage({ url, alt, className = '', placeholderClassName = '', unavailableText = '图片加载失败', allowZoom = true }: Props) {
  const [objectUrl, setObjectUrl] = useState('')
  const [retry, setRetry] = useState(0)
  const [failed, setFailed] = useState(!url)
  const [zoomed, setZoomed] = useState(false)

  useEffect(() => {
    let active = true
    let nextUrl = ''
    setFailed(!url); setObjectUrl('')
    if (url) void fetchAssetBlob(url).then((blob) => {
      if (!active) return
      nextUrl = URL.createObjectURL(blob); setObjectUrl(nextUrl); setFailed(false)
    }).catch(() => { if (active) setFailed(true) })
    return () => { active = false; if (nextUrl) URL.revokeObjectURL(nextUrl) }
  }, [url, retry])

  if (!objectUrl || failed) return <div className={`flex flex-col items-center justify-center gap-2 bg-gray-50 text-center text-xs text-gray-500 dark:bg-white/[0.03] ${placeholderClassName}`}><span>{unavailableText}</span>{url && <button className="font-semibold text-blue-600" onClick={() => setRetry((value) => value + 1)}>重新加载</button>}</div>
  return <>
    <button type="button" className="block w-full" onClick={() => allowZoom && setZoomed(true)}><img src={objectUrl} className={className} alt={alt} /></button>
    {zoomed && <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/85 p-6" role="dialog" aria-label={`查看大图：${alt}`} onClick={() => setZoomed(false)}><button className="absolute right-5 top-5 rounded-full bg-white/15 px-4 py-2 text-sm font-semibold text-white" onClick={() => setZoomed(false)}>关闭</button><img src={objectUrl} className="max-h-full max-w-full object-contain" alt={alt} /></div>}
  </>
}
