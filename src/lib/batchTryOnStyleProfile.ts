import type { BatchGarmentStyleProfile, BatchTryOnGarment } from '../types'
import type { BatchTryOnWorkflowGarmentProfile } from './batchTryOnWorkflowApi'
import type { ServerJob } from './jobsApi'

export type { BatchGarmentStyleProfile } from '../types'

export interface StructureConsistencyDecision {
  candidateIndex: number
  sameStructureFamily: boolean
  reason?: string
}

export const BATCH_STYLE_ANALYSIS_VERSION = 'batch-style-v1'

export const BATCH_STYLE_ANALYSIS_SYSTEM_PROMPT = `You analyze apparel structure for batch virtual try-on.
Return one valid JSON object only. Do not include markdown.

The reusable batch_style_profile may contain structural properties and preservation RULES only.
It must never contain a fixed color, color scheme, visible wording, number, name, logo, team name, or specific graphic content.
Those variable visual facts always come from each CURRENT garment reference image.`

export const BATCH_STYLE_ANALYSIS_USER_PROMPT = `Reference Image 1 is the first garment sample for this batch.

Perform one complete STRUCTURAL analysis and return:
{
  "batch_style_profile": {
    "category": "short machine-readable category",
    "garment_structure": {
      "neckline": "structural description only",
      "sleeve_type": "structural description only",
      "fit": "structural description only",
      "closure": "structural description only",
      "hem_type": "structural description only"
    },
    "view_rules": {
      "supports_front": true,
      "supports_back": true,
      "front_back_must_not_swap": true
    },
    "design_rules": {
      "preserve_text": true,
      "preserve_numbers": true,
      "preserve_names": true,
      "preserve_graphics": true,
      "preserve_font_style": true,
      "preserve_element_position": true
    },
    "structure_rules": {
      "preserve_neckline": true,
      "preserve_sleeves": true,
      "preserve_garment_length": true,
      "preserve_silhouette": true
    }
  },
  "first_sample_observation": {
    "variable_visual_details": "Optional debug-only observation. It never becomes a batch constraint."
  }
}

Do not place colors, wording, numbers, names, logos, team names, or specific graphic descriptions inside batch_style_profile.`

export function buildStructureConsistencyPrompt(candidateCount: number): string {
  return `Reference Image 1 is the source sample for an existing structural profile.
Reference Images 2 through ${candidateCount + 1} are candidate garments.

Perform only a lightweight STRUCTURE consistency check. Ignore color, text, numbers, names, logos and graphic content.
For each candidate, decide whether its garment category, neckline, sleeve construction, closure, length and silhouette belong to the same structure family as Reference Image 1.

Return exactly:
{
  "decisions": [
    {"candidate_index": 1, "same_structure_family": true, "reason": ""}
  ]
}

candidate_index starts at 1 for Reference Image 2. Return ${candidateCount} decisions in input order.`
}

export function parseProfileFromJob(job: ServerJob, options: {
  profileKey: string
  sourceSampleAssetId: string
  sourceGarmentId: string
  analysisModel: string
}): BatchGarmentStyleProfile {
  const payload = parseJobJson(job)
  const raw = asRecord(payload.batch_style_profile)
  return sanitizeBatchGarmentStyleProfile({
    profileKey: options.profileKey,
    sourceSampleAssetId: options.sourceSampleAssetId,
    sourceGarmentId: options.sourceGarmentId,
    category: stringValue(raw.category, 'apparel'),
    garmentStructure: asRecord(raw.garment_structure),
    viewRules: asRecord(raw.view_rules),
    designRules: asRecord(raw.design_rules),
    structureRules: asRecord(raw.structure_rules),
    firstSampleObservation: asRecord(payload.first_sample_observation),
    analysisModel: options.analysisModel,
    analysisVersion: BATCH_STYLE_ANALYSIS_VERSION,
    coveredGarmentIds: [options.sourceGarmentId],
  })
}

export function parseConsistencyDecisions(job: ServerJob, expectedCount: number): StructureConsistencyDecision[] {
  const payload = parseJobJson(job)
  const decisions = Array.isArray(payload.decisions) ? payload.decisions : []
  const byIndex = new Map<number, StructureConsistencyDecision>()
  for (const value of decisions) {
    const record = asRecord(value)
    const candidateIndex = Number(record.candidate_index)
    if (!Number.isInteger(candidateIndex) || candidateIndex < 1 || candidateIndex > expectedCount) continue
    byIndex.set(candidateIndex, {
      candidateIndex,
      sameStructureFamily: record.same_structure_family === true,
      reason: typeof record.reason === 'string' ? record.reason.trim() : undefined,
    })
  }
  return Array.from({ length: expectedCount }, (_, index) => byIndex.get(index + 1) ?? ({
    candidateIndex: index + 1,
    sameStructureFamily: false,
    reason: 'The structure check did not return a valid decision.',
  }))
}

export function sanitizeBatchGarmentStyleProfile(value: any): BatchGarmentStyleProfile {
  const structure = asRecord(value.garmentStructure)
  const view = asRecord(value.viewRules)
  const design = asRecord(value.designRules)
  const rules = asRecord(value.structureRules)
  const coveredGarmentIds: string[] = Array.isArray(value.coveredGarmentIds)
    ? value.coveredGarmentIds.filter((item: unknown): item is string => typeof item === 'string' && Boolean(item))
    : []
  return {
    profileKey: cleanIdentifier(value.profileKey, 'profile'),
    sourceSampleAssetId: value.sourceSampleAssetId,
    sourceGarmentId: value.sourceGarmentId,
    category: cleanStructureValue(value.category, 'apparel'),
    garmentStructure: {
      neckline: optionalStructureValue(structure.neckline),
      sleeveType: optionalStructureValue(structure.sleeveType ?? structure.sleeve_type),
      fit: optionalStructureValue(structure.fit),
      closure: optionalStructureValue(structure.closure),
      hemType: optionalStructureValue(structure.hemType ?? structure.hem_type),
    },
    viewRules: {
      supportsFront: booleanValue(view.supportsFront ?? view.supports_front, true),
      supportsBack: booleanValue(view.supportsBack ?? view.supports_back, true),
      frontBackMustNotSwap: booleanValue(view.frontBackMustNotSwap ?? view.front_back_must_not_swap, true),
    },
    designRules: {
      preserveText: booleanValue(design.preserveText ?? design.preserve_text, true),
      preserveNumbers: booleanValue(design.preserveNumbers ?? design.preserve_numbers, true),
      preserveNames: booleanValue(design.preserveNames ?? design.preserve_names, true),
      preserveGraphics: booleanValue(design.preserveGraphics ?? design.preserve_graphics, true),
      preserveFontStyle: booleanValue(design.preserveFontStyle ?? design.preserve_font_style, true),
      preserveElementPosition: booleanValue(design.preserveElementPosition ?? design.preserve_element_position, true),
    },
    structureRules: {
      preserveNeckline: booleanValue(rules.preserveNeckline ?? rules.preserve_neckline, true),
      preserveSleeves: booleanValue(rules.preserveSleeves ?? rules.preserve_sleeves, true),
      preserveGarmentLength: booleanValue(rules.preserveGarmentLength ?? rules.preserve_garment_length, true),
      preserveSilhouette: booleanValue(rules.preserveSilhouette ?? rules.preserve_silhouette, true),
    },
    firstSampleObservation: asRecord(value.firstSampleObservation),
    analysisModel: String(value.analysisModel || '').slice(0, 120),
    analysisVersion: String(value.analysisVersion || BATCH_STYLE_ANALYSIS_VERSION).slice(0, 80),
    coveredGarmentIds: [...new Set<string>(coveredGarmentIds)],
  }
}

export function restoreWorkflowStyleProfile(
  profile: BatchTryOnWorkflowGarmentProfile,
  garments: BatchTryOnGarment[],
): BatchGarmentStyleProfile {
  const source = garments.find((garment) => garment.serverAssetId === profile.source_sample_asset_id)
  return sanitizeBatchGarmentStyleProfile({
    profileKey: profile.profile_key,
    sourceSampleAssetId: profile.source_sample_asset_id,
    sourceGarmentId: source?.id || profile.source_sample_asset_id,
    category: profile.category,
    garmentStructure: profile.garment_structure,
    viewRules: profile.view_rules,
    designRules: profile.design_rules,
    structureRules: profile.structure_rules,
    firstSampleObservation: profile.observation || {},
    analysisModel: profile.analysis_model,
    analysisVersion: profile.analysis_version,
    coveredGarmentIds: garments.map((garment) => garment.id),
  })
}

export function batchStyleProfileSnapshot(profile: BatchGarmentStyleProfile) {
  const safe = sanitizeBatchGarmentStyleProfile(profile)
  return {
    profile_key: safe.profileKey,
    source_sample_asset_id: safe.sourceSampleAssetId,
    category: safe.category,
    garment_structure: {
      neckline: safe.garmentStructure.neckline,
      sleeve_type: safe.garmentStructure.sleeveType,
      fit: safe.garmentStructure.fit,
      closure: safe.garmentStructure.closure,
      hem_type: safe.garmentStructure.hemType,
    },
    view_rules: {
      supports_front: safe.viewRules.supportsFront,
      supports_back: safe.viewRules.supportsBack,
      front_back_must_not_swap: safe.viewRules.frontBackMustNotSwap,
    },
    design_rules: {
      preserve_text: safe.designRules.preserveText,
      preserve_numbers: safe.designRules.preserveNumbers,
      preserve_names: safe.designRules.preserveNames,
      preserve_graphics: safe.designRules.preserveGraphics,
      preserve_font_style: safe.designRules.preserveFontStyle,
      preserve_element_position: safe.designRules.preserveElementPosition,
    },
    structure_rules: {
      preserve_neckline: safe.structureRules.preserveNeckline,
      preserve_sleeves: safe.structureRules.preserveSleeves,
      preserve_garment_length: safe.structureRules.preserveGarmentLength,
      preserve_silhouette: safe.structureRules.preserveSilhouette,
    },
    analysis_model: safe.analysisModel,
    analysis_version: safe.analysisVersion,
  }
}

export function batchStyleProfileSummary(profile: BatchGarmentStyleProfile): string {
  return [
    `品类：${profile.category || '服装'}`,
    profile.garmentStructure.neckline ? `领型：${profile.garmentStructure.neckline}` : '',
    profile.garmentStructure.sleeveType ? `袖型：${profile.garmentStructure.sleeveType}` : '',
    profile.garmentStructure.fit ? `版型：${profile.garmentStructure.fit}` : '',
    `正反面规则：${profile.viewRules.frontBackMustNotSwap ? '严格保持' : '按当前服装判断'}`,
    `文字规则：${profile.designRules.preserveText ? '严格保持' : '按当前服装判断'}`,
    `号码规则：${profile.designRules.preserveNumbers ? '严格保持' : '按当前服装判断'}`,
    `字体规则：${profile.designRules.preserveFontStyle ? '严格保持' : '按当前服装判断'}`,
  ].filter(Boolean).join(' · ')
}

export interface BatchStyleProfileDisplayItem {
  label: string
  value: string
}

export interface BatchStyleProfileDisplay {
  category: string
  structure: BatchStyleProfileDisplayItem[]
  viewRules: string[]
  preservationRules: string[]
}

const STYLE_VALUE_LABELS: Record<string, string> = {
  apparel: '服装',
  football_jersey: '橄榄球衣',
  sports_jersey: '运动球衣',
  short_sleeve_vneck_sports_jersey: '短袖 V 领运动球衣',
  v_neck: 'V 领',
  crew_neck: '圆领',
  round_neck: '圆领',
  short_sleeve: '短袖',
  long_sleeve: '长袖',
  sleeveless: '无袖',
  cropped: '短款',
  regular: '常规版型',
  oversized: '宽松版型',
  slim: '修身版型',
  pullover: '套头',
  button: '纽扣',
  zipper: '拉链',
  straight: '直下摆',
  curved: '弧形下摆',
}

export function batchStyleProfileDisplay(profile: BatchGarmentStyleProfile): BatchStyleProfileDisplay {
  const structure = [
    ['领型', profile.garmentStructure.neckline],
    ['袖型', profile.garmentStructure.sleeveType],
    ['版型', profile.garmentStructure.fit],
    ['穿脱结构', profile.garmentStructure.closure],
    ['下摆', profile.garmentStructure.hemType],
  ].filter((item): item is [string, string] => Boolean(item[1]))
    .map(([label, value]) => ({ label, value: styleValueLabel(value) }))

  const viewRules = [
    profile.viewRules.supportsFront ? '支持正面参考' : '',
    profile.viewRules.supportsBack ? '支持背面参考' : '',
    profile.viewRules.frontBackMustNotSwap ? '正反面不可互换' : '',
  ].filter(Boolean)

  const preservationRules = [
    profile.designRules.preserveText ? '保持文字' : '',
    profile.designRules.preserveNumbers ? '保持号码' : '',
    profile.designRules.preserveNames ? '保持姓名' : '',
    profile.designRules.preserveGraphics ? '保持图案' : '',
    profile.designRules.preserveFontStyle ? '保持字体样式' : '',
    profile.designRules.preserveElementPosition ? '保持元素位置' : '',
    profile.structureRules.preserveNeckline ? '保持领型' : '',
    profile.structureRules.preserveSleeves ? '保持袖型' : '',
    profile.structureRules.preserveGarmentLength ? '保持衣长' : '',
    profile.structureRules.preserveSilhouette ? '保持轮廓' : '',
  ].filter(Boolean)

  return {
    category: styleValueLabel(profile.category || 'apparel'),
    structure,
    viewRules,
    preservationRules,
  }
}

function styleValueLabel(value: string): string {
  const normalized = value.trim()
  return STYLE_VALUE_LABELS[normalized.toLowerCase()] || normalized.replace(/_/g, ' ')
}

function parseJobJson(job: ServerJob): Record<string, unknown> {
  const metadata = asRecord(job.result_json?.metadata)
  const rawText = metadata.text
  if (typeof rawText !== 'string' || !rawText.trim()) throw new Error('服装分析任务没有返回有效 JSON。')
  const cleaned = rawText.trim().replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '')
  try {
    return asRecord(JSON.parse(cleaned))
  } catch {
    throw new Error('服装分析结果不是有效 JSON，请重试。')
  }
}

function asRecord(value: unknown): Record<string, any> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, any> : {}
}

function booleanValue(value: unknown, fallback: boolean): boolean {
  return typeof value === 'boolean' ? value : fallback
}

function stringValue(value: unknown, fallback: string): string {
  return typeof value === 'string' && value.trim() ? value.trim() : fallback
}

function cleanIdentifier(value: unknown, fallback: string): string {
  const cleaned = String(value || '').replace(/[^A-Za-z0-9_.:-]/g, '-').replace(/-+/g, '-').slice(0, 80)
  return cleaned || fallback
}

function cleanStructureValue(value: unknown, fallback: string): string {
  const text = stringValue(value, fallback).slice(0, 80)
  return forbiddenVariableDetail(text) ? fallback : text
}

function optionalStructureValue(value: unknown): string | undefined {
  if (typeof value !== 'string' || !value.trim()) return undefined
  const text = value.trim().slice(0, 80)
  return forbiddenVariableDetail(text) ? undefined : text
}

function forbiddenVariableDetail(value: string): boolean {
  return /(#[0-9a-f]{3,8}|\b(?:black|white|red|blue|green|yellow|orange|purple|pink|gray|grey|brown|gold|silver)\b|颜色|黑色|白色|红色|蓝色|绿色|黄色|号码|姓名|队名|logo|graphic content)/i.test(value)
}
