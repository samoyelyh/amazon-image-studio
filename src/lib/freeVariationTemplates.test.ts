import { describe, expect, it } from 'vitest'
import { freeVariationTemplates, renderFreeVariationTemplate } from './freeVariationTemplates'

describe('free variation prompt templates', () => {
  it('contains the required fixed template categories and high-frequency actions', () => {
    expect(new Set(freeVariationTemplates.map((item) => item.category))).toEqual(
      new Set(['preserve', 'replace', 'scene', 'composition', 'style']),
    )
    expect(freeVariationTemplates.some((item) => item.text === '保持角色不变')).toBe(true)
    expect(freeVariationTemplates.some((item) => item.text.includes('亚马逊Listing'))).toBe(true)
  })

  it('renders a variable template using the user value', () => {
    const template = freeVariationTemplates.find((item) => item.id === 'change-background')
    expect(template).toBeDefined()
    expect(renderFreeVariationTemplate(template!, '橄榄球场')).toBe('更换背景为橄榄球场')
  })
})
