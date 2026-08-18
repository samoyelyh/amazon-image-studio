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

  it('uses the current garment as the only source of colors, text, numbers and graphics', () => {
    const prompt = buildBatchTryOnPrompt({
      garmentFileName: 'red-88.jpg',
      outputSize: '2048x2048',
      batchStyleProfile: {
        profileKey: 'profile-1',
        sourceSampleAssetId: 'sample-1',
        sourceGarmentId: 'garment-1',
        category: 'football_jersey',
        garmentStructure: { neckline: 'v_neck', sleeveType: 'short_sleeve', fit: 'cropped' },
        viewRules: { supportsFront: true, supportsBack: true, frontBackMustNotSwap: true },
        designRules: { preserveText: true, preserveNumbers: true, preserveNames: true, preserveGraphics: true, preserveFontStyle: true, preserveElementPosition: true },
        structureRules: { preserveNeckline: true, preserveSleeves: true, preserveGarmentLength: true, preserveSilhouette: true },
        analysisModel: 'gpt-test',
        analysisVersion: 'batch-style-v1',
        coveredGarmentIds: ['garment-1', 'garment-2'],
      },
    })
    expect(prompt).toContain('Reference Image 2, the CURRENT GARMENT REFERENCE IMAGE, is the only source of truth')
    expect(prompt).toContain('DO NOT inherit color, color combination, text, wording, name, number, logo, graphic')
    expect(prompt).toContain('v_neck')
    expect(prompt).not.toContain('black and white')
    expect(prompt).not.toContain('99')
    expect(prompt).not.toMatch(/\{\{[a-z0-9_]+\}\}/)
  })

  it('keeps one shared structure while four garments retain their own visual identity', () => {
    const sharedProfile = {
      profileKey: 'football-v-neck-short-sleeve',
      sourceSampleAssetId: 'sample-black-99',
      sourceGarmentId: 'garment-black-99',
      category: 'football_jersey',
      garmentStructure: { neckline: 'v_neck', sleeveType: 'short_sleeve', fit: 'regular' },
      viewRules: { supportsFront: true, supportsBack: true, frontBackMustNotSwap: true },
      designRules: { preserveText: true, preserveNumbers: true, preserveNames: true, preserveGraphics: true, preserveFontStyle: true, preserveElementPosition: true },
      structureRules: { preserveNeckline: true, preserveSleeves: true, preserveGarmentLength: true, preserveSilhouette: true },
      analysisModel: 'gpt-test',
      analysisVersion: 'batch-style-v1',
      coveredGarmentIds: ['garment-black-99', 'garment-red-88', 'garment-white-usa', 'garment-blue-23'],
    }
    const garmentFiles = ['black-99.jpg', 'red-88.jpg', 'white-USA.jpg', 'blue-23.jpg']

    const prompts = garmentFiles.map((garmentFileName) => buildBatchTryOnPrompt({
      garmentFileName,
      outputSize: '2048x2048',
      batchStyleProfile: sharedProfile,
    }))

    prompts.forEach((prompt, index) => {
      expect(prompt).toContain('v_neck')
      expect(prompt).toContain(garmentFiles[index])
      expect(prompt).toContain('CURRENT garment reference')
      expect(prompt).toContain('DO NOT inherit color, color combination, text, wording, name, number, logo, graphic')
    })
    expect(prompts[1]).not.toContain('black-99.jpg')
    expect(prompts[2]).not.toContain('black-99.jpg')
    expect(prompts[3]).not.toContain('black-99.jpg')
  })

  it('uses live reference-image inspection instead of inventing unavailable visual analysis fields', () => {
    const prompt = buildBatchTryOnPrompt({ garmentFileName: 'shirt.jpg', outputSize: '2048x2048' })

    expect(prompt).toContain('Determine this directly from Reference Image 1 (TEMPLATE IMAGE) at generation time')
    expect(prompt).toContain('Determine this directly from Reference Image 2 (CURRENT GARMENT REFERENCE) at generation time')
    expect(prompt).not.toMatch(/\{\{[a-z0-9_]+\}\}/)
  })

  it('keeps scene adaptation disabled by default and enables it for an explicit background preset', () => {
    const preserved = buildBatchTryOnPrompt({ garmentFileName: 'shirt.jpg', outputSize: '2048x2048' })
    const adapted = buildBatchTryOnPrompt({
      garmentFileName: 'shirt.jpg',
      outputSize: '2048x2048',
      presetSelection: {
        replacementMode: 'strict-garment-only',
        backgroundStyle: 'sports-field',
        backgroundAdaptationMode: 'subtle',
      },
    })

    expect(preserved).toContain('Scene adaptation is disabled.')
    expect(adapted).toContain('Scene adaptation is permitted only to the degree requested')
    expect(adapted).toContain('运动场背景')
  })
})
