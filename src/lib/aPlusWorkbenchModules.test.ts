import { describe, expect, it } from 'vitest'
import { DEFAULT_AMAZON_PROMPT_DRAFT } from './amazonPrompt'
import {
  A_PLUS_WORKBENCH_MODULES,
  A_PLUS_MODE_CONFIG,
  buildAPlusGenerationPayload,
  buildAPlusProductBrief,
  buildAPlusWorkbenchSpecs,
  createDefaultAPlusProjectState,
  resolveAPlusModeTransition,
} from './aPlusWorkbenchModules'

describe('A+ workbench module library', () => {
  it('provides all sixteen requested modules', () => {
    expect(A_PLUS_WORKBENCH_MODULES).toHaveLength(16)
    expect(A_PLUS_WORKBENCH_MODULES.map((item) => item.name)).toContain('首屏主视觉')
    expect(A_PLUS_WORKBENCH_MODULES.map((item) => item.name)).toContain('使用建议图')
  })

  it('converts ordered UI modules into the existing module spec structure', () => {
    const specs = buildAPlusWorkbenchSpecs(
      ['hero', 'details', 'hero::copy::1'],
      { hero: '1464x600', details: '970x300', 'hero::copy::1': '600x450' },
      'premium',
    )
    expect(specs.map((item) => item.slot)).toEqual(['A+W01', 'A+W02', 'A+W03'])
    expect(specs[0]).toMatchObject({ displayLabel: '首屏主视觉', uploadWidth: 1464, uploadHeight: 600 })
    expect(specs[2]).toMatchObject({ displayLabel: '首屏主视觉', uploadWidth: 600, uploadHeight: 450 })
  })

  it('builds an AI-ready product brief without inventing a module recommendation', () => {
    const draft = { ...DEFAULT_AMAZON_PROMPT_DRAFT, productTitle: '测试商品', sellingPoints: '卖点一', brand: 'Brand' }
    expect(buildAPlusProductBrief(draft)).toContain('产品名称：测试商品')
    expect(buildAPlusProductBrief(draft)).toContain('品牌/型号：Brand')
  })

  it('uses one mode config for available and default modules', () => {
    expect(A_PLUS_MODE_CONFIG.quick.defaultModules).toHaveLength(4)
    expect(A_PLUS_MODE_CONFIG.standard.availableModules).not.toContain('hero')
    expect(A_PLUS_MODE_CONFIG.premium.availableModules).toContain('hero')
  })

  it('warns about incompatible modules and preserves compatible manual composition', () => {
    const current = {
      ...createDefaultAPlusProjectState('premium'),
      selectedModuleIds: ['hero', 'details', 'brand-story'],
      hasManualComposition: true,
    }
    const transition = resolveAPlusModeTransition(current, 'standard')
    expect(transition.incompatibleModuleIds).toEqual(['hero', 'brand-story'])
    expect(transition.nextState.selectedModuleIds).toEqual(['details'])
    expect(transition.nextState.mode).toBe('standard')
  })

  it('loads target defaults when the current mode still uses its defaults', () => {
    const transition = resolveAPlusModeTransition(createDefaultAPlusProjectState('standard'), 'premium')
    expect(transition.incompatibleModuleIds).toEqual([])
    expect(transition.nextState.selectedModuleIds).toEqual(A_PLUS_MODE_CONFIG.premium.defaultModules)
    expect(transition.nextState.hasManualComposition).toBe(false)
  })

  it('builds an ordered generation payload from the selected UI state', () => {
    const specs = buildAPlusWorkbenchSpecs(
      ['details', 'hero'],
      { details: '600x450', hero: '1464x600' },
      'premium',
    )
    const payload = buildAPlusGenerationPayload({
      mode: 'premium',
      site: 'US',
      language: 'en-US',
      quality: '4k',
      outputFormat: 'jpeg',
      outputCompression: 82,
      instanceIds: ['details', 'hero'],
      specs,
    })
    expect(payload).toMatchObject({ aPlusMode: 'premium', contentType: 'premium', quality: '4k', outputFormat: 'jpeg', outputCompression: 82 })
    expect(payload.modules.map((item) => [item.moduleId, item.width, item.height, item.order])).toEqual([
      ['details', 600, 450, 1],
      ['hero', 1464, 600, 2],
    ])
    expect(payload.modules[0].generationSize).toBe('4096x3072')
    expect(payload.modules[0].objective).toContain('关键设计细节')
  })
})
