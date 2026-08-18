import type { BatchTryOnTemplatePrompt } from './batchTryOnWorkflowApi'

type PromptRecord = Pick<
  BatchTryOnTemplatePrompt,
  'id' | 'generated_final_prompt' | 'edited_final_prompt'
>

export interface BatchTryOnPromptDraftSyncResult {
  drafts: Record<string, string>
  serverPrompts: Record<string, string>
}

/**
 * Keep a user's in-progress edit intact while still accepting a newly completed
 * AI analysis. The server record exists before analysis finishes, so checking
 * only whether the record id has been initialized leaves the textarea empty.
 */
export function syncBatchTryOnPromptDrafts(
  currentDrafts: Record<string, string>,
  previousServerPrompts: Record<string, string>,
  records: PromptRecord[],
): BatchTryOnPromptDraftSyncResult {
  const drafts: Record<string, string> = {}
  const serverPrompts: Record<string, string> = {}

  for (const record of records) {
    const serverPrompt = record.edited_final_prompt || record.generated_final_prompt || ''
    const currentDraft = currentDrafts[record.id]
    const previousServerPrompt = previousServerPrompts[record.id]

    serverPrompts[record.id] = serverPrompt
    drafts[record.id] = (
      currentDraft === undefined
      || currentDraft.trim() === ''
      || currentDraft === previousServerPrompt
    )
      ? serverPrompt
      : currentDraft
  }

  return { drafts, serverPrompts }
}
