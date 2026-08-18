// @ts-expect-error Vitest runs this file in Node; the browser build intentionally omits Node typings.
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const source = readFileSync(new URL('./BatchTryOnReviewDialog.tsx', import.meta.url), 'utf8')

describe('BatchTryOnReviewDialog clipboard compatibility', () => {
  it('uses the shared clipboard fallback for submitted prompts', () => {
    expect(source).toContain("import { copyTextToClipboard } from '../lib/clipboard'")
    expect(source).toContain('await copyTextToClipboard(submittedPrompt)')
    expect(source).not.toContain('await navigator.clipboard.writeText(submittedPrompt)')
  })
})
