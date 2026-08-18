import type { BatchTryOnTemplatePrompt } from './batchTryOnWorkflowApi'

export interface BatchTryOnValidationPromptValues {
  analysisPrompt: string
  sampleFinalPrompt: string
  sampleFinalPromptLabel: string
}

/**
 * Keep the reusable template analysis preset separate from the final prompt
 * produced for one validation garment. A per-image Luna result must never
 * become the analysis preset for later garments.
 */
export function resolveBatchTryOnValidationPromptValues(
  configuredAnalysisPrompt: string,
  record?: BatchTryOnTemplatePrompt,
): BatchTryOnValidationPromptValues {
  const sampleFinalPrompt = record?.edited_final_prompt?.trim()
    || record?.generated_final_prompt?.trim()
    || record?.analysis_prompt_used?.trim()
    || ''

  return {
    analysisPrompt: configuredAnalysisPrompt.trim(),
    sampleFinalPrompt,
    sampleFinalPromptLabel: record?.edited_final_prompt?.trim()
      ? `样图实际提示词 · 人工版 V${record.prompt_version}`
      : record?.generated_final_prompt?.trim()
        ? `样图实际提示词 · AI版 V${record.prompt_version}`
        : sampleFinalPrompt
          ? '样图提交时的提示词快照'
          : '当前样图尚未读取到最终提示词快照',
  }
}
