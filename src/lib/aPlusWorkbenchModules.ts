import type { AmazonPromptDraft } from './amazonPrompt'
import { getAPlusModuleGenerationSize, type APlusContentType, type APlusModuleKind, type AmazonAPlusModuleSpec } from './listingPlanner'

export interface APlusWorkbenchModule {
  id: string
  name: string
  description: string
  badge: string
  moduleType: APlusModuleKind
  defaultSize: string
}

export type APlusMode = 'quick' | 'standard' | 'premium'

export interface APlusModeConfig {
  id: APlusMode
  name: string
  description: string
  contentType: APlusContentType
  defaultModules: string[]
  availableModules: string[]
  defaultResolution: '2k' | '4k'
  promptStrategy: string
}

export const A_PLUS_WORKBENCH_SIZE_OPTIONS = ['1464x600', '970x600', '970x300', '600x450'] as const

export const A_PLUS_WORKBENCH_MODULES: APlusWorkbenchModule[] = [
  { id: 'hero', name: '首屏主视觉', description: '建立商品第一视觉，突出核心卖点。', badge: 'Premium Hero', moduleType: 'hero-banner', defaultSize: '1464x600' },
  { id: 'key-benefits', name: '核心卖点图', description: '用清晰的信息层级呈现主要购买理由。', badge: 'Key Benefits', moduleType: 'feature-image', defaultSize: '970x600' },
  { id: 'usage-scene', name: '使用场景图', description: '展示商品在真实使用环境中的价值。', badge: 'Lifestyle', moduleType: 'single-image', defaultSize: '970x600' },
  { id: 'multi-angle', name: '多角度图', description: '从多个视角完整交代商品外观。', badge: 'Gallery', moduleType: 'feature-image', defaultSize: '970x600' },
  { id: 'atmosphere', name: '场景氛围图', description: '强化品牌调性与目标人群的使用想象。', badge: 'Atmosphere', moduleType: 'header-banner', defaultSize: '970x300' },
  { id: 'details', name: '商品细节图', description: '放大材质、结构和关键设计细节。', badge: 'Detail', moduleType: 'highlight-tile', defaultSize: '970x600' },
  { id: 'brand-story', name: '品牌故事图', description: '传达品牌理念、来源与产品价值。', badge: 'Brand Story', moduleType: 'brand-story', defaultSize: '970x600' },
  { id: 'size-guide', name: '尺寸/容量/尺码图', description: '直观说明尺寸、容量或尺码信息。', badge: 'Size Guide', moduleType: 'feature-image', defaultSize: '970x600' },
  { id: 'comparison', name: '效果对比图', description: '在真实信息范围内展示使用前后或差异。', badge: 'Comparison', moduleType: 'comparison-thumbnail', defaultSize: '970x600' },
  { id: 'specifications', name: '详细规格/参数表', description: '集中呈现已确认的规格与参数信息。', badge: 'Specifications', moduleType: 'single-image', defaultSize: '970x600' },
  { id: 'craftsmanship', name: '工艺制作图', description: '突出制作工艺、结构和品质细节。', badge: 'Craft', moduleType: 'feature-image', defaultSize: '970x600' },
  { id: 'accessories', name: '配件/赠品图', description: '准确展示包装内配件和赠品内容。', badge: 'In the Box', moduleType: 'single-image', defaultSize: '970x600' },
  { id: 'collection', name: '系列展示图', description: '展示同系列商品的统一视觉与选择。', badge: 'Collection', moduleType: 'feature-image', defaultSize: '970x600' },
  { id: 'ingredients', name: '商品成分图', description: '适用于成分、材料或组成结构说明。', badge: 'Ingredients', moduleType: 'highlight-tile', defaultSize: '970x600' },
  { id: 'support', name: '售后保障图', description: '清晰表达可验证的服务与保障信息。', badge: 'Support', moduleType: 'single-image', defaultSize: '970x300' },
  { id: 'usage-tips', name: '使用建议图', description: '通过步骤或建议降低理解和使用门槛。', badge: 'Usage Tips', moduleType: 'feature-image', defaultSize: '970x600' },
]

const QUICK_MODULES = ['key-benefits', 'usage-scene', 'details', 'size-guide', 'specifications', 'usage-tips']
const STANDARD_MODULES = ['key-benefits', 'usage-scene', 'multi-angle', 'atmosphere', 'details', 'size-guide', 'specifications', 'craftsmanship', 'accessories', 'ingredients', 'support', 'usage-tips']
const PREMIUM_MODULES = A_PLUS_WORKBENCH_MODULES.map((item) => item.id)

export const A_PLUS_MODE_CONFIG: Record<APlusMode, APlusModeConfig> = {
  quick: {
    id: 'quick',
    name: '快速 A+',
    description: '用四个核心模块快速建立精简 A+ 套图。',
    contentType: 'standard',
    defaultModules: ['key-benefits', 'usage-scene', 'details', 'size-guide'],
    availableModules: QUICK_MODULES,
    defaultResolution: '2k',
    promptStrategy: 'Prioritize speed, clarity, and one decisive message per module. Keep layouts simple and commercially useful.',
  },
  standard: {
    id: 'standard',
    name: '标准 A+',
    description: '适用于常规 Amazon A+ 的完整内容方案。',
    contentType: 'standard-large',
    defaultModules: ['key-benefits', 'usage-scene', 'multi-angle', 'details', 'size-guide', 'specifications'],
    availableModules: STANDARD_MODULES,
    defaultResolution: '2k',
    promptStrategy: 'Build a balanced standard Amazon A+ sequence with clear product evidence, benefits, usage, details, and specifications.',
  },
  premium: {
    id: 'premium',
    name: 'Premium A+',
    description: '面向品牌叙事和更丰富视觉层级的高级方案。',
    contentType: 'premium',
    defaultModules: ['hero', 'key-benefits', 'usage-scene', 'details', 'brand-story', 'comparison', 'collection'],
    availableModules: PREMIUM_MODULES,
    defaultResolution: '4k',
    promptStrategy: 'Create a premium brand-led A+ sequence with richer visual storytelling, stronger art direction, and purposeful premium modules without inventing brand facts.',
  },
}

export function getAPlusModeFromContentType(type: APlusContentType | undefined): APlusMode {
  if (type === 'premium') return 'premium'
  if (type === 'standard') return 'quick'
  return 'standard'
}

export function getAPlusModeModules(mode: APlusMode) {
  const available = new Set(A_PLUS_MODE_CONFIG[mode].availableModules)
  return A_PLUS_WORKBENCH_MODULES.filter((module) => available.has(module.id))
}

export function getDefaultAPlusModuleSizes(instanceIds: string[]) {
  return Object.fromEntries(instanceIds.map((id) => [id, getAPlusWorkbenchModule(id).defaultSize]))
}

export interface APlusProjectState {
  mode: APlusMode
  selectedModuleIds: string[]
  moduleSizes: Record<string, string>
  moduleExtraRequirements: Record<string, string>
  outputFormat: 'png' | 'jpeg' | 'webp'
  outputCompression: number | null
  hasManualComposition: boolean
}

export function createDefaultAPlusProjectState(mode: APlusMode = 'standard'): APlusProjectState {
  const selectedModuleIds = [...A_PLUS_MODE_CONFIG[mode].defaultModules]
  return {
    mode,
    selectedModuleIds,
    moduleSizes: getDefaultAPlusModuleSizes(selectedModuleIds),
    moduleExtraRequirements: {},
    outputFormat: 'jpeg',
    outputCompression: 90,
    hasManualComposition: false,
  }
}

export interface APlusModeTransition {
  nextState: APlusProjectState
  incompatibleModuleIds: string[]
}

export function resolveAPlusModeTransition(
  currentState: APlusProjectState,
  mode: APlusMode,
): APlusModeTransition {
  const nextConfig = A_PLUS_MODE_CONFIG[mode]
  const compatibleIds = currentState.selectedModuleIds.filter((id) => nextConfig.availableModules.includes(getAPlusModuleBaseId(id)))
  const incompatibleModuleIds = currentState.selectedModuleIds.filter((id) => !nextConfig.availableModules.includes(getAPlusModuleBaseId(id)))
  const shouldPreserveComposition = currentState.hasManualComposition && compatibleIds.length > 0
  const selectedModuleIds = shouldPreserveComposition
    ? compatibleIds
    : [...nextConfig.defaultModules]

  return {
    incompatibleModuleIds,
    nextState: {
      ...currentState,
      mode,
      selectedModuleIds,
      moduleSizes: {
        ...currentState.moduleSizes,
        ...Object.fromEntries(selectedModuleIds.map((id) => [
          id,
          currentState.moduleSizes[id] || getAPlusWorkbenchModule(id).defaultSize,
        ])),
      },
      hasManualComposition: shouldPreserveComposition,
    },
  }
}

export function getAPlusModuleBaseId(instanceId: string) {
  return instanceId.split('::copy::')[0]
}

export function getAPlusWorkbenchModule(instanceId: string) {
  const baseId = getAPlusModuleBaseId(instanceId)
  return A_PLUS_WORKBENCH_MODULES.find((item) => item.id === baseId) ?? A_PLUS_WORKBENCH_MODULES[0]
}

function parseSize(value: string, fallback: string) {
  const match = /^(\d+)x(\d+)$/.exec(value) ?? /^(\d+)x(\d+)$/.exec(fallback)
  return { width: Number(match?.[1] || 970), height: Number(match?.[2] || 600) }
}

export function buildAPlusWorkbenchSpecs(
  instanceIds: string[],
  sizes: Record<string, string>,
  type: APlusContentType,
  extraRequirements: Record<string, string> = {},
): AmazonAPlusModuleSpec[] {
  return instanceIds.slice(0, 16).map((instanceId, index) => {
    const module = getAPlusWorkbenchModule(instanceId)
    const size = parseSize(sizes[instanceId] || module.defaultSize, module.defaultSize)
    const extra = extraRequirements[instanceId]?.trim()
    return {
      contentType: type,
      slot: `A+W${String(index + 1).padStart(2, '0')}`,
      label: module.badge,
      displayLabel: module.name,
      moduleType: module.moduleType,
      uploadWidth: size.width,
      uploadHeight: size.height,
      objective: [module.description, extra ? `Additional requirement: ${extra}` : ''].filter(Boolean).join(' '),
    }
  })
}

export function buildAPlusProductBrief(draft: AmazonPromptDraft, listingText = '') {
  return [
    listingText.trim(),
    draft.productTitle.trim() ? `产品名称：${draft.productTitle.trim()}` : '',
    draft.sellingPoints.trim() ? `核心卖点：\n${draft.sellingPoints.trim()}` : '',
    draft.audience.trim() ? `目标人群：${draft.audience.trim()}` : '',
    draft.scene.trim() ? `使用场景：${draft.scene.trim()}` : '',
    draft.category.trim() ? `类目：${draft.category.trim()}` : '',
    draft.brand.trim() ? `品牌/型号：${draft.brand.trim()}` : '',
    draft.color.trim() ? `颜色：${draft.color.trim()}` : '',
    draft.material.trim() ? `材质/工艺：${draft.material.trim()}` : '',
    draft.packageIncludes.trim() ? `包装清单：${draft.packageIncludes.trim()}` : '',
    draft.forbidden.trim() ? `其他要求：${draft.forbidden.trim()}` : '',
  ].filter(Boolean).join('\n\n')
}

export interface APlusGenerationPayload {
  aPlusMode: APlusMode
  contentType: APlusContentType
  site: string
  language: string
  quality: '2k' | '4k'
  outputFormat: 'png' | 'jpeg' | 'webp'
  outputCompression: number | null
  modules: Array<{
    instanceId: string
    moduleId: string
    type: APlusModuleKind
    order: number
    width: number
    height: number
    aspectRatio: string
    generationSize: string
    objective: string
  }>
}

export function buildAPlusGenerationPayload(options: {
  mode: APlusMode
  site: string
  language: string
  quality: '2k' | '4k'
  outputFormat: 'png' | 'jpeg' | 'webp'
  outputCompression: number | null
  instanceIds: string[]
  specs: AmazonAPlusModuleSpec[]
}): APlusGenerationPayload {
  const config = A_PLUS_MODE_CONFIG[options.mode]
  return {
    aPlusMode: options.mode,
    contentType: config.contentType,
    site: options.site,
    language: options.language,
    quality: options.quality,
    outputFormat: options.outputFormat,
    outputCompression: options.outputFormat === 'png' ? null : options.outputCompression,
    modules: options.instanceIds.map((instanceId, index) => {
      const spec = options.specs[index]
      const width = spec?.uploadWidth || 970
      const height = spec?.uploadHeight || 600
      return {
        instanceId,
        moduleId: getAPlusModuleBaseId(instanceId),
        type: spec?.moduleType || getAPlusWorkbenchModule(instanceId).moduleType,
        order: index + 1,
        width,
        height,
        aspectRatio: `${width}:${height}`,
        generationSize: getAPlusModuleGenerationSize({ uploadWidth: width, uploadHeight: height }, options.quality === '4k' ? '4K' : '2K'),
        objective: spec?.objective || '',
      }
    }),
  }
}
