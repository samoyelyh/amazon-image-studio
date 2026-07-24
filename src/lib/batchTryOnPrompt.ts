import type { BatchTryOnPresetSelection } from '../types'
import { buildBatchTryOnPresetPrompt } from './batchTryOnPresets'

export const BATCH_TRY_ON_BASE_PROMPT = `You are performing a high-fidelity apparel virtual try-on image edit.

REFERENCE IMAGE ORDER:

* Reference Image 1 is the target model and base scene.
* Reference Image 2 is the exact garment that must be placed on the model.

PRIMARY TASK:
Replace only the garment currently worn by the model in Reference Image 1 with the garment shown in Reference Image 2. Make the garment fit the model naturally while preserving the original model image and the source garment design with the highest possible fidelity.

GARMENT FIDELITY — CRITICAL:
Preserve the exact garment design from Reference Image 2. Do not redesign, simplify, reinterpret, beautify, replace or invent any garment element.

Strictly preserve:

* garment category and silhouette
* neckline and collar shape
* sleeve type and sleeve length
* shoulder construction
* hem length and garment proportions
* front opening, placket, zipper and button positions
* panel construction, piping and seam lines
* all graphics, patterns and print placement
* all text, names, letters and spelling
* all numbers, including leading zeros
* logos, symbols, flags and badges
* stripes, borders, gradients and color blocks
* exact colors and color relationships
* fabric appearance, mesh texture and printed finish
* front-facing or back-facing garment orientation

Do not mirror, reverse, rotate, relocate or rewrite any text, number, logo, graphic, stripe or pattern.
Do not convert printed graphics into embroidery.
Do not add pockets, buttons, seams, stripes, logos, text or decorations that are not present in the garment reference.
Do not remove existing garment details.

MODEL AND SCENE PRESERVATION — CRITICAL:
Keep the model's identity, face, facial expression, hairstyle, skin tone, body shape, pose, hands, legs and visible anatomy unchanged.
Keep the original background, props, environment, camera angle, perspective, framing, crop, depth of field, lighting direction, shadows and overall composition unchanged.
Do not replace the model.
Do not change the model's age, gender presentation or body proportions.
Do not add or remove people or background objects.
Do not crop, zoom or expand the scene unless technically required to match the selected output dimensions.

EDITING BOUNDARY:
Modify only the clothing area that must be replaced.
Retain all non-clothing pixels and visual elements as closely as possible.
Adapt only the physically necessary drape, folds, perspective, occlusion and lighting so the referenced garment appears naturally worn by the existing model.
The garment must look clean, realistic, properly aligned and physically connected to the model's body.

OUTPUT RESTRICTIONS:
No new advertising text.
No captions.
No watermark.
No mockup labels.
No extra logo.
No extra accessories.
No duplicated limbs.
No distorted hands.
No damaged facial features.
No random garment variations.
No visual redesign.

FINAL PRIORITY:

1. Preserve the exact source garment elements.
2. Preserve the original model, pose and scene.
3. Produce a realistic and commercially usable apparel image.
   When visual improvement conflicts with garment accuracy, always prioritize garment accuracy.`

export interface BuildBatchTryOnPromptOptions {
  garmentFileName: string
  outputSize: string
  templateName?: string
  presetSelection?: BatchTryOnPresetSelection
  extraRequirements?: string
  reviewNotes?: string
  retryMode?: 'direct' | 'with_review_notes'
}

export function buildBatchTryOnPrompt(options: BuildBatchTryOnPromptOptions): string {
  const sections = [
    BATCH_TRY_ON_BASE_PROMPT,
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
