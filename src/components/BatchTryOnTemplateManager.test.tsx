import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import BatchTryOnTemplateManager from './BatchTryOnTemplateManager'

describe('optional template prompt preset', () => {
  it('provides a selectable custom option and editable prompt without any preset', () => {
    const noop = () => undefined
    const markup = renderToStaticMarkup(<BatchTryOnTemplateManager
      templates={[{ id: 't', imageId: 'image', fileName: 'model.png', displayName: '模板一', selected: true, isDefault: true }]}
      maxItems={10} promptPresets={[]} promptPresetIds={{ t: '' }}
      promptValues={{ t: '保留人物，只替换图B服装。' }} onPromptChange={noop}
      onUpload={noop} onRemove={noop} onPromptPresetChange={noop} onSetDefault={noop}
      onToggle={noop} onToggleAll={noop} onView={noop}
    />)
    expect(markup).toContain('提示词预设（可选）')
    expect(markup).toMatch(/<option value="" selected="">不使用预设 · 自定义提示词<\/option>/)
    expect(markup).toContain('aria-label="模板一 自定义提示词"')
    expect(markup).toContain('保留人物，只替换图B服装。')
    expect(markup).toContain('直接使用当前提示词 · 不经Luna')
  })
})
