import { useEffect, useState } from 'react'
import {
  getAttachmentModuleModelContext,
  generatePersonalAIModel,
  getAIModelPreset,
  savePersonalAIModel,
  updateAttachmentModuleModelContext,
  type AIModelPreset,
  type AttachmentModuleModelContext,
} from '../../lib/creativePresetApi'
import { randomUuid } from '../../lib/randomUuid'
import { getAsset, type Asset } from '../../lib/contentApi'
import AuthenticatedImage from '../category-listing/AuthenticatedImage'

interface Props {
  projectId: string
  moduleKey: string
  models: AIModelPreset[]
  busy?: boolean
  onChanged?: () => void
  onError: (message: string) => void
}

const modes: Array<[AttachmentModuleModelContext['selection_mode'], string]> = [
  ['inherit', '继承整套默认'],
  ['recommended', 'AI推荐'],
  ['selected', '从模特库选择'],
  ['none', '不使用模特'],
]

export default function AttachmentModuleModelPanel({ projectId, moduleKey, models, busy = false, onChanged, onError }: Props) {
  const [context, setContext] = useState<AttachmentModuleModelContext | null>(null)
  const [saving, setSaving] = useState(false)
  const [generatorOpen, setGeneratorOpen] = useState(false)
  const [candidate, setCandidate] = useState<AIModelPreset | null>(null)
  const [candidateAsset, setCandidateAsset] = useState<Asset | null>(null)
  const [form, setForm] = useState({ gender: 'male', age: '25-30', body: 'athletic', style: 'sports', personality: 'sunny', expression: 'subtle_smile' })

  useEffect(() => {
    let active = true
    void getAttachmentModuleModelContext(projectId, moduleKey)
      .then((value) => { if (active) setContext(value) })
      .catch((error) => { if (active) onError(error instanceof Error ? error.message : '读取模块模特失败') })
    return () => { active = false }
  }, [projectId, moduleKey])

  const submit = async (mode: AttachmentModuleModelContext['selection_mode'], ids: string[] = []) => {
    setSaving(true)
    try {
      const value = await updateAttachmentModuleModelContext(projectId, moduleKey, {
        selection_mode: mode,
        selected_model_identity_version_ids: mode === 'selected' ? ids : [],
      })
      setContext(value)
      onChanged?.()
    } catch (error) {
      onError(error instanceof Error ? error.message : '保存模块模特失败')
    } finally {
      setSaving(false)
    }
  }

  const selected = new Set(context?.selected_identity_version_ids || [])
  const generate = async () => {
    setSaving(true); setCandidate(null); setCandidateAsset(null)
    try {
      let value = await generatePersonalAIModel({
        idempotency_key: `personal-model:${randomUuid()}`, quick_type: 'structured_quick_model',
        display_name: '我的临时AI模特', gender_presentation: form.gender,
        age_range: form.age as '25-30', body_type: form.body as 'athletic',
        commercial_style: form.style as 'sports', personality: form.personality as 'sunny',
        hair_style: 'natural', expression: form.expression as 'subtle_smile', recommended_usage: ['stadium', 'gift', 'casual'],
      })
      setCandidate(value)
      for (let attempt = 0; attempt < 90 && !value.current_identity?.identity_asset_id && !['FAILED'].includes(value.status); attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 2000))
        value = await getAIModelPreset(value.id); setCandidate(value)
      }
      if (value.current_identity?.identity_asset_id) setCandidateAsset(await getAsset(value.current_identity.identity_asset_id))
    } catch (error) { onError(error instanceof Error ? error.message : '生成AI模特失败') } finally { setSaving(false) }
  }
  return <section className="rounded-xl border border-gray-200 p-4 dark:border-white/[0.08]">
    <div><h3 className="text-sm font-semibold text-gray-900 dark:text-white">当前模块模特</h3><p className="mt-1 text-xs text-gray-500">模块覆盖只影响当前模块；继承时继续使用整套默认模特。</p></div>
    <div className="mt-3 flex flex-wrap gap-2">{modes.map(([value, label]) => <button key={value} type="button" disabled={busy || saving || (value === 'selected' && !models.length)} onClick={() => void submit(value, value === 'selected' && models[0]?.current_identity_version_id ? [models[0].current_identity_version_id] : [])} className={`rounded-lg border px-3 py-2 text-xs font-semibold ${context?.selection_mode === value ? 'border-blue-300 bg-blue-50 text-blue-700' : 'border-gray-200 text-gray-600 dark:border-white/[0.1] dark:text-gray-300'}`}>{label}</button>)}</div>
    <button type="button" disabled={busy || saving} onClick={() => setGeneratorOpen(true)} className="mt-3 rounded-lg border border-violet-200 bg-violet-50 px-3 py-2 text-xs font-semibold text-violet-700">自主生成模特</button>
    {context?.selection_mode === 'selected' && <div className="mt-3 grid gap-2 sm:grid-cols-2">{models.map((model) => {
      const identityId = model.current_identity_version_id
      if (!identityId) return null
      const active = selected.has(identityId)
      return <button key={model.id} type="button" disabled={busy || saving} onClick={() => void submit('selected', [identityId])} className={`rounded-xl border p-3 text-left ${active ? 'border-violet-300 bg-violet-50' : 'border-gray-200 dark:border-white/[0.08]'}`}><div className="text-xs font-semibold text-gray-900 dark:text-white">{model.display_name}</div><div className="mt-1 text-[11px] text-gray-500">{model.short_description}</div></button>
    })}</div>}
    {context && <p className="mt-3 text-[11px] text-gray-400">实际策略：{context.inherited ? '继承整套默认' : context.effective_selection_mode}</p>}
    {generatorOpen && <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/50 p-4" role="dialog" aria-modal="true" aria-label="自主生成AI模特"><div className="w-full max-w-2xl rounded-2xl bg-white p-5 shadow-2xl dark:bg-gray-900">
      <div className="flex items-start justify-between"><div><h3 className="font-semibold text-gray-950 dark:text-white">自主生成AI模特</h3><p className="mt-1 text-xs text-gray-500">使用结构化关键词生成一个候选身份；临时使用不会进入公共模特库。</p></div><button type="button" onClick={() => setGeneratorOpen(false)} className="text-xl text-gray-400">×</button></div>
      <div className="mt-4 grid gap-3 sm:grid-cols-3">{[
        ['gender', '性别呈现', [['male', '男性'], ['female', '女性']]],
        ['age', '年龄', ['18-24', '25-30', '30-39', '40-49', '50+'].map((v) => [v, v])],
        ['body', '体型', ['slim', 'natural', 'fit', 'athletic', 'strong', 'tall'].map((v) => [v, v])],
        ['style', '商业风格', ['amazon_ecommerce', 'sports', 'lifestyle', 'streetwear', 'premium_commercial'].map((v) => [v, v])],
        ['personality', '气质', ['natural', 'sunny', 'mature', 'friendly', 'confident', 'cool', 'energetic', 'premium'].map((v) => [v, v])],
        ['expression', '表情', ['neutral', 'subtle_smile', 'confident', 'relaxed'].map((v) => [v, v])],
      ].map(([key, label, options]) => <label key={String(key)} className="text-xs font-semibold text-gray-600">{String(label)}<select value={form[key as keyof typeof form]} onChange={(event) => setForm((current) => ({ ...current, [String(key)]: event.target.value }))} className="mt-1 w-full rounded-lg border border-gray-200 px-2 py-2 text-sm dark:border-white/[0.1] dark:bg-gray-950">{(options as string[][]).map(([value, copy]) => <option key={value} value={value}>{copy}</option>)}</select></label>)}</div>
      {candidate && <div className="mt-4 rounded-xl bg-gray-50 p-3 dark:bg-white/[0.03]"><div className="text-xs font-semibold">候选状态：{candidate.status}</div>{candidateAsset && <AuthenticatedImage url={candidateAsset.url} alt={candidate.display_name} className="mt-3 max-h-72 w-full rounded-xl object-contain" />}</div>}
      <div className="mt-5 flex flex-wrap justify-end gap-2"><button type="button" disabled={saving} onClick={() => void generate()} className="rounded-lg border border-gray-200 px-3 py-2 text-xs font-semibold">{candidate ? '重新生成' : '生成候选模特'}</button><button type="button" disabled={!candidate?.current_identity_version_id || saving} onClick={() => void submit('selected', [candidate!.current_identity_version_id!]).then(() => setGeneratorOpen(false))} className="rounded-lg bg-blue-600 px-3 py-2 text-xs font-semibold text-white disabled:opacity-40">使用此模特</button><button type="button" disabled={!candidate?.current_identity_version_id || candidate.source_type === 'USER_GENERATED' || saving} onClick={() => void savePersonalAIModel(candidate!.id).then(setCandidate).catch((error) => onError(error instanceof Error ? error.message : '保存个人模特失败'))} className="rounded-lg bg-violet-600 px-3 py-2 text-xs font-semibold text-white disabled:opacity-40">保存到我的模特库</button></div>
    </div></div>}
  </section>
}
