import type { ListingImageTaskGroup } from './listingWorkflowApi'

export const ATTACHMENT_WORKBENCH_CONFIG_KEY = 'attachment_workbench'

export const ATTACHMENT_MODULE_CODES = [
  'pure_white',
  'custom_process',
  'stadium_scene',
  'gift_scene',
  'detail_display',
  'casual_scene',
] as const

export type AttachmentModuleCode = (typeof ATTACHMENT_MODULE_CODES)[number]
export type AttachmentGenerationMode = 'standard' | 'creative'

export interface AttachmentModuleDefinition {
  code: AttachmentModuleCode
  name: string
  shortDescription: string
  defaultAspectRatio: string
  allowedAspectRatios: string[]
}

export interface AttachmentModuleDraft {
  selected: boolean
  aspectRatio: string
  imageCount: number
  generationMode: AttachmentGenerationMode
}

export interface AttachmentWorkbenchDraft {
  schemaVersion: 1
  visualDirection: string
  modules: Record<AttachmentModuleCode, AttachmentModuleDraft>
}

export interface AttachmentTaskSummary {
  total: number
  queued: number
  running: number
  succeeded: number
  failed: number
  cancelled: number
  activeGroups: number
  completedGroups: number
}

export const attachmentModuleDefinitions: AttachmentModuleDefinition[] = [
  {
    code: 'pure_white',
    name: '纯白底图',
    shortDescription: '突出商品本体、正背关系和电商白底展示。',
    defaultAspectRatio: '1:1',
    allowedAspectRatios: ['1:1', '4:5', '3:4'],
  },
  {
    code: 'custom_process',
    name: '定制流程图',
    shortDescription: '展示姓名、号码等定制步骤与商品对应关系。',
    defaultAspectRatio: '1:1',
    allowedAspectRatios: ['1:1', '4:5', '3:4'],
  },
  {
    code: 'stadium_scene',
    name: '观赛场景图',
    shortDescription: '营造比赛日、看台或球场观赛氛围。',
    defaultAspectRatio: '4:5',
    allowedAspectRatios: ['4:5', '3:4', '1:1'],
  },
  {
    code: 'gift_scene',
    name: '礼品场景图',
    shortDescription: '呈现礼盒、节日赠礼与个性化礼品价值。',
    defaultAspectRatio: '1:1',
    allowedAspectRatios: ['1:1', '4:5', '3:4'],
  },
  {
    code: 'detail_display',
    name: '细节展示图',
    shortDescription: '聚焦领口、袖口、面料、印花和缝线细节。',
    defaultAspectRatio: '1:1',
    allowedAspectRatios: ['1:1', '4:5', '3:4'],
  },
  {
    code: 'casual_scene',
    name: '休闲场景图',
    shortDescription: '展示日常穿搭、街头或生活方式场景。',
    defaultAspectRatio: '4:5',
    allowedAspectRatios: ['4:5', '3:4', '1:1'],
  },
]

const definitionByCode = Object.fromEntries(
  attachmentModuleDefinitions.map((definition) => [definition.code, definition]),
) as Record<AttachmentModuleCode, AttachmentModuleDefinition>

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function isModuleCode(value: string): value is AttachmentModuleCode {
  return (ATTACHMENT_MODULE_CODES as readonly string[]).includes(value)
}

function clampImageCount(value: unknown) {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return 1
  return Math.max(1, Math.min(4, Math.round(parsed)))
}

export function createAttachmentWorkbenchDraft(availableCodes: readonly string[] = ATTACHMENT_MODULE_CODES): AttachmentWorkbenchDraft {
  const available = new Set(availableCodes)
  return {
    schemaVersion: 1,
    visualDirection: '',
    modules: Object.fromEntries(attachmentModuleDefinitions.map((definition) => [definition.code, {
      selected: available.has(definition.code),
      aspectRatio: definition.defaultAspectRatio,
      imageCount: 1,
      generationMode: 'standard' as const,
    }])) as Record<AttachmentModuleCode, AttachmentModuleDraft>,
  }
}

export function normalizeAttachmentWorkbenchDraft(
  value: unknown,
  availableCodes: readonly string[] = ATTACHMENT_MODULE_CODES,
): AttachmentWorkbenchDraft {
  const defaults = createAttachmentWorkbenchDraft(availableCodes)
  if (!isObject(value)) return defaults
  const savedModules = isObject(value.modules) ? value.modules : {}
  const available = new Set(availableCodes)
  const modules = { ...defaults.modules }

  for (const [rawCode, rawDraft] of Object.entries(savedModules)) {
    if (!isModuleCode(rawCode) || !isObject(rawDraft)) continue
    const definition = definitionByCode[rawCode]
    const aspectRatio = typeof rawDraft.aspectRatio === 'string' && definition.allowedAspectRatios.includes(rawDraft.aspectRatio)
      ? rawDraft.aspectRatio
      : definition.defaultAspectRatio
    modules[rawCode] = {
      selected: available.has(rawCode) && rawDraft.selected !== false,
      aspectRatio,
      imageCount: clampImageCount(rawDraft.imageCount),
      generationMode: rawDraft.generationMode === 'creative' ? 'creative' : 'standard',
    }
  }

  return {
    schemaVersion: 1,
    visualDirection: typeof value.visualDirection === 'string' ? value.visualDirection.slice(0, 4000) : '',
    modules,
  }
}

export function selectedAttachmentModules(draft: AttachmentWorkbenchDraft) {
  return attachmentModuleDefinitions.filter((definition) => draft.modules[definition.code].selected)
}

export function countRequestedAttachmentImages(draft: AttachmentWorkbenchDraft) {
  return selectedAttachmentModules(draft).reduce((total, definition) => total + draft.modules[definition.code].imageCount, 0)
}

export function summarizeAttachmentTaskGroups(groups: ListingImageTaskGroup[]): AttachmentTaskSummary {
  const terminal = new Set(['succeeded', 'partially_succeeded', 'failed', 'cancelled'])
  return groups.reduce<AttachmentTaskSummary>((summary, group) => ({
    total: summary.total + group.statistics.total,
    queued: summary.queued + group.statistics.queued,
    running: summary.running + group.statistics.running,
    succeeded: summary.succeeded + group.statistics.succeeded,
    failed: summary.failed + group.statistics.failed,
    cancelled: summary.cancelled + group.statistics.cancelled,
    activeGroups: summary.activeGroups + (terminal.has(group.status) ? 0 : 1),
    completedGroups: summary.completedGroups + (terminal.has(group.status) ? 1 : 0),
  }), { total: 0, queued: 0, running: 0, succeeded: 0, failed: 0, cancelled: 0, activeGroups: 0, completedGroups: 0 })
}

export function isAttachmentSessionReady(session: { confirmed_at: string | null; listing_version_number: number | null }) {
  return Boolean(session.confirmed_at && session.listing_version_number)
}
