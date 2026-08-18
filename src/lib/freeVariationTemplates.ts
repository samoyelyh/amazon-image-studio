export type FreeVariationTemplateCategory = 'preserve' | 'replace' | 'scene' | 'composition' | 'style'

export interface FreeVariationTemplate {
  id: string
  category: FreeVariationTemplateCategory
  label: string
  text: string
  variable?: {
    label: string
    suggestions: string[]
  }
}

export const freeVariationTemplateCategoryLabels: Record<FreeVariationTemplateCategory, string> = {
  preserve: '保持类',
  replace: '更换类',
  scene: '常用场景',
  composition: '常用构图',
  style: '常用风格',
}

export const freeVariationTemplates: FreeVariationTemplate[] = [
  { id: 'keep-character', category: 'preserve', label: '保持角色不变', text: '保持角色不变' },
  { id: 'keep-garment', category: 'preserve', label: '保持服装不变', text: '保持服装的颜色、图案、文字、号码和版型不变' },
  { id: 'keep-garment-graphics', category: 'preserve', label: '保持服装图案和号码不变', text: '保持服装图案、文字和号码完全不变' },
  { id: 'keep-pose', category: 'preserve', label: '保持姿势不变', text: '保持人物姿势不变' },
  { id: 'keep-face', category: 'preserve', label: '保持人物脸部不变', text: '保持人物身份、脸部和发型不变' },
  { id: 'keep-composition', category: 'preserve', label: '保持构图不变', text: '保持原图构图和主体位置不变' },
  { id: 'keep-angle', category: 'preserve', label: '保持镜头角度不变', text: '保持原有镜头角度不变' },
  { id: 'keep-variable', category: 'preserve', label: '保持指定内容不变', text: '保持{{value}}不变', variable: { label: '需要保持什么不变？', suggestions: ['人物身份和脸部', '服装核心细节', '背景', '姿势和构图'] } },

  { id: 'change-background', category: 'replace', label: '更换背景', text: '更换背景为{{value}}', variable: { label: '要更换成什么背景？', suggestions: ['橄榄球场', '比赛日看台', '训练场', '运动街头', '白底电商背景', '摄影棚'] } },
  { id: 'change-scene', category: 'replace', label: '更换场景', text: '更换场景为{{value}}', variable: { label: '要更换成什么场景？', suggestions: ['比赛日球场', '校园比赛', '更衣室', '运动街头', '生活方式场景'] } },
  { id: 'change-action', category: 'replace', label: '更换动作', text: '将人物动作更换为{{value}}', variable: { label: '要更换成什么动作？', suggestions: ['自然站立', '跑动', '庆祝胜利', '持球准备', '观赛互动'] } },
  { id: 'change-light', category: 'replace', label: '更换光线氛围', text: '将光线和整体氛围改成{{value}}', variable: { label: '希望使用什么光线或氛围？', suggestions: ['夜晚球场灯光', '比赛日热烈氛围', '柔和摄影棚光线', '清晨自然光'] } },
  { id: 'change-people-count', category: 'replace', label: '更换人物数量', text: '画面中的人物数量改为{{value}}', variable: { label: '需要几个人？', suggestions: ['单人', '两人', '三人小组', '多人观赛人群'] } },
  { id: 'change-camera-distance', category: 'replace', label: '更换镜头远近', text: '镜头景别改为{{value}}', variable: { label: '需要什么镜头景别？', suggestions: ['全身远景', '半身中景', '上半身近景', '产品细节特写'] } },
  { id: 'keep-person-change-background', category: 'replace', label: '人物不变，更换背景', text: '保持人物身份、脸部、姿势和服装不变，更换背景为{{value}}', variable: { label: '要更换成什么背景？', suggestions: ['橄榄球场', '比赛日看台', '训练场', '运动街头'] } },
  { id: 'keep-garment-change-scene', category: 'replace', label: '服装不变，更换场景', text: '保持服装的颜色、图案、文字、号码和版型不变，更换场景为{{value}}', variable: { label: '要更换成什么场景？', suggestions: ['比赛日球场', '训练场', '运动街头', '校园比赛'] } },
  { id: 'highlight-variable', category: 'replace', label: '突出局部细节', text: '突出{{value}}的细节', variable: { label: '需要突出什么细节？', suggestions: ['胸前号码', '领口和袖口', '面料纹理', '图案和文字', '缝线结构'] } },
  { id: 'change-mood-variable', category: 'replace', label: '更换成某种氛围', text: '整体氛围改成{{value}}', variable: { label: '希望使用什么氛围？', suggestions: ['比赛日氛围', '高级运动摄影氛围', '轻松生活方式氛围', '干净电商氛围'] } },
  { id: 'change-model-style', category: 'replace', label: '更换模特风格', text: '模特风格改成{{value}}', variable: { label: '需要什么模特风格？', suggestions: ['男性运动模特', '女性运动模特', '青少年运动风格', '街头潮流风格'] } },

  { id: 'scene-football-field', category: 'scene', label: '橄榄球场背景', text: '更换成橄榄球场背景' },
  { id: 'scene-game-day-stands', category: 'scene', label: '比赛日看台背景', text: '更换成比赛日观众席和看台背景' },
  { id: 'scene-training', category: 'scene', label: '训练场背景', text: '更换成专业训练场背景' },
  { id: 'scene-sport-street', category: 'scene', label: '运动街头背景', text: '更换成现代运动街头背景' },
  { id: 'scene-locker-room', category: 'scene', label: '更衣室背景', text: '更换成干净专业的运动更衣室背景' },
  { id: 'scene-white-commerce', category: 'scene', label: '白底电商背景', text: '更换成干净的纯白电商背景' },
  { id: 'scene-studio', category: 'scene', label: '摄影棚背景', text: '更换成专业电商摄影棚背景' },
  { id: 'scene-campus', category: 'scene', label: '校园比赛场景', text: '更换成校园比赛日场景' },
  { id: 'scene-night-stadium', category: 'scene', label: '夜晚球场灯光', text: '更换成夜晚球场灯光场景' },

  { id: 'composition-full-body', category: 'composition', label: '生成全身图', text: '生成完整全身构图，人物从头到脚完整可见' },
  { id: 'composition-half-body', category: 'composition', label: '生成半身图', text: '生成自然的半身构图' },
  { id: 'composition-upper-body', category: 'composition', label: '生成上半身图', text: '生成以上半身为重点的构图' },
  { id: 'composition-garment-detail', category: 'composition', label: '突出服装细节', text: '突出展示服装的设计和制作细节' },
  { id: 'composition-number', category: 'composition', label: '突出胸前号码', text: '突出展示胸前号码并保持号码准确清晰' },
  { id: 'composition-collar-cuff', category: 'composition', label: '突出领口和袖口', text: '突出展示领口和袖口的结构细节' },
  { id: 'composition-amazon', category: 'composition', label: '适合亚马逊Listing', text: '生成适合亚马逊Listing展示的清晰电商图片' },

  { id: 'style-real-commerce', category: 'style', label: '真实电商风格', text: '使用真实自然的电商摄影风格' },
  { id: 'style-premium-sport', category: 'style', label: '高级运动摄影', text: '使用高级感运动摄影风格' },
  { id: 'style-game-day', category: 'style', label: '比赛日氛围', text: '营造真实热烈的比赛日氛围' },
  { id: 'style-lifestyle', category: 'style', label: '生活方式穿搭', text: '使用自然的生活方式穿搭摄影风格' },
  { id: 'style-clean', category: 'style', label: '干净简洁', text: '使用干净简洁、主体清晰的视觉风格' },
]

export function renderFreeVariationTemplate(template: FreeVariationTemplate, value = '') {
  return template.text.replace('{{value}}', value.trim())
}
