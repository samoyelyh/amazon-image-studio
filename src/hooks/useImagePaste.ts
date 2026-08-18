import { useCallback, type ClipboardEvent, type PointerEvent } from 'react'

export interface ClipboardImageItemLike {
  type: string
  getAsFile: () => File | null
}

const MIME_EXTENSIONS: Record<string, string> = {
  'image/jpeg': 'jpg',
  'image/png': 'png',
  'image/webp': 'webp',
  'image/gif': 'gif',
  'image/avif': 'avif',
}

function timestampPart(now: number): string {
  const date = new Date(now)
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}-${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`
}

export function extractClipboardImageFiles(
  items: ArrayLike<ClipboardImageItemLike>,
  now = Date.now(),
): File[] {
  const stamp = timestampPart(now)
  return Array.from(items)
    .filter((item) => item.type.startsWith('image/'))
    .flatMap((item, index) => {
      const source = item.getAsFile()
      if (!source) return []
      const extension = MIME_EXTENSIONS[source.type]
        || source.type.split('/')[1]?.replace(/[^a-z0-9]/gi, '').toLowerCase()
        || 'png'
      return [new File([source], `pasted-image-${stamp}-${index + 1}.${extension}`, {
        type: source.type || item.type,
        lastModified: now,
      })]
    })
}

interface UseImagePasteOptions {
  disabled?: boolean
  maxFiles?: number
  onPasteFiles: (files: File[]) => void | Promise<void>
}

export function useImagePaste({ disabled = false, maxFiles, onPasteFiles }: UseImagePasteOptions) {
  const onPaste = useCallback((event: ClipboardEvent<HTMLElement>) => {
    if (disabled) return
    const files = extractClipboardImageFiles(event.clipboardData.items)
    if (!files.length) return
    event.preventDefault()
    event.stopPropagation()
    const accepted = typeof maxFiles === 'number' ? files.slice(0, Math.max(0, maxFiles)) : files
    if (accepted.length) void onPasteFiles(accepted)
  }, [disabled, maxFiles, onPasteFiles])

  const onPointerDownCapture = useCallback((event: PointerEvent<HTMLElement>) => {
    if (disabled) return
    const target = event.target as HTMLElement
    if (target.closest('input, textarea, select, [contenteditable="true"]')) return
    event.currentTarget.focus({ preventScroll: true })
  }, [disabled])

  return {
    onPaste,
    onPointerDownCapture,
    tabIndex: disabled ? -1 : 0,
    'aria-keyshortcuts': 'Control+V Meta+V',
  } as const
}

