import type { BatchGarmentStyleProfile } from '../types'
import {
  BATCH_STYLE_ANALYSIS_SYSTEM_PROMPT,
  BATCH_STYLE_ANALYSIS_USER_PROMPT,
  buildStructureConsistencyPrompt,
  parseConsistencyDecisions,
  parseProfileFromJob,
} from './batchTryOnStyleProfile'
import {
  getServerJob,
  isServerJobTerminal,
  resolveModelCode,
  submitServerJob,
  type ServerJob,
} from './jobsApi'
import { randomUuid } from './randomUuid'

export interface GarmentStyleAnalysisInput {
  garmentId: string
  assetId: string
  filename: string
}

export async function analyzeBatchGarmentStyles(options: {
  projectId: string
  garments: GarmentStyleAnalysisInput[]
  onStatus?: (message: string) => void
}): Promise<BatchGarmentStyleProfile[]> {
  const garments = uniqueGarments(options.garments)
  if (!garments.length) throw new Error('没有可分析的服装素材。')
  const modelCode = await resolveModelCode('text_generation', 'batch_tryon.style_analyze')
  const first = garments[0]
  options.onStatus?.(`正在完整分析第一件服装：${first.filename}`)
  const firstJob = await submitAnalysisJob({
    projectId: options.projectId,
    modelCode,
    referenceAssetIds: [first.assetId],
    systemPrompt: BATCH_STYLE_ANALYSIS_SYSTEM_PROMPT,
    userPrompt: BATCH_STYLE_ANALYSIS_USER_PROMPT,
    clientItemId: `style-sample:${first.garmentId}`,
  })
  const firstProfile = parseProfileFromJob(firstJob, {
    profileKey: `style-${randomUuid()}`,
    sourceSampleAssetId: first.assetId,
    sourceGarmentId: first.garmentId,
    analysisModel: modelCode,
  })
  const profiles = [firstProfile]

  const remaining = garments.slice(1)
  for (let offset = 0; offset < remaining.length; offset += 9) {
    const candidates = remaining.slice(offset, offset + 9)
    options.onStatus?.(`正在检查服装结构一致性：${offset + 1}-${offset + candidates.length} / ${remaining.length}`)
    const checkJob = await submitAnalysisJob({
      projectId: options.projectId,
      modelCode,
      referenceAssetIds: [first.assetId, ...candidates.map((item) => item.assetId)],
      systemPrompt: BATCH_STYLE_ANALYSIS_SYSTEM_PROMPT,
      userPrompt: buildStructureConsistencyPrompt(candidates.length),
      clientItemId: `style-check:${first.garmentId}:${offset + 1}`,
    })
    const decisions = parseConsistencyDecisions(checkJob, candidates.length)
    for (const [index, candidate] of candidates.entries()) {
      const decision = decisions[index]
      if (decision.sameStructureFamily) {
        firstProfile.coveredGarmentIds.push(candidate.garmentId)
        continue
      }
      options.onStatus?.(`检测到不同款式结构，正在建立新款式：${candidate.filename}`)
      const profileJob = await submitAnalysisJob({
        projectId: options.projectId,
        modelCode,
        referenceAssetIds: [candidate.assetId],
        systemPrompt: BATCH_STYLE_ANALYSIS_SYSTEM_PROMPT,
        userPrompt: BATCH_STYLE_ANALYSIS_USER_PROMPT,
        clientItemId: `style-sample:${candidate.garmentId}`,
      })
      profiles.push(parseProfileFromJob(profileJob, {
        profileKey: `style-${randomUuid()}`,
        sourceSampleAssetId: candidate.assetId,
        sourceGarmentId: candidate.garmentId,
        analysisModel: modelCode,
      }))
    }
  }
  options.onStatus?.(`已分析批次款式：${profiles.length} 个结构组`)
  return profiles
}

export function findStyleProfileForGarment(
  profiles: BatchGarmentStyleProfile[] | undefined,
  garmentId: string | undefined,
): BatchGarmentStyleProfile | undefined {
  if (!garmentId) return undefined
  return profiles?.find((profile) => profile.coveredGarmentIds.includes(garmentId))
}

function uniqueGarments(garments: GarmentStyleAnalysisInput[]) {
  return Array.from(new Map(garments.map((item) => [item.garmentId, item])).values())
}

async function submitAnalysisJob(options: {
  projectId: string
  modelCode: string
  referenceAssetIds: string[]
  systemPrompt: string
  userPrompt: string
  clientItemId: string
}): Promise<ServerJob> {
  const submitted = await submitServerJob({
    operation_code: 'batch_tryon.style_analyze',
    workspace_type: 'batch_tryon',
    queue_name: 'planning_queue',
    capability: 'text_generation',
    model_code: options.modelCode,
    idempotency_key: `batch-style:${randomUuid()}`,
    project_id: options.projectId,
    client_item_id: options.clientItemId.slice(0, 120),
    billing_factors: { quality: 'standard', resolution: 'text' },
    input: {
      system_prompt: options.systemPrompt,
      user_prompt: options.userPrompt,
      temperature: 0,
      reference_asset_ids: options.referenceAssetIds,
      metadata: { workflow: 'batch_tryon_style_profile' },
    },
  })
  return waitForAnalysisJob(submitted)
}

async function waitForAnalysisJob(initial: ServerJob): Promise<ServerJob> {
  let job = initial
  const deadline = Date.now() + 15 * 60 * 1000
  while (!isServerJobTerminal(job.status)) {
    if (Date.now() >= deadline) throw new Error('批次服装分析超时，请稍后重试。')
    await new Promise((resolve) => setTimeout(resolve, 1500))
    job = await getServerJob(job.id)
  }
  if (job.status !== 'succeeded') throw new Error(job.error_message || '批次服装分析失败。')
  return job
}
