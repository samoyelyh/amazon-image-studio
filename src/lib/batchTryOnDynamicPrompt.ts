import type { BatchGarmentStyleProfile } from './batchTryOnStyleProfile'
import { batchStyleProfileSnapshot } from './batchTryOnStyleProfile'

export const AI_VIRTUAL_TRY_ON_PROMPT_INTRO = `AI VIRTUAL TRY-ON — FINAL DYNAMIC PROMPT

Replace only the garment worn by the model in the TEMPLATE IMAGE with the CURRENT GARMENT REFERENCE.

The final result must preserve the original template model, pose, body structure, composition, and scene while accurately transferring the CURRENT garment onto the model.

The garment must adapt naturally to the model. The model must NOT be changed to adapt to the garment.`

const INSPECT_TEMPLATE = 'Determine this directly from Reference Image 1 (TEMPLATE IMAGE) at generation time and preserve it.'
const INSPECT_CURRENT_GARMENT = 'Determine this directly from Reference Image 2 (CURRENT GARMENT REFERENCE) at generation time. Do not infer it from the first garment or another batch item.'

const DYNAMIC_PROMPT_TEMPLATE = `${AI_VIRTUAL_TRY_ON_PROMPT_INTRO}

---

## 1. SHARED GARMENT STRUCTURE

The following structural information was extracted from the first garment in this batch and is used ONLY to define the shared garment construction:

{{batch_garment_structure_profile}}

This shared profile may include garment category, neckline construction, sleeve type and length, garment length, silhouette or fit, hem construction, closure structure, front/back structural relationship, panel construction, and general garment construction rules.

IMPORTANT: The first garment is used ONLY to determine shared structural characteristics.

DO NOT inherit color, color combination, text, wording, name, number, logo, graphic, print, typography, stripe colors, or decorative artwork from the first garment. These variable visual details must ALWAYS come from the CURRENT garment reference.

---

## 2. CURRENT GARMENT IS THE VISUAL SOURCE OF TRUTH

Reference Image 2, the CURRENT GARMENT REFERENCE IMAGE, is the only source of truth for the garment's variable visual design.

Preserve the exact garment design from the CURRENT GARMENT REFERENCE. Do not redesign, simplify, reinterpret, beautify, or invent any garment element.

Preserve exactly from the CURRENT garment: actual colors and their distribution; color blocking; stripes and trim colors; all text, letters, wording, names, numbers, logos, graphics, and printed artwork; typography, number style, outline, shadow, spacing, placement, scale, and orientation; neckline, sleeve, and hem appearance; silhouette; and visible stitching and panel details.

Do not copy or inherit visual details from any previously processed garment.

---

## 3. COLOR PRESERVATION — CRITICAL

Preserve the exact colors and color distribution shown in the CURRENT garment reference image.

Do NOT recolor the garment, borrow colors from another garment, shift garment hue to match the background, simplify multicolor designs, replace accent or stripe colors, or change typography or number colors.

The scene may adapt only when the selected task settings explicitly permit it. The garment must never be recolored to adapt to the scene.

---

## 4. FRONT / BACK ORIENTATION — CRITICAL

Template body view:
{{template_body_view}}

Template body rotation:
{{template_body_rotation}}

Current garment visible view information:
{{current_garment_view_information}}

Front-side garment elements must remain on the front and back-side elements must remain on the back. Never swap front and back, place front chest graphics on the back, place back names or numbers on the front, mirror garment artwork, or reverse text or numbers.

If the TEMPLATE primarily shows the model from the FRONT, use only the CURRENT garment's front design for visible front-facing areas. If it primarily shows the BACK, use only its back design for visible back-facing areas. For SIDE or THREE-QUARTER views, wrap the garment naturally around the body perspective while preserving the spatial relationship between front and back elements.

---

## 5. TEXT / NUMBER / FONT PRESERVATION — CRITICAL

Every visible letter, word, name, number, logo, and typographic element must remain as faithful as possible to the CURRENT garment reference.

Do NOT misspell, rewrite, translate, replace, simplify, invent, reorder, mirror, or reverse typography. Do not replace the original font with a generic font or move typography to another garment area.

Preserve font appearance, letter and number shape, weight, outline, double outline, shadow, curvature, arch, spacing, alignment, relative scale, position, and orientation.

Current number elements:
{{current_number_elements}}

Current text elements:
{{current_text_elements}}

Any visible number and wording must remain exactly the same, including leading zeros.

---

## 6. TEMPLATE STRUCTURE

The garment must fit naturally to the existing TEMPLATE structure.

Body orientation: {{template_body_view}}
Approximate body rotation: {{template_body_rotation}}
Pose: {{template_pose}}
Left arm: {{template_left_arm_pose}}
Right arm: {{template_right_arm_pose}}
Visible garment regions: {{template_visible_regions}}
Occluded garment regions: {{template_occluded_regions}}
Body crop: {{template_body_crop}}
Body proportions: {{template_body_proportion}}
Camera: {{template_camera_information}}

Use information observed directly in the TEMPLATE IMAGE to adapt the CURRENT garment realistically. Do not invent or alter template characteristics.

---

## 7. GARMENT FITTING

Fit the CURRENT garment naturally onto the model's existing body while preserving shoulder width, torso and waist proportions, arm length, body shape, and posture.

Allow physically realistic folds, compression, stretching, perspective deformation, sleeve bending, torso wrapping, and natural draping caused by the pose. Realistic fabric deformation is allowed; garment redesign is not.

---

## 8. NECKLINE AND SHOULDER FITTING

Current garment neckline:
{{current_neckline}}

Fit the neckline naturally around the model's neck and shoulders. Do not inherit the neckline from the clothing originally worn in the TEMPLATE. Never convert one neckline or collar construction into another. Preserve shoulder construction and seam placement.

---

## 9. SLEEVE FITTING

Current garment sleeve structure:
{{current_sleeve_structure}}

Fit both sleeves naturally to the model's arm position. If an arm is bent, allow the fabric to bend and fold naturally. Do NOT change sleeve length, sleeve shape, cuff construction, stripe count or sequence, trim design, or printed sleeve elements.

---

## 10. GARMENT LENGTH AND HEM

Current garment length and fit:
{{current_garment_length_and_fit}}

Preserve the correct garment length and hem position. Do not lengthen a cropped garment or shorten a regular-length garment. If the TEMPLATE crop does not show the full hem, do not expand the composition to reveal it; preserve the original framing.

---

## 11. OCCLUSION HANDLING

Template occlusion analysis:
{{template_occlusion_constraints}}

Keep the garment naturally behind any covering hair, hands, crossed arms, or foreground objects. Never draw fabric, numbers, letters, graphics, or stripes over those occluders. Preserve natural depth relationships, and never remove or deform body parts, hair, or objects to expose more garment detail.

---

## 12. BODY ROTATION AND PERSPECTIVE

The TEMPLATE body rotation is:
{{template_body_rotation}}

Conform the CURRENT garment to this orientation. Apply physically appropriate perspective deformation to fabric, artwork, stripes, numbers, text, and seams without changing the design. Text and numbers may follow body perspective but must remain recognizable and faithful.

---

## 13. MODEL PRESERVATION — CRITICAL

Keep the TEMPLATE model unchanged. Preserve identity, face, facial features, expression, hairstyle and length, skin tone, body proportions, posture, pose, arm, hand, finger and leg positions, camera angle and distance, and framing.

Do not replace the model, beautify or reshape the body, change shoulder width, alter pose or hands, change hairstyle, or regenerate the face unnecessarily. Only replace the garment.

---

## 14. TEMPLATE SCENE PRESERVATION

Preserve the original TEMPLATE scene, composition, camera position, perspective, major background objects, and model placement. Do not redesign the scene unless the selected task settings explicitly request it.

---

## 15. COLOR-ADAPTIVE VISUAL MOOD

Current garment palette information:
{{current_garment_palette}}

Suggested visual mood:
{{current_palette_mood}}

Scene adaptation policy for this task:
{{scene_adaptation_policy}}

Only when the task settings permit scene adaptation, the surrounding mood may be adjusted through background tone, supporting accents, ambient lighting, warm/cool balance, and atmosphere. Such adjustments must remain subtle unless explicitly requested. They must never recolor or obscure the product.

---

## 16. SCENE-TO-GARMENT COLOR RELATIONSHIP

The background may harmonize with the garment only when scene adaptation is enabled. The garment must NOT be recolored to harmonize with the background. Never modify the actual product palette.

---

## 17. PRODUCT PRIORITY

The garment is the commercial product and must remain the primary visual reference. Scene styling must never overpower it, reduce visibility, obscure text or numbers, distort colors, add confusing graphics, or make details difficult to identify.

---

## 18. TEMPLATE GARMENT MUST NOT LEAK INTO RESULT

The clothing originally worn by the TEMPLATE model may be used only to understand body coverage, garment region, pose, occlusion, and body shape.

Do not preserve any TEMPLATE garment colors, graphics, lettering, numbers, logos, neckline or sleeve design, trims, or patterns. Fully replace it with the CURRENT garment.

---

## 19. CURRENT GARMENT PRIORITY ORDER

1. Correct CURRENT garment identity
2. Correct front/back orientation
3. Correct text and number content
4. Correct typography and artwork
5. Correct garment colors
6. Correct garment construction
7. Correct garment fit to TEMPLATE pose
8. Correct occlusion
9. Correct model preservation
10. Scene and mood adaptation

Never sacrifice product accuracy for visual styling.

---

## 20. FINAL OUTPUT REQUIREMENT

Create a photorealistic virtual try-on result. The CURRENT garment should look naturally worn by the existing TEMPLATE model, with realistic fabric behavior, natural body fit, correct perspective, and physically believable occlusion.

The result must look as though the model originally wore this exact garment during the TEMPLATE photoshoot.

Do not create a pasted-on texture appearance, floating graphics, distorted typography, mixed front/back artwork, model alterations, product redesign, or inherited variable characteristics from the first garment.

The CURRENT garment reference determines product appearance. The batch structure profile determines shared construction rules. The TEMPLATE IMAGE determines how the garment physically fits the model. The CURRENT garment palette may influence the surrounding mood only when permitted, but never the garment itself.

Only replace the garment while preserving product fidelity, template realism, and natural visual integration.`

export interface BuildDynamicTryOnPromptOptions {
  batchStyleProfile?: BatchGarmentStyleProfile
  preserveTemplateScene?: boolean
}

export function buildDynamicTryOnPrompt(options: BuildDynamicTryOnPromptOptions = {}): string {
  const profile = options.batchStyleProfile
  const sharedProfile = profile
    ? JSON.stringify(batchStyleProfileSnapshot(profile), null, 2)
    : 'No precomputed shared profile is available. Infer construction only from the CURRENT GARMENT REFERENCE and never from another garment.'

  const currentField = (profileValue?: string) => profileValue
    ? `Shared structure profile value: ${profileValue}. Verify it against the CURRENT GARMENT REFERENCE; the current image wins if they differ.`
    : INSPECT_CURRENT_GARMENT

  const values: Record<string, string> = {
    batch_garment_structure_profile: sharedProfile,
    template_body_view: INSPECT_TEMPLATE,
    template_body_rotation: INSPECT_TEMPLATE,
    current_garment_view_information: INSPECT_CURRENT_GARMENT,
    current_number_elements: INSPECT_CURRENT_GARMENT,
    current_text_elements: INSPECT_CURRENT_GARMENT,
    template_pose: INSPECT_TEMPLATE,
    template_left_arm_pose: INSPECT_TEMPLATE,
    template_right_arm_pose: INSPECT_TEMPLATE,
    template_visible_regions: INSPECT_TEMPLATE,
    template_occluded_regions: INSPECT_TEMPLATE,
    template_body_crop: INSPECT_TEMPLATE,
    template_body_proportion: INSPECT_TEMPLATE,
    template_camera_information: INSPECT_TEMPLATE,
    current_neckline: currentField(profile?.garmentStructure.neckline),
    current_sleeve_structure: currentField(profile?.garmentStructure.sleeveType),
    current_garment_length_and_fit: currentField([
      profile?.garmentStructure.fit,
      profile?.garmentStructure.hemType,
    ].filter(Boolean).join('; ') || undefined),
    template_occlusion_constraints: INSPECT_TEMPLATE,
    current_garment_palette: INSPECT_CURRENT_GARMENT,
    current_palette_mood: options.preserveTemplateScene === false
      ? 'Infer a restrained commercial mood from the CURRENT garment palette without modifying the garment itself.'
      : 'No mood adaptation. Preserve the TEMPLATE scene, background tone, and lighting exactly.',
    scene_adaptation_policy: options.preserveTemplateScene === false
      ? 'Scene adaptation is permitted only to the degree requested by the selected background presets or user requirements.'
      : 'Scene adaptation is disabled. Preserve the TEMPLATE background, lighting, color balance, and atmosphere exactly.',
  }

  return DYNAMIC_PROMPT_TEMPLATE.replace(/\{\{([a-z0-9_]+)\}\}/g, (_token, key: string) => values[key] || INSPECT_CURRENT_GARMENT)
}
