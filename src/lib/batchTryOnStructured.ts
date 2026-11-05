export const STRUCTURED_LUNA_FORMAT = 'garment_analysis_v1_1' as const
export type LunaAnalysisFormat = 'final_prompt_text' | typeof STRUCTURED_LUNA_FORMAT
export function isPerGarmentLuna(strategy?: string) {
  return strategy === 'luna_per_image' || strategy === 'luna_structured'
}
export interface StructuredLunaAnalysis {
  task_type: 'batch_garment_replacement'
  total_garments: 1
  template_analysis: {
    subject: string; pose: string; view_direction: string; original_clothing: string
    lighting: string; occlusions: string[]; protected_elements: string[]
  }
  jobs: Array<{
    garment_id: string; garment_type: string; view_direction: string; garment_structure: string
    colors: string[]; graphics: string[]; texts_and_numbers: string[]; replacement_region: string
    structural_changes: string[]; preservation_rules: string[]; removal_rules: string[]
    risk_level: 'LOW' | 'MEDIUM' | 'HIGH'; needs_manual_review: boolean
    uncertainties: string[]; generation_prompt: string
  }>
}
