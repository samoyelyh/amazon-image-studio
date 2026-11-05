import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import BatchTryOnStructuredAnalysis from '../components/BatchTryOnStructuredAnalysis'
import { isPerGarmentLuna, type StructuredLunaAnalysis } from './batchTryOnStructured'

describe('structured Luna integration', () => {
  it('keeps both per-image strategies on the independent analysis pipeline', () => {
    expect(isPerGarmentLuna('luna_structured')).toBe(true)
    expect(isPerGarmentLuna('luna_per_image')).toBe(true)
    expect(isPerGarmentLuna('preset')).toBe(false)
    expect(isPerGarmentLuna('ai_optimize')).toBe(false)
  })
  it('does not render an empty fake analysis panel', () => {
    expect(renderToStaticMarkup(<BatchTryOnStructuredAnalysis />)).toBe('')
  })
  it('separates analysis facts and risk from the editable final prompt', () => {
    const analysis = {
      template_analysis: { subject: '固定模特', pose: '站姿', view_direction: '正面', original_clothing: '棒球衫', lighting: '柔光', occlusions: [], protected_elements: ['标题'] },
      jobs: [{ garment_id: 'stable-06', garment_type: '球衣', view_direction: '正面', garment_structure: '黑色V领', colors: ['酒红色'], graphics: [], texts_and_numbers: ['TEAM', '06'], replacement_region: '上装', structural_changes: ['清除门襟'], preservation_rules: ['保留身份'], removal_rules: ['移除旧图案'], risk_level: 'HIGH', needs_manual_review: true, uncertainties: ['姓名不可辨认'], generation_prompt: 'FINAL_PROMPT_IS_SEPARATE' }],
    } as unknown as StructuredLunaAnalysis
    const markup = renderToStaticMarkup(<BatchTryOnStructuredAnalysis analysis={analysis} />)
    expect(markup).toContain('高风险')
    expect(markup).toContain('请人工确认')
    expect(markup).toContain('姓名不可辨认')
    expect(markup).toContain('TEAM')
    expect(markup).toContain('06')
    expect(markup).not.toContain('FINAL_PROMPT_IS_SEPARATE')
  })
})
