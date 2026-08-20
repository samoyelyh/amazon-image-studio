import { useEffect, useState } from 'react'
import AuthenticatedImage from '../category-listing/AuthenticatedImage'
import { randomUuid } from '../../lib/randomUuid'
import {
  adminConfirmAIModelIdentity,
  adminCreateThemePreset,
  adminCreateVisualPreset,
  adminGenerateAIModelIdentity,
  adminGenerateAIModelReferences,
  adminListAIModelPresets,
  adminListThemePresets,
  adminListVisualPresets,
  adminPublishAIModelIdentity,
  adminUpdateAIModelPreset,
  adminUpdateThemePreset,
  adminUpdateVisualPreset,
  type AIModelPreset,
  type ThemePreset,
  type VisualPreset,
} from '../../lib/creativePresetApi'

const panel = 'rounded-2xl border border-gray-200 bg-white shadow-sm dark:border-white/[0.08] dark:bg-gray-900'
const input = 'w-full rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm dark:border-white/[0.1] dark:bg-gray-950 dark:text-white'
const button = 'rounded-xl border border-gray-200 bg-white px-3 py-2 text-xs font-semibold text-gray-700 disabled:opacity-50 dark:border-white/[0.1] dark:bg-gray-950 dark:text-gray-200'
const primary = 'rounded-xl bg-blue-600 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50'

export default function CreativePresetManagementPanel({ notify }: { notify: (value: string) => void }) {
  const [tab, setTab] = useState<'visual' | 'theme' | 'model'>('visual')
  const [visuals, setVisuals] = useState<VisualPreset[]>([])
  const [themes, setThemes] = useState<ThemePreset[]>([])
  const [models, setModels] = useState<AIModelPreset[]>([])
  const [busy, setBusy] = useState('')
  const [creating, setCreating] = useState(false)
  const [draft, setDraft] = useState({ code: '', name: '', description: '', prompt: '', tags: '' })

  const refresh = async () => {
    const [visualRows, themeRows, modelRows] = await Promise.all([
      adminListVisualPresets(), adminListThemePresets(), adminListAIModelPresets(),
    ])
    setVisuals(visualRows); setThemes(themeRows); setModels(modelRows)
  }
  useEffect(() => { void refresh().catch((error) => notify(error instanceof Error ? error.message : '创意配置加载失败')) }, [notify])
  useEffect(() => {
    if (!models.some((item) => ['GENERATING_IDENTITY', 'GENERATING_REFERENCES'].includes(item.status))) return
    const timer = window.setInterval(() => void adminListAIModelPresets().then(setModels).catch(() => undefined), 4000)
    return () => window.clearInterval(timer)
  }, [models])

  const run = async (key: string, action: () => Promise<unknown>, message: string) => {
    setBusy(key)
    try { await action(); await refresh(); notify(message) }
    catch (error) { notify(error instanceof Error ? error.message : '操作失败') }
    finally { setBusy('') }
  }
  const createPreset = async () => {
    if (tab === 'model') return
    await run('create', () => tab === 'visual'
      ? adminCreateVisualPreset({
        code: draft.code, name: draft.name, short_description: draft.description,
        full_prompt_template: draft.prompt, tags: draft.tags.split(',').map((item) => item.trim()).filter(Boolean),
        category_scope: [], recommended_modules: [], recommended_model_tags: [], sort_order: 100, is_default: false,
      })
      : adminCreateThemePreset({
        code: draft.code, name: draft.name, short_description: draft.description,
        full_prompt_template: draft.prompt, tags: draft.tags.split(',').map((item) => item.trim()).filter(Boolean), sort_order: 100,
      }), tab === 'visual' ? '视觉模板已创建' : '主题模板已创建')
    setCreating(false); setDraft({ code: '', name: '', description: '', prompt: '', tags: '' })
  }

  return <div className="space-y-5">
    <section className={`${panel} p-5`}>
      <div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="font-bold text-gray-950 dark:text-white">AI生图创意配置</h2><p className="mt-1 text-xs text-gray-500">维护运营可选择的视觉、主题与不可变AI模特身份版本。所有图片任务仍通过统一Worker和资源池。</p></div>{tab !== 'model' && <button className={primary} onClick={() => setCreating((value) => !value)}>{creating ? '收起新建' : '新增模板'}</button>}</div>
      <div className="mt-4 flex gap-2">{([['visual', '视觉模板'], ['theme', '主题模板'], ['model', 'AI模特库']] as const).map(([id, label]) => <button key={id} onClick={() => { setTab(id); setCreating(false) }} className={`rounded-xl px-4 py-2 text-sm font-semibold ${tab === id ? 'bg-gray-950 text-white dark:bg-white dark:text-gray-950' : 'bg-gray-100 text-gray-600 dark:bg-white/[0.06] dark:text-gray-300'}`}>{label}</button>)}</div>
    </section>

    {creating && <section className={`${panel} grid gap-3 p-5`}><div className="grid gap-3 sm:grid-cols-2"><input className={input} placeholder="编码，例如 halloween" value={draft.code} onChange={(e) => setDraft((value) => ({ ...value, code: e.target.value }))} /><input className={input} placeholder="显示名称" value={draft.name} onChange={(e) => setDraft((value) => ({ ...value, name: e.target.value }))} /></div><input className={input} placeholder="一句运营说明" value={draft.description} onChange={(e) => setDraft((value) => ({ ...value, description: e.target.value }))} /><input className={input} placeholder="标签，逗号分隔" value={draft.tags} onChange={(e) => setDraft((value) => ({ ...value, tags: e.target.value }))} /><textarea className={`${input} min-h-40`} placeholder="完整 Prompt Template" value={draft.prompt} onChange={(e) => setDraft((value) => ({ ...value, prompt: e.target.value }))} /><div><button className={primary} disabled={busy !== '' || !draft.code || !draft.name || draft.prompt.length < 20} onClick={() => void createPreset()}>保存新模板</button></div></section>}

    {tab === 'visual' && <div className="grid gap-4 xl:grid-cols-2">{visuals.map((item) => <PresetEditor key={item.id} item={item} busy={busy !== ''} onSave={(next) => run(`visual:${item.id}`, () => adminUpdateVisualPreset(item.id, next), '视觉模板已保存为新版本')} />)}</div>}
    {tab === 'theme' && <div className="grid gap-4 xl:grid-cols-2">{themes.map((item) => <PresetEditor key={item.id} item={item} busy={busy !== ''} onSave={(next) => run(`theme:${item.id}`, () => adminUpdateThemePreset(item.id, next), '主题模板已保存为新版本')} />)}</div>}
    {tab === 'model' && <div className="grid gap-4 xl:grid-cols-2">{models.map((item) => <ModelCard key={item.id} item={item} busy={busy !== ''} run={run} />)}</div>}
  </div>
}

function PresetEditor({ item, busy, onSave }: { item: VisualPreset | ThemePreset; busy: boolean; onSave: (value: Record<string, unknown>) => Promise<void> }) {
  const [name, setName] = useState(item.name)
  const [description, setDescription] = useState(item.short_description)
  const [prompt, setPrompt] = useState(item.prompt_template || '')
  return <section className={`${panel} p-5`}><div className="flex items-center justify-between gap-3"><div><span className="font-semibold dark:text-white">{item.name}</span><span className="ml-2 text-xs text-gray-400">V{item.current_version_number} · {item.code}</span></div><span className={`rounded-full px-2 py-1 text-[11px] font-semibold ${item.is_active ? 'bg-emerald-50 text-emerald-700' : 'bg-gray-100 text-gray-500'}`}>{item.is_active ? '启用' : '停用'}</span></div><div className="mt-4 grid gap-3"><input className={input} value={name} onChange={(e) => setName(e.target.value)} /><input className={input} value={description} onChange={(e) => setDescription(e.target.value)} /><textarea className={`${input} min-h-48 leading-6`} value={prompt} onChange={(e) => setPrompt(e.target.value)} /><div className="flex gap-2"><button className={primary} disabled={busy || prompt.length < 20} onClick={() => void onSave({ name, short_description: description, full_prompt_template: prompt, change_summary: '管理后台编辑' })}>保存新版本</button><button className={button} disabled={busy} onClick={() => void onSave({ is_active: !item.is_active })}>{item.is_active ? '停用' : '启用'}</button>{'is_default' in item && !item.is_default && <button className={button} disabled={busy} onClick={() => void onSave({ is_default: true })}>设为默认</button>}</div></div></section>
}

function ModelCard({ item, busy, run }: { item: AIModelPreset; busy: boolean; run: (key: string, action: () => Promise<unknown>, message: string) => Promise<void> }) {
  const identity = item.current_identity
  const progress = identity?.references.length || 0
  return <section className={`${panel} p-5`}>
    <div className="flex gap-4">
      {item.cover_asset_id
        ? <AuthenticatedImage url={`/api/v1/assets/${item.cover_asset_id}/content`} alt={item.display_name} className="h-24 w-20 rounded-xl object-cover" placeholderClassName="h-24 w-20 rounded-xl" />
        : <div className="flex h-24 w-20 items-center justify-center rounded-xl bg-gray-100 text-2xl">👤</div>}
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2"><h3 className="font-semibold dark:text-white">{item.display_name}</h3><span className="rounded-full bg-gray-100 px-2 py-1 text-[10px] font-semibold text-gray-600">{item.status}</span></div>
        <p className="mt-1 text-xs text-gray-500">{item.gender_presentation} · {item.age_range} · {item.body_type}</p>
        <p className="mt-2 text-xs leading-5 text-gray-600 dark:text-gray-300">{item.short_description}</p>
        <div className="mt-2 text-xs text-gray-500">Identity Pack：{progress} / 4{identity ? ` · V${identity.version_number}` : ''}</div>
      </div>
    </div>
    <div className="mt-4 flex flex-wrap gap-2">
      {(!identity || ['FAILED', 'PUBLISHED'].includes(identity.status)) && <button className={primary} disabled={busy} onClick={() => void run(`identity:${item.id}`, () => adminGenerateAIModelIdentity(item.id, `ai-model-identity:${randomUuid()}`), '模特身份生成任务已提交，可以离开页面')}>生成新身份</button>}
      {identity?.status === 'AWAITING_CONFIRMATION' && <button className={primary} disabled={busy} onClick={() => void run(`confirm:${item.id}`, () => adminConfirmAIModelIdentity(item.id, identity.id), '模特身份已确认')}>确认身份</button>}
      {identity && ['CONFIRMED', 'REFERENCES_FAILED'].includes(identity.status) && <button className={primary} disabled={busy} onClick={() => void run(`refs:${item.id}`, () => adminGenerateAIModelReferences(item.id, identity.id, `ai-model-references:${randomUuid()}`), identity.status === 'REFERENCES_FAILED' ? '失败视图已重新提交，已完成视图会保留' : '身份参考组任务已提交')}>{identity.status === 'REFERENCES_FAILED' ? '重试失败视图' : '生成参考组'}</button>}
      {identity?.status === 'REFERENCES_READY' && <button className={primary} disabled={busy} onClick={() => void run(`publish:${item.id}`, () => adminPublishAIModelIdentity(item.id, identity.id), 'AI模特已发布，运营现在可以选择')}>发布</button>}
      <button className={button} disabled={busy} onClick={() => void run(`toggle:${item.id}`, () => adminUpdateAIModelPreset(item.id, { is_active: !item.is_active }), item.is_active ? 'AI模特已停用' : 'AI模特已启用')}>{item.is_active ? '停用' : '启用'}</button>
    </div>
  </section>
}
