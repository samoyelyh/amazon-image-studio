import type { BatchTryOnPresetSelection } from '../types'
import {
  findBatchTryOnPreset,
  presetsForCategory,
  resolveBatchTryOnPresetSelection,
  summarizeBatchTryOnPresets,
  type BatchTryOnPresetCategory,
} from '../lib/batchTryOnPresets'

interface Props {
  selection: BatchTryOnPresetSelection
  disabled?: boolean
  onChange: (selection: BatchTryOnPresetSelection) => void
}

const FIELDS: Array<{
  category: BatchTryOnPresetCategory
  field: keyof BatchTryOnPresetSelection
  label: string
  optional?: boolean
}> = [
  { category: 'target_audience', field: 'targetAudience', label: '人群预设', optional: true },
  { category: 'replacement_mode', field: 'replacementMode', label: '换衣效果' },
  { category: 'background_style', field: 'backgroundStyle', label: '背景风格' },
  { category: 'background_adaptation_mode', field: 'backgroundAdaptationMode', label: '背景适配' },
]

export default function BatchTryOnPresetPanel({ selection, disabled, onChange }: Props) {
  const resolved = resolveBatchTryOnPresetSelection(selection)
  const summary = summarizeBatchTryOnPresets(resolved)
  const backgroundConflict = selection.backgroundStyle === 'keep-original'
    && selection.backgroundAdaptationMode !== 'keep-unchanged'

  const update = (field: keyof BatchTryOnPresetSelection, value: string) => {
    const next = resolveBatchTryOnPresetSelection({ ...selection, [field]: value || undefined })
    onChange(next)
  }

  return (
    <section className="mt-4 rounded-2xl border border-violet-200 bg-violet-50/40 p-4 dark:border-violet-500/20 dark:bg-violet-500/5">
      <div>
        <h3 className="text-sm font-bold text-gray-900 dark:text-white">提示词预设</h3>
        <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">系统约束优先级最高；每类单选，预设会在自定义要求之前拼接。</p>
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {FIELDS.map(({ category, field, label, optional }) => {
          const selected = findBatchTryOnPreset(category, resolved[field])
          return <label key={category} className="min-w-0">
            <span className="mb-1 block text-xs font-semibold text-gray-600 dark:text-gray-300">{label}</span>
            <select
              value={resolved[field] || ''}
              disabled={disabled || (category === 'background_adaptation_mode' && resolved.backgroundStyle === 'keep-original')}
              onChange={(event) => update(field, event.target.value)}
              className="h-10 w-full rounded-xl border border-violet-200 bg-white px-3 text-xs font-semibold text-gray-800 outline-none focus:border-violet-400 disabled:opacity-60 dark:border-violet-500/20 dark:bg-gray-950 dark:text-gray-100"
            >
              {optional && <option value="">不指定</option>}
              {presetsForCategory(category).map((preset) => <option key={preset.id} value={preset.code}>{preset.name}</option>)}
            </select>
            <span className="mt-1.5 block min-h-8 text-[11px] leading-relaxed text-gray-500 dark:text-gray-400">{selected?.description || '不额外限定该维度。'}</span>
          </label>
        })}
      </div>
      {backgroundConflict && <div className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:bg-amber-500/10 dark:text-amber-200">已按优先级处理冲突：“保持原背景不变”优先，背景适配已自动调整为“背景保持不变”。</div>}
      <div className="mt-3 rounded-xl border border-violet-100 bg-white/80 px-3 py-2.5 text-xs text-gray-600 dark:border-violet-500/10 dark:bg-gray-950/70 dark:text-gray-300">
        <span className="font-semibold">最终预设摘要：</span>{summary || '未选择预设'}
      </div>
    </section>
  )
}
