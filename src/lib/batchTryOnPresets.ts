import type { BatchTryOnPresetSelection } from '../types'

export type BatchTryOnPresetCategory =
  | 'target_audience'
  | 'replacement_mode'
  | 'background_style'
  | 'background_adaptation_mode'

export interface BatchTryOnPromptPreset {
  id: string
  category: BatchTryOnPresetCategory
  code: string
  name: string
  description: string
  prompt: string
  source: 'system' | 'organization'
}

export const DEFAULT_BATCH_TRY_ON_PRESET_SELECTION: BatchTryOnPresetSelection = {
  replacementMode: 'strict-garment-only',
  backgroundStyle: 'keep-original',
  backgroundAdaptationMode: 'keep-unchanged',
}

export const BATCH_TRY_ON_PROMPT_PRESETS: readonly BatchTryOnPromptPreset[] = [
  {
    id: 'target-audience-western-athletic-men',
    category: 'target_audience',
    code: 'western-athletic-men',
    name: '欧美运动男性',
    description: '强化欧美运动男性气质与商业运动视觉。',
    prompt: 'Present a confident Western athletic male aesthetic. Keep the existing model identity unchanged; use this preset only to guide styling, commercial mood and scene aesthetics.',
    source: 'system',
  },
  {
    id: 'target-audience-western-athletic-women',
    category: 'target_audience',
    code: 'western-athletic-women',
    name: '欧美运动女性',
    description: '强化欧美运动女性气质与活力视觉。',
    prompt: 'Present a confident Western athletic female aesthetic. Keep the existing model identity unchanged; use this preset only to guide styling, commercial mood and scene aesthetics.',
    source: 'system',
  },
  {
    id: 'target-audience-youth-sports',
    category: 'target_audience',
    code: 'youth-sports',
    name: '青少年运动风',
    description: '明快、年轻且适合运动服饰电商展示。',
    prompt: 'Use a youthful sports-inspired commercial mood with energetic, age-appropriate styling. Do not change the existing model identity, age or anatomy.',
    source: 'system',
  },
  {
    id: 'target-audience-campus-energy',
    category: 'target_audience',
    code: 'campus-energy',
    name: '校园活力风',
    description: '校园、社团与年轻活力审美。',
    prompt: 'Use a clean campus-energy aesthetic suitable for school, club and youth lifestyle apparel while preserving the original model and composition.',
    source: 'system',
  },
  {
    id: 'target-audience-american-casual',
    category: 'target_audience',
    code: 'american-casual',
    name: '美式休闲风',
    description: '自然、松弛的美式休闲商业氛围。',
    prompt: 'Use an approachable American casual lifestyle aesthetic with natural commercial styling while preserving the original model identity and garment details.',
    source: 'system',
  },
  {
    id: 'target-audience-sports-fan',
    category: 'target_audience',
    code: 'sports-fan',
    name: '球迷观赛风',
    description: '球迷、球队与观赛氛围倾向。',
    prompt: 'Use a sports-fan and game-day commercial mood appropriate for jerseys and supporter apparel without adding unreferenced team marks, text or logos.',
    source: 'system',
  },
  {
    id: 'target-audience-streetwear',
    category: 'target_audience',
    code: 'streetwear',
    name: '街头潮流风',
    description: '现代街头与年轻潮流审美。',
    prompt: 'Use a modern streetwear commercial aesthetic with confident styling while keeping the existing model identity and all source garment graphics unchanged.',
    source: 'system',
  },
  {
    id: 'replacement-strict-garment-only',
    category: 'replacement_mode',
    code: 'strict-garment-only',
    name: '严格只换衣服，其余不变',
    description: '最高强度保留模特、姿势、构图、光线和背景。',
    prompt: `Only replace the garment with the uploaded clothing item.
Keep the original model identity, face, hairstyle, pose, body proportions, camera angle, background, framing and lighting unchanged.
Do not redesign the outfit.
Preserve all garment details from the uploaded clothing image, including colors, text, graphics, numbers, stripes, neckline, sleeves, hem, silhouette and fabric appearance.`,
    source: 'system',
  },
  {
    id: 'replacement-preserve-face-pose-background',
    category: 'replacement_mode',
    code: 'preserve-face-pose-background',
    name: '保持模特脸部、姿势、背景不变，只替换服装',
    description: '明确锁定人物身份、姿势和背景。',
    prompt: 'Replace only the clothing. Keep the model face, identity, hairstyle, expression, pose, body proportions, camera, framing, lighting and background exactly unchanged.',
    source: 'system',
  },
  {
    id: 'replacement-natural-fit',
    category: 'replacement_mode',
    code: 'natural-fit',
    name: '保持模特和场景不变，服装自然贴合身体',
    description: '允许必要褶皱和遮挡变化，使服装自然穿着。',
    prompt: 'Keep the model and scene unchanged. Fit the referenced garment naturally to the existing body using only physically necessary drape, folds, perspective, occlusion and shading.',
    source: 'system',
  },
  {
    id: 'replacement-top-only',
    category: 'replacement_mode',
    code: 'top-only',
    name: '只换上衣，不改变裤子和配饰',
    description: '编辑范围限制在上衣区域。',
    prompt: 'Replace only the upper-body garment. Keep pants, skirt, footwear, jewelry, accessories and every other clothing item unchanged.',
    source: 'system',
  },
  {
    id: 'replacement-lock-composition-light-background',
    category: 'replacement_mode',
    code: 'lock-composition-light-background',
    name: '只换衣服，禁止改变构图、光线和背景',
    description: '严格锁定构图、光线和背景。',
    prompt: 'Replace only the garment. Do not change composition, crop, camera angle, perspective, lighting, shadows, depth of field or background.',
    source: 'system',
  },
  {
    id: 'background-keep-original',
    category: 'background_style',
    code: 'keep-original',
    name: '保持原背景不变',
    description: '禁止修改、替换或扩展原背景。',
    prompt: 'Keep the original background exactly unchanged. Do not replace, redesign, restyle, expand or remove any background element.',
    source: 'system',
  },
  {
    id: 'background-clean-ecommerce',
    category: 'background_style',
    code: 'clean-ecommerce',
    name: '简洁电商背景',
    description: '简洁、商业化且突出服装主体。',
    prompt: 'Use a clean, uncluttered, commercially attractive e-commerce background that keeps attention on the garment and contains no text or watermark.',
    source: 'system',
  },
  {
    id: 'background-sports-field',
    category: 'background_style',
    code: 'sports-field',
    name: '运动场背景',
    description: '适合球衣和运动服饰的运动场景。',
    prompt: 'Use a realistic sports-field or athletic venue background suitable for commercial apparel presentation, without adding unreferenced team branding.',
    source: 'system',
  },
  {
    id: 'background-stadium-stands',
    category: 'background_style',
    code: 'stadium-stands',
    name: '观赛看台背景',
    description: '观赛、看台与比赛日氛围。',
    prompt: 'Use a realistic stadium-stands or game-day spectator environment suitable for supporter apparel, with no invented logos, team names or text.',
    source: 'system',
  },
  {
    id: 'background-street-casual',
    category: 'background_style',
    code: 'street-casual',
    name: '街头休闲背景',
    description: '现代街区或休闲生活方式环境。',
    prompt: 'Use a modern street-casual lifestyle background with commercially controlled visual clutter and natural depth.',
    source: 'system',
  },
  {
    id: 'background-campus',
    category: 'background_style',
    code: 'campus',
    name: '校园场景背景',
    description: '适合校园、社团和青少年服饰。',
    prompt: 'Use a clean, realistic campus-inspired environment appropriate for school and youth apparel while avoiding readable signage or invented branding.',
    source: 'system',
  },
  {
    id: 'background-festive',
    category: 'background_style',
    code: 'festive',
    name: '节日氛围背景',
    description: '根据服装主题营造适度节日氛围。',
    prompt: 'Use a tasteful festive atmosphere that matches the garment theme while remaining commercially usable and avoiding text, watermarks or distracting decorations.',
    source: 'system',
  },
  {
    id: 'background-auto-garment-style',
    category: 'background_style',
    code: 'auto-garment-style',
    name: '自动匹配服装风格背景',
    description: '按运动、休闲或节日服装类型自动选择商业背景。',
    prompt: `Adapt the background style to match the uploaded garment's style category, while keeping the scene commercially attractive and suitable for e-commerce use.
For sports jerseys, prefer sports-related or stadium-inspired environments.
For casual garments, prefer clean lifestyle or simple fashion backgrounds.
For festive garments, prefer an appropriate festive atmosphere.`,
    source: 'system',
  },
  {
    id: 'background-adaptation-keep-unchanged',
    category: 'background_adaptation_mode',
    code: 'keep-unchanged',
    name: '背景保持不变',
    description: '不根据服装调整背景。',
    prompt: 'Background adaptation is disabled. Preserve the original background exactly.',
    source: 'system',
  },
  {
    id: 'background-adaptation-subtle',
    category: 'background_adaptation_mode',
    code: 'subtle',
    name: '背景轻微适配服装风格',
    description: '仅轻微调整氛围，不破坏原有构图。',
    prompt: 'Adapt the background only subtly to the garment style. Preserve the scene structure, camera, framing and primary background elements.',
    source: 'system',
  },
  {
    id: 'background-adaptation-significant',
    category: 'background_adaptation_mode',
    code: 'significant',
    name: '背景明显按服装风格变化',
    description: '允许明显重塑背景风格，但保持电商可用性。',
    prompt: 'Change the background style clearly to match the garment category while preserving the model, pose, camera perspective and commercially useful composition.',
    source: 'system',
  },
  {
    id: 'background-adaptation-automatic',
    category: 'background_adaptation_mode',
    code: 'automatic',
    name: '完全自动判断背景风格',
    description: '由服装类别自动决定合适背景。',
    prompt: 'Automatically infer the most suitable commercial background style from the garment category. Use sports settings for jerseys, clean lifestyle settings for casual apparel and appropriate festive settings for themed garments.',
    source: 'system',
  },
]

const CATEGORY_FIELD: Record<BatchTryOnPresetCategory, keyof BatchTryOnPresetSelection> = {
  target_audience: 'targetAudience',
  replacement_mode: 'replacementMode',
  background_style: 'backgroundStyle',
  background_adaptation_mode: 'backgroundAdaptationMode',
}

export function presetsForCategory(category: BatchTryOnPresetCategory) {
  return BATCH_TRY_ON_PROMPT_PRESETS.filter((preset) => preset.category === category)
}

export function findBatchTryOnPreset(category: BatchTryOnPresetCategory, code?: string) {
  return code
    ? BATCH_TRY_ON_PROMPT_PRESETS.find((preset) => preset.category === category && preset.code === code)
    : undefined
}

export function resolveBatchTryOnPresetSelection(selection: BatchTryOnPresetSelection): BatchTryOnPresetSelection {
  if (selection.backgroundStyle === 'keep-original') {
    return { ...selection, backgroundAdaptationMode: 'keep-unchanged' }
  }
  return { ...selection }
}

export function selectedBatchTryOnPresets(selection: BatchTryOnPresetSelection) {
  const resolved = resolveBatchTryOnPresetSelection(selection)
  return (Object.entries(CATEGORY_FIELD) as Array<[BatchTryOnPresetCategory, keyof BatchTryOnPresetSelection]>)
    .flatMap(([category, field]) => {
      const preset = findBatchTryOnPreset(category, resolved[field])
      return preset ? [preset] : []
    })
}

export function summarizeBatchTryOnPresets(selection: BatchTryOnPresetSelection) {
  return selectedBatchTryOnPresets(selection).map((preset) => preset.name).join(' · ')
}

export function buildBatchTryOnPresetPrompt(selection: BatchTryOnPresetSelection) {
  const presets = selectedBatchTryOnPresets(selection)
  if (!presets.length) return ''
  return `SELECTED PROMPT PRESETS:\n${presets.map((preset) => `* ${preset.name}: ${preset.prompt}`).join('\n')}`
}
