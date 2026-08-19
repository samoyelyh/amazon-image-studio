import { describe, expect, it } from 'vitest'
import {
  countRequestedAttachmentImages,
  createAttachmentWorkbenchDraft,
  isAttachmentSessionReady,
  normalizeAttachmentWorkbenchDraft,
  selectedAttachmentModules,
  summarizeAttachmentTaskGroups,
} from './attachmentImageWorkbench'
import type { ListingImageTaskGroup } from './listingWorkflowApi'

describe('attachment image workbench draft', () => {
  it('creates the six football jersey modules with production-ready defaults', () => {
    const draft = createAttachmentWorkbenchDraft()
    expect(Object.keys(draft.modules)).toHaveLength(6)
    expect(draft.modules.pure_white.aspectRatio).toBe('1:1')
    expect(draft.modules.stadium_scene.aspectRatio).toBe('4:5')
    expect(selectedAttachmentModules(draft)).toHaveLength(6)
    expect(countRequestedAttachmentImages(draft)).toBe(6)
  })

  it('restores valid persisted values while clamping unsupported data', () => {
    const draft = normalizeAttachmentWorkbenchDraft({
      visualDirection: '统一运动商业视觉',
      modules: {
        pure_white: { selected: true, aspectRatio: '4:5', imageCount: 99, generationMode: 'creative' },
        custom_process: { selected: true, aspectRatio: '16:9', imageCount: 0, generationMode: 'unknown' },
        unknown_module: { selected: true, aspectRatio: '1:1', imageCount: 2 },
      },
    }, ['pure_white'])

    expect(draft.visualDirection).toBe('统一运动商业视觉')
    expect(draft.modules.pure_white).toEqual({ selected: true, aspectRatio: '4:5', imageCount: 4, generationMode: 'creative' })
    expect(draft.modules.custom_process).toEqual({ selected: false, aspectRatio: '1:1', imageCount: 1, generationMode: 'standard' })
    expect(Object.keys(draft.modules)).toHaveLength(6)
  })

  it('uses durable listing confirmation facts instead of session status', () => {
    expect(isAttachmentSessionReady({ confirmed_at: '2026-08-19T00:00:00Z', listing_version_number: 2 })).toBe(true)
    expect(isAttachmentSessionReady({ confirmed_at: null, listing_version_number: 2 })).toBe(false)
    expect(isAttachmentSessionReady({ confirmed_at: '2026-08-19T00:00:00Z', listing_version_number: null })).toBe(false)
  })
})

describe('attachment image task status', () => {
  it('aggregates real task group statistics without mixing generation and review states', () => {
    const groups = [
      { status: 'running', statistics: { total: 4, queued: 2, running: 1, succeeded: 1, failed: 0, cancelled: 0 } },
      { status: 'partially_succeeded', statistics: { total: 3, queued: 0, running: 0, succeeded: 2, failed: 1, cancelled: 0 } },
    ] as ListingImageTaskGroup[]

    expect(summarizeAttachmentTaskGroups(groups)).toEqual({
      total: 7,
      queued: 2,
      running: 1,
      succeeded: 3,
      failed: 1,
      cancelled: 0,
      activeGroups: 1,
      completedGroups: 1,
    })
  })
})
