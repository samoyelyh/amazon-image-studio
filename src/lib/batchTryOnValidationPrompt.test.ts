import { describe, expect, it } from 'vitest'
import type { BatchTryOnTemplatePrompt } from './batchTryOnWorkflowApi'
import { resolveBatchTryOnValidationPromptValues } from './batchTryOnValidationPrompt'

function record(overrides: Partial<BatchTryOnTemplatePrompt> = {}): BatchTryOnTemplatePrompt {
  return {
    id: 'prompt-1',
    workflow_job_id: 'workflow-1',
    template_id: 'template-1',
    garment_id: 'garment-1',
    client_item_id: 'template-1:garment-1',
    template_type: 'pure_white',
    preset_id: 'preset-1',
    template_asset_id: 'template-asset-1',
    first_garment_asset_id: 'garment-asset-1',
    font_reference_asset_id: null,
    analysis_job_id: 'analysis-1',
    analysis_prompt_used: 'SYSTEM PRESET FOR EVERY GARMENT',
    generated_final_prompt: 'FIRST GARMENT FINAL PROMPT',
    edited_final_prompt: null,
    prompt_status: 'effective',
    prompt_version: 2,
    error_code: null,
    error_message: null,
    ...overrides,
  }
}

describe('resolveBatchTryOnValidationPromptValues', () => {
  it('never replaces the reusable analysis preset with one garment Luna output', () => {
    const result = resolveBatchTryOnValidationPromptValues(
      'EDITABLE SYSTEM PRESET',
      record(),
    )

    expect(result.analysisPrompt).toBe('EDITABLE SYSTEM PRESET')
    expect(result.sampleFinalPrompt).toBe('FIRST GARMENT FINAL PROMPT')
  })

  it('shows an edited per-image result only in the read-only sample field', () => {
    const result = resolveBatchTryOnValidationPromptValues(
      'SYSTEM PRESET',
      record({ edited_final_prompt: 'EDITED SAMPLE FINAL PROMPT' }),
    )

    expect(result.analysisPrompt).toBe('SYSTEM PRESET')
    expect(result.sampleFinalPrompt).toBe('EDITED SAMPLE FINAL PROMPT')
    expect(result.sampleFinalPromptLabel).toContain('人工版')
  })
})
