import AuthenticatedImage from '../category-listing/AuthenticatedImage'
import type { AIModelPreset, AttachmentCreativeContext, ThemePreset, VisualPreset } from '../../lib/creativePresetApi'

const card = 'rounded-2xl border p-4 text-left transition'

export default function AttachmentCreativeContextPanel({
  context, visuals, themes, models, supportsModel, busy, onChange,
}: {
  context: AttachmentCreativeContext
  visuals: VisualPreset[]
  themes: ThemePreset[]
  models: AIModelPreset[]
  supportsModel: boolean
  busy: boolean
  onChange: (value: {
    visualPresetId: string
    themePresetId: string | null
    modelSelectionMode: 'recommended' | 'selected' | 'none'
    modelIdentityIds: string[]
  }) => void
}) {
  const selectedIds = context.selected_models.map((item) => item.identity_version_id)
  const submit = (patch: Partial<{
    visualPresetId: string
    themePresetId: string | null
    modelSelectionMode: 'recommended' | 'selected' | 'none'
    modelIdentityIds: string[]
  }>) => onChange({
    visualPresetId: patch.visualPresetId ?? context.visual_preset.id,
    themePresetId: patch.themePresetId === undefined ? context.theme_preset?.id || null : patch.themePresetId,
    modelSelectionMode: patch.modelSelectionMode ?? context.model_selection_mode,
    modelIdentityIds: patch.modelIdentityIds ?? (context.model_selection_mode === 'selected' ? selectedIds : []),
  })

  return <section className="rounded-2xl border border-blue-100 bg-gradient-to-b from-white to-blue-50/30 p-5 shadow-sm dark:border-blue-500/15 dark:from-gray-900 dark:to-blue-950/10">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><h2 className="font-semibold text-gray-950 dark:text-white">创意方向</h2><p className="mt-1 text-xs text-gray-500">先选公司视觉模板；主题和AI模特为可选叠加，不需要运营自己从零写整套Prompt。</p></div>
      {context.planning_stale && <span className="rounded-full bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-700">设置已变化 · 请重新策划</span>}
    </div>

    <div className="mt-5">
      <div className="mb-3 flex items-center justify-between"><h3 className="text-sm font-semibold text-gray-800 dark:text-gray-100">整套视觉模板</h3><span className="text-xs text-gray-400">必选</span></div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {visuals.map((item) => {
          const active = context.visual_preset.id === item.id
          return <button key={item.id} disabled={busy} type="button" onClick={() => submit({ visualPresetId: item.id })} className={`${card} ${active ? 'border-blue-500 bg-blue-50 ring-1 ring-blue-200 dark:bg-blue-500/10' : 'border-gray-200 bg-white hover:border-blue-300 dark:border-white/[0.08] dark:bg-gray-950'}`}>
            <div className="flex items-center justify-between gap-2"><strong className="text-sm text-gray-950 dark:text-white">{item.name}</strong>{item.is_default && <span className="rounded-full bg-blue-100 px-2 py-0.5 text-[10px] font-semibold text-blue-700">默认</span>}</div>
            <p className="mt-2 text-xs leading-5 text-gray-500">{item.short_description}</p>
          </button>
        })}
      </div>
    </div>

    <div className={`mt-5 grid gap-5 ${supportsModel ? 'xl:grid-cols-[minmax(220px,0.7fr)_minmax(0,1.3fr)]' : ''}`}>
      <div>
        <label className="text-sm font-semibold text-gray-800 dark:text-gray-100" htmlFor="attachment-theme">主题模板 <span className="font-normal text-gray-400">可选</span></label>
        <select id="attachment-theme" disabled={busy} value={context.theme_preset?.id || ''} onChange={(event) => submit({ themePresetId: event.target.value || null })} className="mt-3 w-full rounded-xl border border-gray-200 bg-white px-3 py-2.5 text-sm dark:border-white/[0.1] dark:bg-gray-950">
          <option value="">无主题</option>
          {themes.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.short_description}</option>)}
        </select>
        <p className="mt-2 text-xs leading-5 text-gray-500">主题只改变场景氛围，不会覆盖商品真实颜色、号码、Logo与定制内容。</p>
      </div>

      {supportsModel && <div>
        <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-semibold text-gray-800 dark:text-gray-100">AI模特</h3><div className="flex rounded-xl bg-gray-100 p-1 text-xs dark:bg-white/[0.05]">{([
          ['recommended', 'AI推荐'], ['selected', '手动选择'], ['none', '不使用'],
        ] as const).map(([value, label]) => <button key={value} type="button" disabled={busy || (value === 'selected' && !models.length)} onClick={() => submit({ modelSelectionMode: value, modelIdentityIds: value === 'selected' ? (models[0]?.current_identity_version_id ? [models[0].current_identity_version_id] : []) : [] })} className={`rounded-lg px-3 py-1.5 font-semibold ${context.model_selection_mode === value ? 'bg-white text-blue-700 shadow-sm dark:bg-gray-800' : 'text-gray-500'}`}>{label}</button>)}</div></div>
        {context.model_selection_mode === 'recommended' && <div className="mt-3 flex flex-wrap gap-2">{context.selected_models.length ? context.selected_models.map((item) => <span key={item.identity_version_id} className="rounded-full bg-violet-50 px-3 py-1 text-xs font-semibold text-violet-700">{item.model.display_name} · {item.model.short_description}</span>) : <span className="text-xs text-gray-500">当前还没有已发布模特，策划会先按无固定身份继续；管理员发布后可重新选择。</span>}</div>}
        {context.model_selection_mode === 'none' && <p className="mt-3 text-xs text-gray-500">不固定人物身份，场景图由图片模型按策划生成合适人物。</p>}
        {context.model_selection_mode === 'selected' && <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">{models.map((item) => {
          const identityId = item.current_identity_version_id
          const active = Boolean(identityId && selectedIds.includes(identityId))
          return <button key={item.id} type="button" disabled={busy || !identityId} onClick={() => {
            if (!identityId) return
            const next = active ? selectedIds.filter((id) => id !== identityId) : [...selectedIds, identityId].slice(0, 3)
            if (next.length) submit({ modelSelectionMode: 'selected', modelIdentityIds: next })
          }} className={`${card} flex items-center gap-3 ${active ? 'border-violet-500 bg-violet-50 dark:bg-violet-500/10' : 'border-gray-200 bg-white dark:border-white/[0.08] dark:bg-gray-950'}`}>
            {item.cover_asset_id ? <AuthenticatedImage url={`/api/v1/assets/${item.cover_asset_id}/content`} alt={item.display_name} className="h-12 w-12 rounded-xl object-cover" placeholderClassName="h-12 w-12 rounded-xl" /> : <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-gray-100 text-lg">👤</div>}
            <div className="min-w-0"><div className="truncate text-sm font-semibold text-gray-950 dark:text-white">{item.display_name}</div><div className="mt-1 truncate text-[11px] text-gray-500">{item.gender_presentation} · {item.age_range} · {item.short_description}</div></div>
          </button>
        })}</div>}
      </div>}
    </div>
  </section>
}
