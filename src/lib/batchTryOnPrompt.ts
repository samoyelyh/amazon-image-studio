import type { BatchTryOnPresetSelection } from '../types'
import { buildBatchTryOnPresetPrompt, resolveBatchTryOnPresetSelection } from './batchTryOnPresets'
import { AI_VIRTUAL_TRY_ON_PROMPT_INTRO, buildDynamicTryOnPrompt } from './batchTryOnDynamicPrompt'
import type { BatchGarmentStyleProfile } from './batchTryOnStyleProfile'

export const BATCH_TRY_ON_BASE_PROMPT = AI_VIRTUAL_TRY_ON_PROMPT_INTRO

export interface BuildBatchTryOnPromptOptions {
  garmentFileName: string
  outputSize: string
  templateName?: string
  presetSelection?: BatchTryOnPresetSelection
  extraRequirements?: string
  reviewNotes?: string
  retryMode?: 'direct' | 'with_review_notes'
  batchStyleProfile?: BatchGarmentStyleProfile
}

export function buildBatchTryOnPrompt(options: BuildBatchTryOnPromptOptions): string {
  const resolvedPreset = options.presetSelection
    ? resolveBatchTryOnPresetSelection(options.presetSelection)
    : undefined
  const preserveTemplateScene = !resolvedPreset
    || resolvedPreset.backgroundStyle === 'keep-original'
    || (!resolvedPreset.backgroundStyle && resolvedPreset.backgroundAdaptationMode === 'keep-unchanged')
  const sections = [
    buildDynamicTryOnPrompt({
      batchStyleProfile: options.batchStyleProfile,
      preserveTemplateScene,
    }),
    `CURRENT TASK:\n* Template name: ${options.templateName?.trim() || 'unnamed model template'}\n* Garment file name: ${options.garmentFileName.trim() || 'unnamed garment'}\n* Expected output size: ${options.outputSize.trim() || 'follow the model template image'}\n* Reference Image 1 is the model template. Reference Image 2 is the garment for this task. Keep this order unchanged.`,
  ]

  const presetPrompt = options.presetSelection ? buildBatchTryOnPresetPrompt(options.presetSelection) : ''
  if (presetPrompt) sections.push(presetPrompt)

  const extraRequirements = options.extraRequirements?.trim()
  if (extraRequirements) {
    sections.push(`ADDITIONAL USER REQUIREMENTS:\n${extraRequirements}\n\nThese additional requirements may refine the result but must never override the garment fidelity, model preservation, scene preservation, or reference image order rules above.`)
  }

  const reviewNotes = options.reviewNotes?.trim()
  if (reviewNotes) {
    sections.push(`REVIEW CORRECTION REQUIREMENTS:

The previous generated result did not pass manual review.

Correct the following issues:
${reviewNotes}

These correction instructions are additional requirements only.
They must not replace or weaken the mandatory garment fidelity requirements.

Continue to preserve:
- the original model identity and face
- hairstyle
- pose
- body proportions
- camera angle
- background
- lighting
- garment color
- graphics
- text
- numbers, including leading zeros
- logos
- stripes
- stitching
- panel structure
- neckline
- sleeves
- hem
- garment silhouette
- fabric appearance
- print-versus-embroidery characteristics`)
  }

  return sections.join('\n\n')
}
