import { describe, expect, it, vi } from 'vitest'
import {
  DELETE_CONFIRMATION_MS,
  createDeleteConfirmation,
  executeReviewShortcut,
  isDeleteConfirmationValid,
  isTypingTarget,
  registerReviewShortcutListener,
  resolveReviewShortcut,
  type DeleteConfirmationState,
  type ReviewShortcutExecutionContext,
} from './useBatchTryOnReviewShortcuts'

const emptyConfirmation: DeleteConfirmationState = {
  armed: false, itemId: null, versionId: null, expiresAt: null,
}

function typingTarget(selectorMatch: boolean) {
  return { closest: vi.fn().mockReturnValue(selectorMatch ? {} : null) } as unknown as EventTarget
}

function context(overrides: Partial<ReviewShortcutExecutionContext> = {}): ReviewShortcutExecutionContext {
  return {
    enabled: true,
    currentItemId: 'item-1',
    currentVersionId: 'version-1',
    isBusy: false,
    hasApprovePermission: true,
    hasRegeneratePermission: true,
    canApprove: true,
    canRegenerate: true,
    approveUnavailableMessage: '不能审核',
    regenerateUnavailableMessage: '不能重新生成',
    onPrevious: vi.fn(),
    onNext: vi.fn(),
    onApprove: vi.fn(),
    onConfirmRegenerate: vi.fn(),
    onNotice: vi.fn(),
    confirmation: emptyConfirmation,
    isRepeat: false,
    replaceConfirmation: vi.fn(),
    cancelConfirmation: vi.fn(),
    now: 1_000,
    ...overrides,
  }
}

describe('batch try-on review shortcut key resolution', () => {
  it.each([
    ['ArrowLeft', undefined, 'previous'],
    ['ArrowRight', undefined, 'next'],
    ['Enter', undefined, 'approve'],
    ['Delete', undefined, 'delete'],
    ['Escape', undefined, 'cancel'],
  ])('maps %s to %s', (key, code, action) => {
    expect(resolveReviewShortcut({ key, code })).toBe(action)
  })

  it('supports the physical Delete code fallback', () => {
    expect(resolveReviewShortcut({ key: 'Unidentified', code: 'Delete' })).toBe('delete')
  })

  it('does not bind Backspace or unrelated keys', () => {
    expect(resolveReviewShortcut({ key: 'Backspace' })).toBeNull()
    expect(resolveReviewShortcut({ key: 'A' })).toBeNull()
  })

  it.each(['input', 'textarea', 'select', 'button', 'contenteditable'])(
    'protects a focused %s-like typing target',
    () => {
      expect(resolveReviewShortcut({ key: 'Enter', target: typingTarget(true) })).toBeNull()
    },
  )

  it('allows shortcuts for non-typing targets', () => {
    expect(isTypingTarget(typingTarget(false))).toBe(false)
    expect(resolveReviewShortcut({ key: 'ArrowRight', target: typingTarget(false) })).toBe('next')
  })

  it('ignores IME composition events', () => {
    expect(resolveReviewShortcut({ key: 'Enter', isComposing: true })).toBeNull()
  })
})

describe('batch try-on review shortcut execution', () => {
  it('moves to the previous item without changing review state', () => {
    const current = context()
    expect(executeReviewShortcut('previous', current)).toBe(true)
    expect(current.cancelConfirmation).toHaveBeenCalledOnce()
    expect(current.onPrevious).toHaveBeenCalledOnce()
    expect(current.onApprove).not.toHaveBeenCalled()
  })

  it('moves to the next item without changing review state', () => {
    const current = context()
    executeReviewShortcut('next', current)
    expect(current.onNext).toHaveBeenCalledOnce()
    expect(current.onConfirmRegenerate).not.toHaveBeenCalled()
  })

  it('runs the existing approval callback for Enter', () => {
    const current = context()
    executeReviewShortcut('approve', current)
    expect(current.onApprove).toHaveBeenCalledOnce()
  })

  it('does not repeat approval while Enter is held', () => {
    const current = context({ isRepeat: true })
    executeReviewShortcut('approve', current)
    expect(current.onApprove).not.toHaveBeenCalled()
  })

  it('shows a clear message when the current item is not approvable', () => {
    const current = context({ canApprove: false })
    executeReviewShortcut('approve', current)
    expect(current.onNotice).toHaveBeenCalledWith('不能审核', 'warning')
  })

  it('does not take over Enter for a viewer', () => {
    const current = context({ hasApprovePermission: false })
    expect(executeReviewShortcut('approve', current)).toBe(false)
    expect(current.onApprove).not.toHaveBeenCalled()
  })

  it('locks navigation and submission while a request is busy', () => {
    const current = context({ isBusy: true })
    executeReviewShortcut('next', current)
    executeReviewShortcut('approve', current)
    expect(current.onNext).not.toHaveBeenCalled()
    expect(current.onApprove).not.toHaveBeenCalled()
    expect(current.onNotice).toHaveBeenCalledWith('当前操作正在处理中，请稍候。', 'info')
  })

  it('arms Delete without immediately regenerating', () => {
    const current = context()
    executeReviewShortcut('delete', current)
    expect(current.replaceConfirmation).toHaveBeenCalledWith({
      armed: true,
      itemId: 'item-1',
      versionId: 'version-1',
      expiresAt: 1_000 + DELETE_CONFIRMATION_MS,
    })
    expect(current.onConfirmRegenerate).not.toHaveBeenCalled()
  })

  it('confirms regeneration on the second Delete within five seconds', () => {
    const confirmation = createDeleteConfirmation('item-1', 'version-1', 1_000)
    const current = context({ confirmation, now: 2_000 })
    executeReviewShortcut('delete', current)
    expect(current.onConfirmRegenerate).toHaveBeenCalledOnce()
    expect(current.replaceConfirmation).toHaveBeenCalledWith(emptyConfirmation)
  })

  it('does not confirm regeneration after the five-second timeout', () => {
    const confirmation = createDeleteConfirmation('item-1', 'version-1', 1_000)
    const current = context({ confirmation, now: 6_001 })
    executeReviewShortcut('delete', current)
    expect(current.onConfirmRegenerate).not.toHaveBeenCalled()
    expect(current.replaceConfirmation).toHaveBeenCalledWith(expect.objectContaining({ armed: true, expiresAt: 11_001 }))
  })

  it('does not regenerate a different item after navigation', () => {
    const confirmation = createDeleteConfirmation('item-A', 'version-A', 1_000)
    const current = context({ confirmation, currentItemId: 'item-B', currentVersionId: 'version-B', now: 2_000 })
    executeReviewShortcut('delete', current)
    expect(current.onConfirmRegenerate).not.toHaveBeenCalled()
    expect(current.replaceConfirmation).toHaveBeenCalledWith(expect.objectContaining({ itemId: 'item-B', versionId: 'version-B' }))
  })

  it('ignores repeated Delete keydown events', () => {
    const current = context({ isRepeat: true })
    executeReviewShortcut('delete', current)
    expect(current.replaceConfirmation).not.toHaveBeenCalled()
    expect(current.onConfirmRegenerate).not.toHaveBeenCalled()
  })

  it('shows a clear message when regeneration is unavailable', () => {
    const current = context({ canRegenerate: false })
    executeReviewShortcut('delete', current)
    expect(current.onNotice).toHaveBeenCalledWith('不能重新生成', 'warning')
  })

  it('does not take over Delete for a viewer', () => {
    const current = context({ hasRegeneratePermission: false })
    expect(executeReviewShortcut('delete', current)).toBe(false)
  })

  it('requires stable item and version ids before arming Delete', () => {
    const current = context({ currentVersionId: null })
    executeReviewShortcut('delete', current)
    expect(current.onNotice).toHaveBeenCalledWith('当前图片信息尚未加载完成，不能重新生成。', 'warning')
  })

  it('cancels an armed Delete confirmation with Escape', () => {
    const current = context({ confirmation: createDeleteConfirmation('item-1', 'version-1', 1_000) })
    expect(executeReviewShortcut('cancel', current)).toBe(true)
    expect(current.cancelConfirmation).toHaveBeenCalledWith('已取消重新生成')
  })

  it('leaves Escape alone when no confirmation is armed', () => {
    const current = context()
    expect(executeReviewShortcut('cancel', current)).toBe(false)
  })
})

describe('Delete confirmation identity and listener lifecycle', () => {
  it('validates item, version and expiry together', () => {
    const confirmation = createDeleteConfirmation('item-1', 'version-1', 1_000)
    expect(isDeleteConfirmationValid(confirmation, 'item-1', 'version-1', 5_999)).toBe(true)
    expect(isDeleteConfirmationValid(confirmation, 'item-2', 'version-1', 2_000)).toBe(false)
    expect(isDeleteConfirmationValid(confirmation, 'item-1', 'version-2', 2_000)).toBe(false)
    expect(isDeleteConfirmationValid(confirmation, 'item-1', 'version-1', 6_000)).toBe(false)
  })

  it('removes exactly the listener that it registered', () => {
    const addEventListener = vi.fn()
    const removeEventListener = vi.fn()
    const listener = vi.fn()
    const cleanup = registerReviewShortcutListener({ addEventListener, removeEventListener }, listener)
    expect(addEventListener).toHaveBeenCalledWith('keydown', listener)
    cleanup()
    expect(removeEventListener).toHaveBeenCalledWith('keydown', listener)
  })
})
