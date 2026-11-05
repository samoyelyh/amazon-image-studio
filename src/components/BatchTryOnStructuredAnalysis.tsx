import type { StructuredLunaAnalysis } from '../lib/batchTryOnStructured'

export default function BatchTryOnStructuredAnalysis({ analysis }: { analysis?: StructuredLunaAnalysis | null }) {
  const garment = analysis?.jobs?.[0]
  if (!analysis || !garment) return null
  const template = analysis.template_analysis
  const rows: Array<[string, string | string[]]> = [
    ['目标人物 / 商品', template.subject], ['姿势与朝向', `${template.pose}；${template.view_direction}`],
    ['原始服装', template.original_clothing], ['光照', template.lighting], ['遮挡', template.occlusions],
    ['模板保护', template.protected_elements], ['服装类型与视角', `${garment.garment_type}；${garment.view_direction}`],
    ['服装结构', garment.garment_structure], ['颜色', garment.colors], ['图案', garment.graphics],
    ['原文文字 / 号码', garment.texts_and_numbers], ['替换区域', garment.replacement_region],
    ['结构调整', garment.structural_changes], ['保留规则', garment.preservation_rules], ['旧设计清除', garment.removal_rules],
    ['不确定信息', garment.uncertainties],
  ]
  return <details open={garment.needs_manual_review} className="my-3 rounded-xl border border-blue-200 bg-blue-50/40 p-3 text-xs dark:border-blue-500/20 dark:bg-blue-500/5">
    <summary className="cursor-pointer font-semibold">Luna 结构化分析 V1.1 · {garment.risk_level === 'HIGH' ? '高风险' : garment.risk_level === 'MEDIUM' ? '中等风险' : '低风险'}{garment.needs_manual_review ? ' · 请人工确认' : ''}</summary>
    <dl className="mt-3 max-h-80 space-y-2 overflow-y-auto leading-5">{rows.map(([label, value]) => <div key={label}>
      <dt className="font-medium text-gray-500">{label}</dt><dd className="whitespace-pre-wrap break-words">{Array.isArray(value) ? value.join('；') || '无' : value}</dd>
    </div>)}</dl>
  </details>
}
