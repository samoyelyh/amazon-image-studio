import { describe, expect, it } from 'vitest'
import { buildBatchTryOnPrompt } from './batchTryOnPrompt'
import {
  buildBatchTryOnPresetPrompt,
  presetsForCategory,
  resolveBatchTryOnPresetSelection,
  summarizeBatchTryOnPresets,
} from './batchTryOnPresets'

describe('batch try-on prompt presets', () => {
  it('contains all required preset categories', () => {
    expect(presetsForCategory('target_audience')).toHaveLength(7)
    expect(presetsForCategory('replacement_mode')).toHaveLength(5)
    expect(presetsForCategory('background_style')).toHaveLength(8)
    expect(presetsForCategory('background_adaptation_mode')).toHaveLength(4)
  })

  it('resolves keep-original background conflicts with highest priority', () => {
    const resolved = resolveBatchTryOnPresetSelection({
      backgroundStyle: 'keep-original',
      backgroundAdaptationMode: 'significant',
    })

    expect(resolved.backgroundAdaptationMode).toBe('keep-unchanged')
  })

  it('builds presets before the user custom prompt', () => {
    const prompt = buildBatchTryOnPrompt({
      garmentFileName: '06-blue-jersey.png',
      templateName: '欧美男模-01',
      outputSize: '2048x2048',
      presetSelection: {
        targetAudience: 'western-athletic-men',
        replacementMode: 'strict-garment-only',
        backgroundStyle: 'auto-garment-style',
        backgroundAdaptationMode: 'subtle',
      },
      extraRequirements: 'CUSTOM REQUIREMENT MARKER',
    })

    expect(buildBatchTryOnPresetPrompt({
      targetAudience: 'western-athletic-men',
      replacementMode: 'strict-garment-only',
      backgroundStyle: 'auto-garment-style',
      backgroundAdaptationMode: 'subtle',
    })).toContain('Only replace the garment')
    expect(summarizeBatchTryOnPresets({
      targetAudience: 'western-athletic-men',
      replacementMode: 'strict-garment-only',
      backgroundStyle: 'auto-garment-style',
      backgroundAdaptationMode: 'subtle',
    })).toContain('欧美运动男性')
    expect(prompt).toContain('Preserve the exact garment design')
    expect(prompt.indexOf('SELECTED PROMPT PRESETS')).toBeLessThan(prompt.indexOf('CUSTOM REQUIREMENT MARKER'))
  })
})
