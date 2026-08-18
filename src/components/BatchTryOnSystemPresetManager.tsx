import { useEffect, useMemo, useState } from 'react'
import {
  updateBatchTryOnPromptPreset,
  type BatchTryOnPromptPreset,
  type BatchTryOnTemplateType,
} from '../lib/batchTryOnWorkflowApi'

interface Props {
  presets: BatchTryOnPromptPreset[]
  onClose: () => void
  onUpdated: (preset: BatchTryOnPromptPreset) => void
  onError: (message: string) => void
}

const TYPE_LABELS: Record<BatchTryOnTemplateType, string> = {
  pure_white: '纯白底图',
  gift_scene: '礼品场景图',
  stadium_scene: '观赛场景图',
  detail_display: '细节展示图',
  casual_scene: '休闲场景图',
  custom_process: '定制信息流程图',
}

export default function BatchTryOnSystemPresetManager({ presets, onClose, onUpdated, onError }: Props) {
  const systemPresets = useMemo(
    () => presets.filter((preset) => preset.scope === 'system').sort((a, b) => a.sort_order - b.sort_order),
    [presets],
  )
  const [selectedId, setSelectedId] = useState(systemPresets[0]?.id || '')
  const selected = systemPresets.find((preset) => preset.id === selectedId) || systemPresets[0]
  const [label, setLabel] = useState(selected?.label || '')
  const [prompt, setPrompt] = useState(selected?.analysis_prompt_template || '')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!selected) return
    setLabel(selected.label)
    setPrompt(selected.analysis_prompt_template)
  }, [selected?.id, selected?.label, selected?.analysis_prompt_template])

  const dirty = Boolean(selected && (
    label.trim() !== selected.label || prompt.trim() !== selected.analysis_prompt_template
  ))

  const save = async () => {
    if (!selected || label.trim().length === 0 || prompt.trim().length < 20 || !dirty) return
    setSaving(true)
    try {
      const updated = await updateBatchTryOnPromptPreset(selected.id, {
        label: label.trim(),
        analysis_prompt_template: prompt.trim(),
      })
      onUpdated(updated)
      setLabel(updated.label)
      setPrompt(updated.analysis_prompt_template)
    } catch (error) {
      onError(error instanceof Error ? error.message : '系统预设保存失败，请重试。')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[115] flex items-center justify-center bg-gray-950/60 p-4" role="dialog" aria-modal="true" aria-label="系统提示词预设管理" onMouseDown={(event) => { if (event.target === event.currentTarget && !saving) onClose() }}>
      <div className="flex max-h-[90vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl dark:bg-gray-950">
        <header className="flex items-start justify-between gap-4 border-b border-gray-100 px-5 py-4 dark:border-white/[0.08]">
          <div>
            <div className="text-xs font-semibold text-blue-600">平台管理员</div>
            <h2 className="mt-1 text-lg font-bold text-gray-900 dark:text-white">系统提示词预设管理</h2>
            <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">保存只影响之后加载预设或创建的新任务，现有草稿和历史任务快照不会被改写。</p>
          </div>
          <button type="button" disabled={saving} onClick={onClose} className="grid h-9 w-9 shrink-0 place-items-center rounded-lg text-xl text-gray-400 hover:bg-gray-100 disabled:opacity-40 dark:hover:bg-white/[0.06]" aria-label="关闭">×</button>
        </header>

        <div className="grid min-h-0 flex-1 md:grid-cols-[220px_minmax(0,1fr)]">
          <nav className="overflow-y-auto border-b border-gray-100 bg-gray-50 p-3 dark:border-white/[0.08] dark:bg-white/[0.025] md:border-b-0 md:border-r">
            <div className="mb-2 px-2 text-[11px] font-semibold uppercase tracking-wide text-gray-400">系统模板类型</div>
            <div className="space-y-1">
              {systemPresets.map((preset) => (
                <button
                  key={preset.id}
                  type="button"
                  disabled={saving}
                  onClick={() => setSelectedId(preset.id)}
                  className={`w-full rounded-xl px-3 py-2.5 text-left text-sm font-semibold transition ${selected?.id === preset.id ? 'bg-blue-600 text-white shadow-sm' : 'text-gray-700 hover:bg-white dark:text-gray-200 dark:hover:bg-white/[0.06]'}`}
                >
                  {TYPE_LABELS[preset.template_type]}
                </button>
              ))}
            </div>
          </nav>

          <main className="min-h-0 overflow-y-auto p-5">
            {!selected ? (
              <div className="rounded-xl border border-dashed border-gray-200 p-8 text-center text-sm text-gray-500">没有可管理的系统预设。</div>
            ) : (
              <div className="space-y-4">
                <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_180px]">
                  <label className="block">
                    <span className="mb-1.5 block text-xs font-semibold text-gray-600 dark:text-gray-300">显示名称</span>
                    <input value={label} disabled={saving} maxLength={160} onChange={(event) => setLabel(event.target.value)} className="h-10 w-full rounded-xl border border-gray-200 px-3 text-sm outline-none focus:border-blue-400 dark:border-white/[0.08] dark:bg-gray-900 dark:text-white" />
                  </label>
                  <div>
                    <span className="mb-1.5 block text-xs font-semibold text-gray-600 dark:text-gray-300">模板代码</span>
                    <div className="flex h-10 items-center rounded-xl bg-gray-100 px-3 font-mono text-xs text-gray-600 dark:bg-white/[0.06] dark:text-gray-300">{selected.template_type}</div>
                  </div>
                </div>
                <label className="block">
                  <div className="mb-1.5 flex items-center justify-between gap-3">
                    <span className="text-xs font-semibold text-gray-600 dark:text-gray-300">系统预设提示词</span>
                    <span className="text-[11px] text-gray-400">{prompt.length} / 30000</span>
                  </div>
                  <textarea value={prompt} disabled={saving} maxLength={30000} rows={24} onChange={(event) => setPrompt(event.target.value)} className="w-full resize-y rounded-xl border border-gray-200 bg-gray-50 px-3 py-3 text-sm leading-6 text-gray-800 outline-none focus:border-blue-400 dark:border-white/[0.08] dark:bg-gray-900 dark:text-gray-100" />
                </label>
              </div>
            )}
          </main>
        </div>

        <footer className="flex flex-col gap-3 border-t border-gray-100 px-5 py-4 dark:border-white/[0.08] sm:flex-row sm:items-center sm:justify-between">
          <div className="text-xs text-gray-500">系统预设仅平台管理员可修改，后端会再次校验权限。</div>
          <div className="flex justify-end gap-2">
            <button type="button" disabled={saving} onClick={onClose} className="h-10 rounded-xl border border-gray-200 px-4 text-sm font-semibold text-gray-600 disabled:opacity-40 dark:border-white/[0.1] dark:text-gray-300">取消</button>
            <button type="button" disabled={saving || !dirty || !label.trim() || prompt.trim().length < 20} onClick={() => void save()} className="h-10 rounded-xl bg-blue-600 px-5 text-sm font-semibold text-white disabled:bg-gray-300">{saving ? '正在保存…' : '保存系统预设'}</button>
          </div>
        </footer>
      </div>
    </div>
  )
}
