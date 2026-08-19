import { afterEach, describe, expect, it, vi } from 'vitest'
import { clearAccessToken } from './authApi'
import {
  getAttachmentPlanning,
  getAttachmentReferences,
  addAttachmentReference,
  removeAttachmentReference,
  analyzeAttachmentReferences,
  listAttachmentPlanVersions,
  optimizeAttachmentModulePrompt,
  planAttachmentSuite,
  replanAttachmentModule,
  updateAttachmentModule,
  updateAttachmentVisualDirection,
  previewAttachmentGeneration,
  generateAttachments,
} from './attachmentPlanningApi'

afterEach(() => {
  clearAccessToken()
  vi.unstubAllGlobals()
})

function ok(body: unknown = {}) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('attachment planning API', () => {
  it('keeps reference upload, unlink and analysis as separate durable operations', async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(ok({ modules: [] })))
    vi.stubGlobal('fetch', fetchMock)

    await getAttachmentReferences('project-1')
    await addAttachmentReference('project-1', 'gift_scene', { slot_type: 'PRINT', asset_id: 'asset-1' })
    await removeAttachmentReference('project-1', 'gift_scene', 'reference-1')
    await analyzeAttachmentReferences('project-1', 'gift_scene', 'attachment-reference:test')

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      '/api/v1/attachment-workbench/projects/project-1/references',
      '/api/v1/attachment-workbench/projects/project-1/modules/gift_scene/references',
      '/api/v1/attachment-workbench/projects/project-1/modules/gift_scene/references/reference-1',
      '/api/v1/attachment-workbench/projects/project-1/modules/gift_scene/references/analyze',
    ])
    expect((fetchMock.mock.calls[2][1] as RequestInit).method).toBe('DELETE')
  })

  it('uses one suite request and keeps selected module context structured', async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(ok({ modules: [] })))
    vi.stubGlobal('fetch', fetchMock)

    await planAttachmentSuite('project-1', {
      modules: [
        { module_key: 'pure_white', aspect_ratio: '1:1', operator_requirement_cn: '' },
        { module_key: 'gift_scene', aspect_ratio: '4:5', operator_requirement_cn: '突出送礼氛围' },
      ],
      visual_direction_cn: '统一真实商品质感',
      idempotency_key: 'attachment-suite:test',
    })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/attachment-workbench/projects/project-1/plan')
    const input = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string)
    expect(input.modules.map((item: { module_key: string }) => item.module_key)).toEqual(['pure_white', 'gift_scene'])
    expect(input.modules[1].aspect_ratio).toBe('4:5')
  })

  it('keeps suite, module, optimizer, manual edit and version routes separate', async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(ok({ modules: [] })))
    vi.stubGlobal('fetch', fetchMock)

    await getAttachmentPlanning('project-1')
    await replanAttachmentModule('project-1', 'gift_scene', {
      aspect_ratio: '4:5', operator_requirement_cn: '', idempotency_key: 'module-replan:test',
    })
    await optimizeAttachmentModulePrompt('project-1', 'gift_scene', {
      aspect_ratio: '4:5', operator_requirement_cn: '', idempotency_key: 'module-optimize:test',
    })
    await updateAttachmentVisualDirection('project-1', {
      visual_direction_cn: '干净商业光线', expected_state_version: 2,
    })
    await updateAttachmentModule('project-1', 'gift_scene', {
      prompt_cn: '完整中文提示词', expected_state_version: 3,
    })
    await listAttachmentPlanVersions('project-1', 'gift_scene')

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      '/api/v1/attachment-workbench/projects/project-1/planning',
      '/api/v1/attachment-workbench/projects/project-1/modules/gift_scene/replan',
      '/api/v1/attachment-workbench/projects/project-1/modules/gift_scene/optimize-prompt',
      '/api/v1/attachment-workbench/projects/project-1/visual-direction',
      '/api/v1/attachment-workbench/projects/project-1/modules/gift_scene',
      '/api/v1/attachment-workbench/projects/project-1/versions?module_key=gift_scene',
    ])
    expect((fetchMock.mock.calls[3][1] as RequestInit).method).toBe('PATCH')
    expect((fetchMock.mock.calls[4][1] as RequestInit).method).toBe('PATCH')
  })

  it('previews the durable snapshot before submitting an idempotent generation batch', async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(ok({ modules: [] })))
    vi.stubGlobal('fetch', fetchMock)

    await previewAttachmentGeneration('project-1', ['gift_scene', 'detail_display'])
    await generateAttachments('project-1', {
      selected_module_keys: ['gift_scene', 'detail_display'],
      snapshot_signature: 'a'.repeat(64),
      idempotency_key: 'attachment-generate:test',
    })

    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/attachment-workbench/projects/project-1/generation-preview')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/v1/attachment-workbench/projects/project-1/generate')
    const previewBody = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string)
    const generationBody = JSON.parse((fetchMock.mock.calls[1][1] as RequestInit).body as string)
    expect(previewBody.selected_module_keys).toEqual(['gift_scene', 'detail_display'])
    expect(generationBody.snapshot_signature).toHaveLength(64)
    expect(generationBody.idempotency_key).toBe('attachment-generate:test')
  })
})
