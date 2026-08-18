import { describe, expect, it } from 'vitest'
import { syncBatchTryOnPromptDrafts } from './batchTryOnPromptDrafts'

describe('syncBatchTryOnPromptDrafts', () => {
  it('fills the final prompt when an analyzing record becomes ready', () => {
    const analyzing = syncBatchTryOnPromptDrafts({}, {}, [{
      id: 'prompt-1',
      generated_final_prompt: null,
      edited_final_prompt: null,
    }])

    const ready = syncBatchTryOnPromptDrafts(analyzing.drafts, analyzing.serverPrompts, [{
      id: 'prompt-1',
      generated_final_prompt: 'Use the current garment as the only visual source.',
      edited_final_prompt: null,
    }])

    expect(ready.drafts['prompt-1']).toBe('Use the current garment as the only visual source.')
  })

  it('keeps a user edit during ordinary workflow polling', () => {
    const result = syncBatchTryOnPromptDrafts(
      { 'prompt-1': 'My reviewed prompt' },
      { 'prompt-1': 'AI prompt' },
      [{ id: 'prompt-1', generated_final_prompt: 'AI prompt', edited_final_prompt: null }],
    )

    expect(result.drafts['prompt-1']).toBe('My reviewed prompt')
  })

  it('replaces the previous server value after reanalysis completes', () => {
    const result = syncBatchTryOnPromptDrafts(
      { 'prompt-1': 'Old AI prompt' },
      { 'prompt-1': 'Old AI prompt' },
      [{ id: 'prompt-1', generated_final_prompt: 'New AI prompt', edited_final_prompt: null }],
    )

    expect(result.drafts['prompt-1']).toBe('New AI prompt')
  })
})
