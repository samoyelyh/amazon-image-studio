import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import AuthenticatedImage from '../components/category-listing/AuthenticatedImage'
import { getAsset, uploadAsset, type Asset } from '../lib/contentApi'
import {
  buildFreeVariationPrompt,
  createFreeVariationProject,
  generateFreeVariations,
  getFreeVariationProject,
  getFreeVariationRecommendations,
  getImagePromptItem,
  listProductCategories,
  optimizeImagePrompt,
  updateFreeVariationProject,
  type FreeVariationContext,
  type FreeVariationRecommendation,
  type ProductCategory,
} from '../lib/listingWorkflowApi'
import {
  freeVariationTemplateCategoryLabels,
  freeVariationTemplates,
  renderFreeVariationTemplate,
  type FreeVariationTemplate,
  type FreeVariationTemplateCategory,
} from '../lib/freeVariationTemplates'
import { randomUuid } from '../lib/randomUuid'
import { useImagePaste } from '../hooks/useImagePaste'
import { useStore } from '../store'

const panel = 'rounded-2xl border border-gray-200 bg-white p-5 shadow-sm dark:border-white/[0.08] dark:bg-gray-900'
const button = 'rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm font-semibold text-gray-700 disabled:cursor-not-allowed disabled:opacity-50 dark:border-white/[0.1] dark:bg-gray-950 dark:text-gray-200'
const primary = 'rounded-xl bg-violet-600 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50'
const field = 'w-full rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm dark:border-white/[0.1] dark:bg-gray-950 dark:text-white'
const FAVORITES_KEY = 'free-variation-template-favorites-v1'
const DEFAULT_PROMPT = '保持参考图片中的主体身份和产品核心视觉细节不变，生成一张自然、真实、适合电商展示的裂变图片。'

type InsertMode = 'insert' | 'append' | 'replace'

function errorText(error: unknown) {
  return error instanceof Error ? error.message : '请求失败，请稍后重试'
}

function readFavorites() {
  try {
    const parsed = JSON.parse(localStorage.getItem(FAVORITES_KEY) || '[]')
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === 'string') : []
  } catch {
    return []
  }
}

export default function SmartImageVariationHubPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const showToast = useStore((state) => state.showToast)
  const promptRef = useRef<HTMLTextAreaElement | null>(null)
  const [context, setContext] = useState<FreeVariationContext | null>(null)
  const [assets, setAssets] = useState<Asset[]>([])
  const [categories, setCategories] = useState<ProductCategory[]>([])
  const [categoryId, setCategoryId] = useState('')
  const [recommendation, setRecommendation] = useState<FreeVariationRecommendation | null>(null)
  const [chinesePrompt, setChinesePrompt] = useState('')
  const [finalEnglishPrompt, setFinalEnglishPrompt] = useState('')
  const [optimizedChinesePrompt, setOptimizedChinesePrompt] = useState('')
  const [templateFragments, setTemplateFragments] = useState<string[]>([])
  const [insertMode, setInsertMode] = useState<InsertMode>('append')
  const [activeVariable, setActiveVariable] = useState<FreeVariationTemplate | null>(null)
  const [variableValue, setVariableValue] = useState('')
  const [favorites, setFavorites] = useState<string[]>(readFavorites)
  const [count, setCount] = useState(1)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [dragging, setDragging] = useState(false)

  const projectId = searchParams.get('project') || ''
  const sourceSessionId = searchParams.get('sourceSession') || ''
  const sourceAssetId = searchParams.get('sourceAsset') || ''

  const loadContext = async (value: FreeVariationContext) => {
    setContext(value)
    setChinesePrompt(value.chinese_prompt || '')
    setFinalEnglishPrompt(value.final_english_prompt || '')
    setOptimizedChinesePrompt(value.prompt_status === 'optimized' || value.prompt_status === 'manually_edited' ? value.chinese_prompt : '')
    setTemplateFragments(value.template_fragments || [])
    setCategoryId(value.selected_category_id || '')
    const loaded = await Promise.all(value.asset_ids.map((id) => getAsset(id).catch(() => null)))
    setAssets(loaded.filter((item): item is Asset => Boolean(item)))
  }

  useEffect(() => {
    let active = true
    void listProductCategories().then((items) => { if (active) setCategories(items) })
      .catch((reason) => { if (active) setError(errorText(reason)) })
    return () => { active = false }
  }, [])

  useEffect(() => {
    let active = true
    if (projectId) {
      setBusy('loading')
      void getFreeVariationProject(projectId).then(async (value) => {
        if (active) await loadContext(value)
      })
        .catch((reason) => { if (active) setError(errorText(reason)) })
        .finally(() => { if (active) setBusy('') })
    } else if (sourceSessionId) {
      setBusy('loading')
      void createFreeVariationProject({
        source_session_id: sourceSessionId,
        asset_ids: sourceAssetId ? [sourceAssetId] : undefined,
        primary_asset_id: sourceAssetId || undefined,
      }).then(async (value) => {
        if (!active) return
        await loadContext(value)
        navigate(`/workspaces/listing/variations?project=${value.project_id}`, { replace: true })
      }).catch((reason) => { if (active) setError(errorText(reason)) })
        .finally(() => { if (active) setBusy('') })
    }
    return () => { active = false }
  }, [projectId, sourceSessionId, sourceAssetId, navigate])

  useEffect(() => {
    let active = true
    setRecommendation(null)
    void getFreeVariationRecommendations(categoryId || undefined).then((value) => {
      if (active) setRecommendation(value)
    }).catch((reason) => {
      if (active) setError(errorText(reason))
    })
    return () => { active = false }
  }, [categoryId])

  const isOptimized = Boolean(chinesePrompt.trim()) && optimizedChinesePrompt === chinesePrompt && Boolean(finalEnglishPrompt.trim())
  const favoriteTemplates = useMemo(() => freeVariationTemplates.filter((item) => favorites.includes(item.id)), [favorites])

  const persistContext = async (nextAssets: Asset[], primaryId: string) => {
    if (!nextAssets.length) return null
    const value = context
      ? await updateFreeVariationProject(context.project_id, { asset_ids: nextAssets.map((item) => item.id), primary_asset_id: primaryId })
      : await createFreeVariationProject({ asset_ids: nextAssets.map((item) => item.id), primary_asset_id: primaryId })
    setContext(value)
    if (!context) navigate(`/workspaces/listing/variations?project=${value.project_id}`, { replace: true })
    return value
  }

  const uploadFiles = async (files: FileList | File[]) => {
    const incoming = Array.from(files).filter((file) => file.type.startsWith('image/')).slice(0, Math.max(0, 10 - assets.length))
    if (!incoming.length) return
    setBusy('upload'); setError('')
    try {
      const uploaded = await Promise.all(incoming.map((file) => uploadAsset(file, 'temporary')))
      const next = [...assets, ...uploaded]
      const primaryId = context?.primary_asset_id && next.some((item) => item.id === context.primary_asset_id)
        ? context.primary_asset_id : next[0].id
      setAssets(next)
      await persistContext(next, primaryId)
      showToast(`已上传 ${uploaded.length} 张参考图片`, 'success')
    } catch (reason) {
      setError(errorText(reason))
    } finally {
      setBusy('')
    }
  }

  const referencePasteZoneProps = useImagePaste({
    disabled: assets.length >= 10 || busy === 'upload',
    maxFiles: Math.max(0, 10 - assets.length),
    onPasteFiles: uploadFiles,
  })

  const removeReference = async (asset: Asset) => {
    if (assets.length <= 1) { showToast('自由裂变至少需要保留一张参考图片', 'error'); return }
    setBusy(`remove:${asset.id}`)
    try {
      const next = assets.filter((item) => item.id !== asset.id)
      const primaryId = context?.primary_asset_id === asset.id ? next[0].id : (context?.primary_asset_id || next[0].id)
      await persistContext(next, primaryId)
      setAssets(next)
    } catch (reason) { setError(errorText(reason)) } finally { setBusy('') }
  }

  const setPrimary = async (assetId: string) => {
    if (!context || context.primary_asset_id === assetId) return
    setBusy(`primary:${assetId}`)
    try {
      const value = await updateFreeVariationProject(context.project_id, { asset_ids: assets.map((item) => item.id), primary_asset_id: assetId })
      setContext(value)
    } catch (reason) { setError(errorText(reason)) } finally { setBusy('') }
  }

  const replacePrompt = (next: string, fragment?: string) => {
    setChinesePrompt(next)
    setFinalEnglishPrompt('')
    setOptimizedChinesePrompt('')
    if (fragment) setTemplateFragments((current) => [...current, fragment].slice(-50))
  }

  const applyText = (text: string) => {
    const area = promptRef.current
    const current = chinesePrompt
    const start = area?.selectionStart ?? current.length
    const end = area?.selectionEnd ?? start
    let next = current
    if (insertMode === 'append') next = [current.trim(), text].filter(Boolean).join('\n')
    else if (insertMode === 'insert') next = `${current.slice(0, start)}${text}${current.slice(end)}`
    else {
      const paragraphStart = current.lastIndexOf('\n', Math.max(0, start - 1)) + 1
      const paragraphEndIndex = current.indexOf('\n', end)
      const paragraphEnd = paragraphEndIndex < 0 ? current.length : paragraphEndIndex
      next = `${current.slice(0, paragraphStart)}${text}${current.slice(paragraphEnd)}`
    }
    replacePrompt(next, text)
    window.setTimeout(() => promptRef.current?.focus(), 0)
  }

  const chooseTemplate = (template: FreeVariationTemplate) => {
    if (template.variable) { setActiveVariable(template); setVariableValue(template.variable.suggestions[0] || ''); return }
    applyText(template.text)
  }

  const applyVariableTemplate = () => {
    if (!activeVariable || !variableValue.trim()) return
    applyText(renderFreeVariationTemplate(activeVariable, variableValue))
    setActiveVariable(null); setVariableValue('')
  }

  const toggleFavorite = (templateId: string) => {
    setFavorites((current) => {
      const next = current.includes(templateId) ? current.filter((id) => id !== templateId) : [...current, templateId]
      localStorage.setItem(FAVORITES_KEY, JSON.stringify(next))
      return next
    })
  }

  const optimize = async () => {
    if (!context || !assets.length || !chinesePrompt.trim()) return
    setBusy('optimize'); setError('')
    try {
      const built = await buildFreeVariationPrompt(context.project_id, {
        chinese_prompt: chinesePrompt.trim(),
        selected_category_id: categoryId || undefined,
        template_fragments: templateFragments,
      })
      let item = await optimizeImagePrompt({
        project_type: 'listing_image', project_id: context.project_id, session_id: context.session_id,
        prompt_item_id: built.item_code, category_id: context.category_id, image_type: built.image_type,
        original_english_prompt: built.base_prompt, chinese_editing_instruction: chinesePrompt.trim(),
        optimized_english_prompt: built.optimized_english_prompt,
        idempotency_key: `free-variation-optimize:${randomUuid()}`,
      })
      while (item.status === 'optimizing') {
        await new Promise((resolve) => window.setTimeout(resolve, 1200))
        item = await getImagePromptItem(item.id)
      }
      if (item.status !== 'optimized' && item.status !== 'manually_edited') throw new Error(item.error_message || 'AI优化英文提示词失败')
      setFinalEnglishPrompt(item.optimized_english_prompt)
      setOptimizedChinesePrompt(chinesePrompt)
      setContext((current) => current ? { ...current, chinese_prompt: chinesePrompt, final_english_prompt: item.optimized_english_prompt, prompt_item_id: item.id, prompt_status: item.status, selected_category_id: categoryId || null, template_fragments: templateFragments } : current)
      showToast('英文图片提示词已完成AI优化', 'success')
    } catch (reason) { setError(errorText(reason)) } finally { setBusy('') }
  }

  const generate = async () => {
    if (!context || !isOptimized) return
    setBusy('generate'); setError('')
    try {
      const response = await generateFreeVariations(context.project_id, {
        count, idempotency_key: `free-variation:${randomUuid()}`, concurrency: Math.min(3, count),
        size: '2048x2048', aspect_ratio: '1:1', requested_width: 2048, requested_height: 2048,
        quality: 'high', output_format: 'png',
      })
      navigate(`/listing-image-workbench/${context.session_id}?group=${response.task_group_id}&source=variation`)
    } catch (reason) { setError(errorText(reason)) } finally { setBusy('') }
  }

  const templateSection = (category: FreeVariationTemplateCategory, items = freeVariationTemplates.filter((item) => item.category === category)) => <details className="rounded-xl border border-gray-200 p-3 dark:border-white/[0.08]" open={category === 'preserve' || category === 'replace'}><summary className="cursor-pointer text-sm font-bold dark:text-white">{freeVariationTemplateCategoryLabels[category]} <span className="font-normal text-gray-400">({items.length})</span></summary><div className="mt-3 flex flex-wrap gap-2">{items.map((template) => <span key={template.id} className="inline-flex overflow-hidden rounded-lg border border-gray-200 bg-white dark:border-white/[0.1] dark:bg-gray-950"><button type="button" className="px-3 py-2 text-xs text-gray-700 hover:bg-violet-50 hover:text-violet-700 dark:text-gray-200" onClick={() => chooseTemplate(template)}>{template.label}{template.variable ? '…' : ''}</button><button type="button" title="收藏模板" className={`border-l px-2 text-sm ${favorites.includes(template.id) ? 'text-amber-500' : 'text-gray-300'}`} onClick={() => toggleFavorite(template.id)}>★</button></span>)}</div></details>

  return <div className="space-y-5 pb-12 pt-6">
    <header className="overflow-hidden rounded-2xl bg-gradient-to-r from-violet-600 to-indigo-600 p-6 text-white shadow-sm"><div className="text-xs font-semibold uppercase tracking-[0.22em] text-violet-100">自由输入优先</div><h1 className="mt-2 text-2xl font-bold">自由图片裂变工作台</h1><p className="mt-2 max-w-3xl text-sm text-violet-50">上传图片、直接输入中文要求、AI重构英文提示词并生成。品类与Skill仅提供可忽略的推荐，不会锁定流程。</p></header>

    {error && <div className="rounded-xl bg-red-50 p-4 text-sm text-red-700">{error}</div>}
    {busy === 'loading' && <div className={panel}>正在恢复自由裂变项目…</div>}

    <section {...referencePasteZoneProps} className={`${panel} outline-none focus:ring-2 focus:ring-violet-500/20`}><div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="font-bold dark:text-white">1. 上传参考图片</h2><p className="mt-1 text-xs text-gray-500">支持1–10张；可设置主图、预览、删除或继续追加。点击本卡片后可 Ctrl/⌘+V 粘贴，图片仅作为当前裂变输入。</p></div><span className="text-xs text-gray-500">{assets.length}/10</span></div>
      <label onDragEnter={(event) => { event.preventDefault(); setDragging(true) }} onDragOver={(event) => event.preventDefault()} onDragLeave={() => setDragging(false)} onDrop={(event) => { event.preventDefault(); setDragging(false); void uploadFiles(event.dataTransfer.files) }} className={`mt-4 flex cursor-pointer items-center justify-center rounded-xl border border-dashed p-6 text-center text-sm font-semibold ${dragging ? 'border-violet-500 bg-violet-100 text-violet-800' : 'border-violet-300 bg-violet-50/60 text-violet-700'}`}><span>{busy === 'upload' ? '正在上传…' : '点击选择、拖拽，或 Ctrl/⌘+V 粘贴图片'}</span><input className="hidden" type="file" accept="image/*" multiple onChange={(event) => { void uploadFiles(event.target.files || []); event.currentTarget.value = '' }} /></label>
      {assets.length > 0 && <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">{assets.map((asset) => <article key={asset.id} className={`overflow-hidden rounded-xl border ${context?.primary_asset_id === asset.id ? 'border-violet-500 ring-2 ring-violet-100' : 'border-gray-200'}`}><div className="relative"><AuthenticatedImage url={asset.url} alt={asset.filename} className="aspect-square w-full bg-gray-50 object-contain" placeholderClassName="aspect-square" /><span className="absolute left-2 top-2 rounded bg-black/60 px-2 py-1 text-[10px] text-white">{context?.primary_asset_id === asset.id ? '主图' : '参考图'}</span></div><div className="truncate px-2 pt-2 text-[11px]">{asset.filename}</div><div className="grid grid-cols-2 gap-1 p-2"><button className="rounded bg-violet-50 px-1 py-1 text-[10px] font-semibold text-violet-700 disabled:opacity-50" disabled={context?.primary_asset_id === asset.id || Boolean(busy)} onClick={() => void setPrimary(asset.id)}>设为主图</button><button className="rounded bg-red-50 px-1 py-1 text-[10px] font-semibold text-red-600 disabled:opacity-50" disabled={Boolean(busy)} onClick={() => void removeReference(asset)}>删除</button></div></article>)}</div>}
    </section>

    <div className="grid gap-5 xl:grid-cols-[minmax(0,1.6fr)_minmax(320px,0.8fr)]"><div className="space-y-5">
      <section className={panel}><div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="font-bold dark:text-white">2. 输入中文裂变要求</h2><p className="mt-1 text-xs text-gray-500">中文是主输入。修改后需要重新执行AI优化，旧英文提示词不会被误用。</p></div><div className="flex gap-2"><button className={button} onClick={() => replacePrompt('')}>清空</button><button className={button} onClick={() => replacePrompt(DEFAULT_PROMPT)}>恢复默认模板</button></div></div><textarea ref={promptRef} aria-label="中文裂变要求" className={`${field} mt-4 min-h-44 resize-y text-base leading-7`} value={chinesePrompt} placeholder="例如：保持人物不变，把背景改成夜晚的橄榄球场；保持衣服图案和号码不变。" onChange={(event) => replacePrompt(event.target.value)} />
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3"><div className="flex items-center gap-2 text-xs text-gray-500"><span>模板点击方式：</span>{([['insert', '插入到光标'], ['append', '追加到末尾'], ['replace', '替换当前段']] as const).map(([value, label]) => <button key={value} className={`rounded-lg px-2 py-1 ${insertMode === value ? 'bg-violet-600 text-white' : 'bg-gray-100 text-gray-600'}`} onClick={() => setInsertMode(value)}>{label}</button>)}</div><span className={`text-xs font-semibold ${isOptimized ? 'text-emerald-600' : chinesePrompt.trim() ? 'text-amber-600' : 'text-gray-400'}`}>{isOptimized ? '英文提示词已同步' : chinesePrompt.trim() ? '需要AI优化英文提示词' : '请先输入要求'}</span></div>
      </section>

      <section className={panel}><div className="flex items-start justify-between gap-3"><div><h2 className="font-bold dark:text-white">3. 提示词快捷模板</h2><p className="mt-1 text-xs text-gray-500">模板只补全文字，不会自动提交生成。星标模板会保存在当前浏览器。</p></div></div>{favoriteTemplates.length > 0 && <div className="mt-4 rounded-xl bg-amber-50 p-3"><div className="text-xs font-bold text-amber-800">★ 收藏模板</div><div className="mt-2 flex flex-wrap gap-2">{favoriteTemplates.map((template) => <button key={template.id} className="rounded-lg bg-white px-3 py-2 text-xs text-amber-800 shadow-sm" onClick={() => chooseTemplate(template)}>{template.label}</button>)}</div></div>}
        {activeVariable && <div className="mt-4 rounded-xl border border-violet-200 bg-violet-50 p-4"><div className="font-bold text-violet-900">{activeVariable.label}</div><label className="mt-3 block text-xs font-semibold text-violet-800">{activeVariable.variable?.label}<input autoFocus className={`${field} mt-1`} value={variableValue} onChange={(event) => setVariableValue(event.target.value)} /></label><div className="mt-2 flex flex-wrap gap-2">{activeVariable.variable?.suggestions.map((value) => <button key={value} className={`rounded-lg px-2 py-1 text-xs ${variableValue === value ? 'bg-violet-600 text-white' : 'bg-white text-violet-700'}`} onClick={() => setVariableValue(value)}>{value}</button>)}</div><div className="mt-3 flex gap-2"><button className={primary} disabled={!variableValue.trim()} onClick={applyVariableTemplate}>应用模板</button><button className={button} onClick={() => setActiveVariable(null)}>取消</button></div></div>}
        <div className="mt-4 space-y-3">{(['preserve', 'replace', 'scene', 'composition', 'style'] as FreeVariationTemplateCategory[]).map((category) => <div key={category}>{templateSection(category)}</div>)}</div>
      </section>

      <section className={panel}><div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="font-bold dark:text-white">4. AI优化英文提示词</h2><p className="mt-1 text-xs text-gray-500">AI会结合参考图和中文修改指令重构完整英文提示词，不做机械翻译。</p></div><button className={primary} disabled={!context || !assets.length || !chinesePrompt.trim() || Boolean(busy)} onClick={() => void optimize()}>{busy === 'optimize' ? '正在AI优化…' : 'AI优化英文提示词'}</button></div>{finalEnglishPrompt ? <div className="mt-4 rounded-xl bg-gray-950 p-4 text-sm leading-6 text-gray-100"><div className="mb-2 text-xs font-bold text-violet-300">最终英文提示词</div><p className="whitespace-pre-wrap">{finalEnglishPrompt}</p></div> : <div className="mt-4 rounded-xl bg-gray-50 p-5 text-center text-sm text-gray-500 dark:bg-white/[0.03]">完成AI优化后在这里查看英文提示词</div>}
        <div className="mt-5 flex flex-wrap items-center justify-between gap-4 border-t border-gray-100 pt-4 dark:border-white/[0.06]"><label className="text-sm font-semibold dark:text-white">生成数量<select aria-label="生成数量" className="ml-2 rounded-lg border border-gray-200 bg-white px-3 py-2 dark:border-white/[0.1] dark:bg-gray-950" value={count} onChange={(event) => setCount(Number(event.target.value))}>{[1, 2, 3, 4].map((value) => <option value={value} key={value}>{value}张</option>)}</select></label><button className={primary} disabled={!context || !isOptimized || Boolean(busy)} onClick={() => void generate()}>{busy === 'generate' ? '正在创建任务组…' : `开始裂变生成（${count}张）`}</button></div>
      </section>
    </div>

      <aside className="space-y-5"><section className={panel}><div className="inline-flex rounded-full bg-violet-50 px-3 py-1 text-xs font-bold text-violet-700">可选辅助</div><h2 className="mt-3 font-bold dark:text-white">品类与Skill推荐</h2><p className="mt-1 text-xs leading-5 text-gray-500">不选择品类也能完成全部自由裂变流程。选择后仅显示可插入的推荐。</p><select aria-label="辅助品类" className={`${field} mt-4`} value={categoryId} onChange={(event) => { setCategoryId(event.target.value); setOptimizedChinesePrompt(''); setFinalEnglishPrompt('') }}><option value="">不使用品类Skill</option>{categories.map((category) => <option value={category.id} key={category.id}>{category.category_name}</option>)}</select>
        {categoryId && recommendation?.available && <div className="mt-4"><div className="rounded-xl bg-emerald-50 p-3 text-sm text-emerald-800"><div className="font-bold">{recommendation.category_name}</div><div className="mt-1 text-xs">{recommendation.skill_name} · V{recommendation.skill_version_number}</div></div><div className="mt-4 space-y-3">{recommendation.directions.map((direction) => <details key={direction.code} className="rounded-xl border border-gray-200 p-3"><summary className="cursor-pointer text-sm font-bold">{direction.name}</summary><div className="mt-2 text-xs text-gray-500"><strong>保持：</strong>{direction.preserve_elements.join('、') || '按用户要求'}<br /><strong>可变：</strong>{direction.allowed_changes.join('、') || '按用户要求'}</div></details>)}</div><div className="mt-4 space-y-2"><div className="text-xs font-bold text-gray-500">推荐模板（点击插入）</div>{recommendation.templates.map((template) => <button key={template.id} className="w-full rounded-xl border border-violet-100 bg-violet-50 p-3 text-left text-xs text-violet-800 hover:border-violet-300" onClick={() => applyText(template.text)}><span className="block font-bold">{template.name}</span><span className="mt-1 block leading-5">{template.text}</span></button>)}</div></div>}
        {categoryId && recommendation && !recommendation.available && <div className="mt-4 rounded-xl bg-amber-50 p-3 text-sm text-amber-700">当前品类没有可用的已发布Skill推荐，但不影响自由输入和生成。</div>}
        {!categoryId && <div className="mt-4 rounded-xl border border-dashed border-gray-200 p-4 text-center text-xs text-gray-500">当前为纯自由模式，不读取任何品类Skill。</div>}
      </section><section className={panel}><h3 className="font-bold dark:text-white">当前任务摘要</h3><dl className="mt-3 space-y-2 text-xs"><div className="flex justify-between"><dt className="text-gray-500">参考图片</dt><dd className="font-semibold">{assets.length}张</dd></div><div className="flex justify-between"><dt className="text-gray-500">提示词模式</dt><dd className="font-semibold">自由中文输入</dd></div><div className="flex justify-between"><dt className="text-gray-500">Skill</dt><dd className="max-w-44 truncate font-semibold">{recommendation?.available ? `${recommendation.skill_name}（辅助）` : '未使用'}</dd></div><div className="flex justify-between"><dt className="text-gray-500">生成数量</dt><dd className="font-semibold">{count}张</dd></div></dl></section></aside>
    </div>
  </div>
}
