import { describe, expect, it } from 'vitest'
import { BATCH_TRY_ON_BASE_PROMPT, buildBatchTryOnPrompt } from './batchTryOnPrompt'

describe('buildBatchTryOnPrompt', () => {
  it('combines fidelity rules, file name, size, reference order, and additional requirements', () => {
    const prompt = buildBatchTryOnPrompt({
      garmentFileName: 'team-07.webp',
      outputSize: '1536x2048',
      extraRequirements: 'Keep the shirt untucked.',
    })

    expect(prompt).toContain(BATCH_TRY_ON_BASE_PROMPT)
    expect(prompt).toContain('team-07.webp')
    expect(prompt).toContain('1536x2048')
    expect(prompt).toContain('Keep the shirt untucked.')
    expect(prompt).toContain('Reference Image 1 is the model template')
    expect(prompt).toContain('Reference Image 2 is the garment')
    expect(prompt).toContain('must never override')
  })

  it('omits an empty additional requirements section', () => {
    const prompt = buildBatchTryOnPrompt({ garmentFileName: 'shirt.jpg', outputSize: '2048x2048' })
    expect(prompt).not.toContain('ADDITIONAL USER REQUIREMENTS')
  })

  it('appends review corrections without replacing the mandatory base prompt', () => {
    const prompt = buildBatchTryOnPrompt({
      garmentFileName: 'team-06.jpg',
      outputSize: '2048x2048',
      reviewNotes: 'The chest number must remain 06 with its leading zero.',
      retryMode: 'with_review_notes',
    })
    expect(prompt).toContain(BATCH_TRY_ON_BASE_PROMPT)
    expect(prompt.indexOf('REVIEW CORRECTION REQUIREMENTS:')).toBeGreaterThan(prompt.indexOf('FINAL PRIORITY:'))
    expect(prompt).toContain('The chest number must remain 06')
    expect(prompt).toContain('must not replace or weaken')
  })

  it('does not add an empty review correction section', () => {
    const prompt = buildBatchTryOnPrompt({ garmentFileName: 'shirt.jpg', outputSize: '2048x2048', reviewNotes: '  ' })
    expect(prompt).not.toContain('REVIEW CORRECTION REQUIREMENTS:')
  })
})
