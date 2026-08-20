import { describe, expect, it } from 'vitest'
import { attachmentMaterialCompletionLabel, materialVersionByNumber } from './attachmentMaterialLibrary'
import type { AttachmentMaterialVersion } from './attachmentMaterialApi'

describe('attachment material library helpers', () => {
  it('calculates completeness from the selected module snapshot target', () => {
    expect(attachmentMaterialCompletionLabel(3, 3, true)).toBe('完整套图 · 目标 3/3')
    expect(attachmentMaterialCompletionLabel(3, 6, false)).toBe('未完整 · 已保存 3 张 / 目标 6')
    expect(attachmentMaterialCompletionLabel(3, 2, true)).toBe('完整套图 · 目标 2/2 · 已保存 3 张')
  })

  it('switches immutable versions without mutating the list', () => {
    const versions = [
      { version_number: 2, id: 'v2' },
      { version_number: 1, id: 'v1' },
    ] as AttachmentMaterialVersion[]
    expect(materialVersionByNumber(versions, 1)?.id).toBe('v1')
    expect(materialVersionByNumber(versions, null)?.id).toBe('v2')
    expect(versions.map((item) => item.id)).toEqual(['v2', 'v1'])
  })
})
