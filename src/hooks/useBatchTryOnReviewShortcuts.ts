import { useEffect, useRef, useState } from 'react'

export const DELETE_CONFIRMATION_MS = 5_000

export type ReviewShortcutNoticeTone = 'info' | 'success' | 'warning'

export type DeleteConfirmationState = {
  armed: boolean
  itemId: string | null
  versionId: string | null
  expiresAt: number | null
}

export type ReviewShortcutAction = 'previous' | 'next' | 'approve' | 'delete' | 'cancel'

type ShortcutEvent = {
  key: string
  code?: string
  isComposing?: boolean
  target?: EventTarget | null
}

type ListenerTarget = {
  addEventListener: (type: string, listener: EventListener) => void
  removeEventListener: (type: string, listener: EventListener) => void
}

export interface BatchTryOnReviewShortcutOptions {
  enabled: boolean
  currentItemId: string | null
  currentVersionId: string | null
  isBusy: boolean
  hasApprovePermission: boolean
  hasRegeneratePermission: boolean
  canApprove: boolean
  canRegenerate: boolean
  approveUnavailableMessage: string
  regenerateUnavailableMessage: string
  onPrevious: () => void
  onNext: () => void
  onApprove: () => void
  onConfirmRegenerate: () => void
  onNotice: (message: string, tone?: ReviewShortcutNoticeTone) => void
}

export interface ReviewShortcutExecutionContext extends BatchTryOnReviewShortcutOptions {
  confirmation: DeleteConfirmationState
  isRepeat: boolean
  now?: number
  replaceConfirmation: (confirmation: DeleteConfirmationState) => void
  cancelConfirmation: (message?: string) => void
}

const EMPTY_CONFIRMATION: DeleteConfirmationState = {
  armed: false,
  itemId: null,
  versionId: null,
  expiresAt: null,
}

export function isTypingTarget(target: EventTarget | null | undefined): boolean {
  const candidate = target as { closest?: (selectors: string) => unknown } | null | undefined
  return Boolean(candidate?.closest?.('input, textarea, select, button, [contenteditable="true"]'))
}

export function resolveReviewShortcut(event: ShortcutEvent): ReviewShortcutAction | null {
  if (event.isComposing || isTypingTarget(event.target)) return null
  if (event.key === 'ArrowLeft') return 'previous'
  if (event.key === 'ArrowRight') return 'next'
  if (event.key === 'Enter') return 'approve'
  if (event.key === 'Escape') return 'cancel'
  if (event.key === 'Delete' || event.code === 'Delete') return 'delete'
  return null
}

export function createDeleteConfirmation(
  itemId: string,
  versionId: string,
  now = Date.now(),
): DeleteConfirmationState {
  return {
    armed: true,
    itemId,
    versionId,
    expiresAt: now + DELETE_CONFIRMATION_MS,
  }
}

export function isDeleteConfirmationValid(
  confirmation: DeleteConfirmationState,
  itemId: string | null,
  versionId: string | null,
  now = Date.now(),
): boolean {
  return Boolean(
    confirmation.armed
    && confirmation.itemId === itemId
    && confirmation.versionId === versionId
    && confirmation.expiresAt
    && confirmation.expiresAt > now,
  )
}

export function registerReviewShortcutListener(
  target: ListenerTarget,
  listener: (event: KeyboardEvent) => void,
) {
  const eventListener = listener as EventListener
  target.addEventListener('keydown', eventListener)
  return () => target.removeEventListener('keydown', eventListener)
}

export function executeReviewShortcut(
  action: ReviewShortcutAction,
  context: ReviewShortcutExecutionContext,
): boolean {
  if (action === 'cancel') {
    if (!context.confirmation.armed) return false
    context.cancelConfirmation('已取消重新生成')
    return true
  }
  if (action === 'approve' && !context.hasApprovePermission) return false
  if (action === 'delete' && !context.hasRegeneratePermission) return false

  if (context.isBusy) {
    context.onNotice('当前操作正在处理中，请稍候。', 'info')
    return true
  }

  if (action === 'previous' || action === 'next') {
    context.cancelConfirmation()
    if (action === 'previous') context.onPrevious()
    else context.onNext()
    return true
  }

  if (action === 'approve') {
    if (context.isRepeat) return true
    if (!context.canApprove) {
      context.onNotice(context.approveUnavailableMessage, 'warning')
      return true
    }
    context.cancelConfirmation()
    context.onApprove()
    return true
  }

  if (context.isRepeat) return true
  if (!context.canRegenerate) {
    context.onNotice(context.regenerateUnavailableMessage, 'warning')
    return true
  }
  if (!context.currentItemId || !context.currentVersionId) {
    context.onNotice('当前图片信息尚未加载完成，不能重新生成。', 'warning')
    return true
  }
  if (isDeleteConfirmationValid(
    context.confirmation,
    context.currentItemId,
    context.currentVersionId,
    context.now,
  )) {
    context.replaceConfirmation(EMPTY_CONFIRMATION)
    context.onConfirmRegenerate()
    return true
  }
  context.replaceConfirmation(createDeleteConfirmation(
    context.currentItemId,
    context.currentVersionId,
    context.now,
  ))
  return true
}

export function useBatchTryOnReviewShortcuts(options: BatchTryOnReviewShortcutOptions) {
  const optionsRef = useRef(options)
  const confirmationRef = useRef<DeleteConfirmationState>(EMPTY_CONFIRMATION)
  const [deleteConfirmation, setDeleteConfirmation] = useState<DeleteConfirmationState>(EMPTY_CONFIRMATION)
  const [remainingSeconds, setRemainingSeconds] = useState(0)
  optionsRef.current = options

  const replaceConfirmation = (next: DeleteConfirmationState) => {
    confirmationRef.current = next
    setDeleteConfirmation(next)
  }

  const cancelDeleteConfirmation = (message?: string) => {
    if (!confirmationRef.current.armed) return
    replaceConfirmation(EMPTY_CONFIRMATION)
    setRemainingSeconds(0)
    if (message) optionsRef.current.onNotice(message, 'info')
  }

  useEffect(() => {
    if (!deleteConfirmation.armed || !deleteConfirmation.expiresAt) return
    const updateRemaining = () => {
      const remaining = deleteConfirmation.expiresAt! - Date.now()
      if (remaining <= 0) {
        cancelDeleteConfirmation('已取消重新生成确认')
        return
      }
      setRemainingSeconds(Math.ceil(remaining / 1_000))
    }
    updateRemaining()
    const timer = window.setInterval(updateRemaining, 200)
    return () => window.clearInterval(timer)
  }, [deleteConfirmation.armed, deleteConfirmation.expiresAt])

  useEffect(() => {
    const confirmation = confirmationRef.current
    if (!confirmation.armed) return
    if (
      confirmation.itemId !== options.currentItemId
      || confirmation.versionId !== options.currentVersionId
      || !options.canRegenerate
    ) {
      cancelDeleteConfirmation()
    }
  }, [options.currentItemId, options.currentVersionId, options.canRegenerate])

  useEffect(() => registerReviewShortcutListener(window, (event) => {
    const action = resolveReviewShortcut(event)
    const current = optionsRef.current
    if (!current.enabled || !action) return
    const handled = executeReviewShortcut(action, {
      ...current,
      confirmation: confirmationRef.current,
      isRepeat: event.repeat,
      replaceConfirmation: (confirmation) => {
        replaceConfirmation(confirmation)
        if (!confirmation.armed) setRemainingSeconds(0)
      },
      cancelConfirmation: cancelDeleteConfirmation,
    })
    if (handled) {
      event.preventDefault()
      event.stopPropagation()
    }
  }), [])

  return {
    deleteConfirmation,
    remainingSeconds,
    cancelDeleteConfirmation,
  }
}
