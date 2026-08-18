import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  resolveValidationWorkflowTemplateId,
  type BatchTryOnWorkflowResponse,
  updateBatchTryOnPromptPreset,
} from './batchTryOnWorkflowApi'

afterEach(() => vi.unstubAllGlobals())

describe('batch try-on prompt preset API', () => {
  it('recovers the validation template from a durable workflow response', () => {
    const workflow = {
      submission_kind: 'validation',
      combinations: [{ template_id: 'template-1', client_item_id: 'validation:item-1' }],
      templates: [{ template_id: 'template-fallback' }],
    } as BatchTryOnWorkflowResponse
    expect(resolveValidationWorkflowTemplateId(workflow)).toBe('template-1')
    expect(resolveValidationWorkflowTemplateId({ ...workflow, submission_kind: 'production' })).toBeUndefined()
  })

  it('updates a preset through the protected preset endpoint', async () => {
    const response = {
      id: 'preset-1', scope: 'system', organization_id: null, owner_user_id: null,
      template_type: 'pure_white', label: '纯白底图', analysis_prompt_template: 'updated prompt text long enough',
      enabled: true, sort_order: 10, is_system_preset: true,
    }
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(response), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)

    await updateBatchTryOnPromptPreset('preset/1', {
      label: '纯白底图', analysis_prompt_template: 'updated prompt text long enough',
    })

    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/batch-tryon/prompt-presets/preset%2F1')
    expect(fetchMock.mock.calls[0][1].method).toBe('PATCH')
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      label: '纯白底图', analysis_prompt_template: 'updated prompt text long enough',
    })
  })
})
