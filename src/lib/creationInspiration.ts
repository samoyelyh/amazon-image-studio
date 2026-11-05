export interface InspirationItem {
  id: string
  title: string
  category: '电商' | '品牌' | '创意' | '人物'
  path: string
  prompt: string
}

export const inspirationAsset = (path: string) => `${import.meta.env.BASE_URL}${path}`

export const inspirationItems: InspirationItem[] = [
  { id: 'product-main', title: '简约商品主图', category: '电商', path: 'creative-assets/product-main.png', prompt: '参考简约商品主图的构图，为我的产品制作一张干净、专业的电商主图。' },
  { id: 'batch-tryon', title: '服装产品套图', category: '电商', path: 'creative-assets/batch-tryon.png', prompt: '参考服装产品展示方式，为我的服装设计一组统一的电商套图。' },
  { id: 'scene-creative', title: '自然创意场景', category: '创意', path: 'creative-assets/scene-creative.png', prompt: '参考自然花草和柔和色彩，为我的产品设计一个艺术感场景。' },
  { id: 'image-editing', title: '生活工作场景', category: '人物', path: 'creative-assets/image-editing.png', prompt: '参考真实生活工作场景，为我的图片创作自然、有故事感的画面。' },
  { id: 'abstract-creative', title: '抽象艺术海报', category: '创意', path: 'creative-assets/abstract-creative.png', prompt: '参考抽象艺术的色彩和形状，为我的产品设计一张创意海报。' },
  { id: 'variation-portrait', title: '人物时尚肖像', category: '人物', path: 'creative-assets/variation-portrait.png', prompt: '参考时尚人物肖像的光影和构图，创作一张品牌人物视觉图片。' },
  { id: 'aplus-visual', title: '自然笔触视觉', category: '品牌', path: 'creative-assets/aplus-visual.png', prompt: '参考自然笔触和柔和配色，为我的品牌设计一个视觉模块。' },
  { id: 'clean-tech', title: '简约科技风', category: '品牌', path: 'style-presets/clean-tech.png', prompt: '使用简约科技风，为我的产品创作清晰、专业的品牌图片。' },
  { id: 'natural-warm', title: '自然暖调风', category: '品牌', path: 'style-presets/natural-warm.png', prompt: '使用自然暖调与柔和日光，为我的产品创作舒适的品牌图片。' },
  { id: 'bright-retail', title: '明亮零售风', category: '电商', path: 'style-presets/bright-retail.png', prompt: '使用明亮零售风，为我的产品创作卖点清晰的营销图片。' },
  { id: 'premium-contrast', title: '高级对比风', category: '创意', path: 'style-presets/premium-contrast.png', prompt: '使用高级对比和杂志式光影，为我的产品创作一张视觉海报。' },
]
