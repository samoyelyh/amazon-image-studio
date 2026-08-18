import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { removeAsset, uploadAsset, type Asset } from '../lib/contentApi'
import {
  analyzeCategoryProduct,
  confirmListingWorkflowSession,
  getCategoryRecommendation,
  getBilingualListingOptimization,
  getListingWorkflowSession,
  listProductCategories,
  optimizeBilingualListing,
  startCategoryRecommendation,
  updateListingWorkflowSession,
  type CategoryRecommendation,
  type BilingualListingContent,
  type ListingWorkflowSession,
  type ProductCategory,
} from '../lib/listingWorkflowApi'
import { randomUuid } from '../lib/randomUuid'
import { useImagePaste } from '../hooks/useImagePaste'
import { useStore } from '../store'
import WorkflowSteps from './category-listing/WorkflowSteps'
import AutoSaveIndicator, { type AutoSaveState } from './category-listing/AutoSaveIndicator'

const panel = 'rounded-2xl border border-gray-200 bg-white shadow-sm dark:border-white/[0.08] dark:bg-gray-900'
const field = 'w-full rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm outline-none focus:border-blue-500 dark:border-white/[0.1] dark:bg-gray-950 dark:text-white'
const primary = 'rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50'
const secondary = 'rounded-xl border border-gray-200 bg-white px-4 py-2 text-sm font-semibold text-gray-700 disabled:opacity-50 dark:border-white/[0.1] dark:bg-gray-950 dark:text-gray-200'
const attributeLabels: Record<string, string> = {
  gender: '适用人群', fit: '版型', sleeve_type: '袖型', neck_type: '领型', main_color: '主色', secondary_color: '辅色',
  graphic_elements: '图案元素', number_presence: '是否有号码', name_presence: '是否有名字', fabric_style: '面料感觉',
  style_tags: '风格标签', scene_tags: '可用场景',
}
const listKeys = new Set(['graphic_elements', 'style_tags', 'scene_tags'])

interface Reference { localId: string; file: File; previewUrl: string; asset?: Asset; uploading: boolean; error?: string }
function errorText(error: unknown) { return error instanceof Error ? error.message : '请求失败，请稍后重试' }
function wait(ms: number) { return new Promise((resolve) => window.setTimeout(resolve, ms)) }
function display(value: unknown) { return Array.isArray(value) ? value.join('、') : value == null ? '' : String(value) }
function parseValue(key: string, value: string) { return listKeys.has(key) ? value.split(/[、,，]/).map((item) => item.trim()).filter(Boolean) : value }
function parseConfiguredValue(type: string, value: string) {
  if (['tags', 'multiselect'].includes(type)) return value.split(/[,，\n]/).map((item) => item.trim()).filter(Boolean)
  if (type === 'boolean') return ['true', '1', 'yes', '是'].includes(value.trim().toLowerCase())
  if (type === 'number') return value.trim() === '' ? '' : Number(value)
  return value
}
const emptyListing = (): BilingualListingContent => ({
  title: { en: '', zh: '' },
  bullet_points: Array.from({ length: 5 }, (_, index) => ({ id: `bullet-${index + 1}`, en: '', zh: '' })),
  description: { en: '', zh: '' }, search_terms: { en: [], zh: [] },
  selling_points: { en: '', zh: '' }, usage_scenarios: { en: '', zh: '' },
  customization_notes: { en: '', zh: '' }, cautions: { en: '', zh: '' }, a_plus_copy: {},
})

function BilingualTextCard({ label, en, zh, onEn, onZh, compact = false }: {
  label: string; en: string; zh: string; onEn: (value: string) => void; onZh: (value: string) => void; compact?: boolean
}) {
  return <div className="rounded-xl border border-gray-200 p-4 dark:border-white/[0.08]"><h3 className="mb-3 text-sm font-semibold dark:text-white">{label}</h3><div className="grid gap-3 lg:grid-cols-2"><label className="text-xs font-semibold text-gray-600">英文版 · 用于最终 Listing<textarea className={`${field} mt-1 ${compact ? 'min-h-24' : 'min-h-32'}`} value={en} onChange={(event) => onEn(event.target.value)} /></label><label className="text-xs font-semibold text-gray-600">中文版 · 用于运营理解和审核<textarea className={`${field} mt-1 ${compact ? 'min-h-24' : 'min-h-32'}`} value={zh} onChange={(event) => onZh(event.target.value)} /></label></div></div>
}

export default function CategoryListingWorkflow() {
  const { sessionId } = useParams<{ sessionId?: string }>()
  const navigate = useNavigate()
  const showToast = useStore((state) => state.showToast)
  const mounted = useRef(true)
  const [categories, setCategories] = useState<ProductCategory[]>([])
  const [categorySearch, setCategorySearch] = useState('')
  const [selectedCategoryId, setSelectedCategoryId] = useState('')
  const [references, setReferences] = useState<Reference[]>([])
  const [existingAssetIds, setExistingAssetIds] = useState<string[]>([])
  const [primaryAssetId, setPrimaryAssetId] = useState<string | null>(null)
  const [recommendation, setRecommendation] = useState<CategoryRecommendation | null>(null)
  const [session, setSession] = useState<ListingWorkflowSession | null>(null)
  const [attributes, setAttributes] = useState<Record<string, unknown>>({})
  const [content, setContent] = useState<BilingualListingContent>(emptyListing)
  const [busy, setBusy] = useState('')
  const [saveState, setSaveState] = useState<AutoSaveState>('idle')
  const hydrated = useRef(false)
  const sessionRef = useRef<ListingWorkflowSession | null>(null)
  const stateVersionRef = useRef(0)
  const latestDraftRef = useRef({ attributes: {} as Record<string, unknown>, content: emptyListing() })
  const lastSavedSignature = useRef('')
  const saveTimer = useRef<number | null>(null)
  const saveQueue = useRef<Promise<void>>(Promise.resolve())

  const applySession = (value: ListingWorkflowSession) => {
    hydrated.current = false
    setSession(value); setSelectedCategoryId(value.category_id); setExistingAssetIds(value.source_asset_ids); setPrimaryAssetId(value.primary_asset_id)
    sessionRef.current = value; stateVersionRef.current = value.state_version
    const nextAttributes = value.structured_attributes || {}
    const nextContent = { ...emptyListing(), ...value.listing_content,
      bullet_points: Array.from({ length: 5 }, (_, index) => value.listing_content.bullet_points?.[index] || { id: `bullet-${index + 1}`, en: '', zh: '' }),
    }
    setAttributes(nextAttributes); setContent(nextContent)
    latestDraftRef.current = { attributes: nextAttributes, content: nextContent }
    lastSavedSignature.current = JSON.stringify(latestDraftRef.current)
    setSaveState(value.last_saved_at ? 'saved' : 'idle')
    hydrated.current = true
  }

  const queueDraftSave = () => {
    saveQueue.current = saveQueue.current.then(async () => {
      const currentSession = sessionRef.current
      if (!currentSession) return
      const draft = latestDraftRef.current
      const signature = JSON.stringify(draft)
      if (signature === lastSavedSignature.current) return
      if (mounted.current) setSaveState('saving')
      try {
        const value = await updateListingWorkflowSession(currentSession.id, {
          structured_attributes: draft.attributes, listing_content: draft.content,
          current_step: 2, expected_state_version: stateVersionRef.current,
        })
        stateVersionRef.current = value.state_version
        sessionRef.current = value
        lastSavedSignature.current = signature
        if (mounted.current) {
          setSession(value)
          setSaveState(JSON.stringify(latestDraftRef.current) === signature ? 'saved' : 'dirty')
        }
      } catch (error) {
        if (mounted.current) { setSaveState('failed'); showToast(errorText(error), 'error') }
      }
    })
    return saveQueue.current
  }

  useEffect(() => {
    mounted.current = true
    void listProductCategories().then((items) => { if (!mounted.current) return; setCategories(items); if (!sessionId && items.length === 1) setSelectedCategoryId(items[0].id) }).catch((error) => showToast(errorText(error), 'error'))
    if (sessionId) void getListingWorkflowSession(sessionId).then((value) => { if (mounted.current) applySession(value) }).catch((error) => showToast(errorText(error), 'error'))
    return () => {
      if (saveTimer.current) window.clearTimeout(saveTimer.current)
      if (lastSavedSignature.current !== JSON.stringify(latestDraftRef.current)) void queueDraftSave()
      mounted.current = false
    }
  }, [sessionId, showToast])

  useEffect(() => {
    latestDraftRef.current = { attributes, content }
    if (!hydrated.current || !sessionRef.current) return
    const signature = JSON.stringify(latestDraftRef.current)
    if (signature === lastSavedSignature.current) return
    setSaveState('dirty')
    if (saveTimer.current) window.clearTimeout(saveTimer.current)
    saveTimer.current = window.setTimeout(() => { void queueDraftSave() }, 1000)
    return () => { if (saveTimer.current) window.clearTimeout(saveTimer.current) }
  }, [attributes, content])

  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (lastSavedSignature.current === JSON.stringify(latestDraftRef.current)) return
      event.preventDefault(); event.returnValue = ''
    }
    window.addEventListener('beforeunload', beforeUnload)
    return () => window.removeEventListener('beforeunload', beforeUnload)
  }, [])

  const uploadedIds = references.flatMap((item) => item.asset ? [item.asset.id] : [])
  const allAssetIds = [...existingAssetIds, ...uploadedIds.filter((id) => !existingAssetIds.includes(id))]
  const visibleCategories = categories.filter((item) => !categorySearch.trim() || `${item.category_name} ${item.category_code}`.toLowerCase().includes(categorySearch.trim().toLowerCase()))
  const configuredSchema = ((session?.category_skill_snapshot?.analysis_config as Record<string, unknown> | undefined)?.attribute_schema || []) as Array<Record<string, unknown>>
  const attributeFields = configuredSchema.length
    ? configuredSchema.map((item) => ({ code: String(item.code || ''), name: String(item.name || item.code || ''), type: String(item.type || 'text') })).filter((item) => item.code)
    : Object.entries(attributeLabels).map(([code, name]) => ({ code, name, type: listKeys.has(code) ? 'tags' : 'text' }))
  const listingContent = (): ListingWorkflowSession['listing_content'] => content
  const setLocalized = (key: 'title' | 'description' | 'selling_points' | 'usage_scenarios' | 'customization_notes' | 'cautions', lang: 'en' | 'zh', value: string) =>
    setContent((current) => ({ ...current, [key]: { ...current[key], [lang]: value } }))
  const setBullet = (index: number, lang: 'en' | 'zh', value: string) => setContent((current) => ({
    ...current, bullet_points: current.bullet_points.map((item, itemIndex) => itemIndex === index ? { ...item, [lang]: value } : item),
  }))
  const setTerms = (lang: 'en' | 'zh', value: string) => setContent((current) => ({
    ...current, search_terms: { ...current.search_terms, [lang]: value.split(/[,，\n]/).map((item) => item.trim()).filter(Boolean) },
  }))

  const uploadFiles = async (files: FileList | File[] | null) => {
    if (!files?.length) return
    const candidates = Array.from(files).filter((file) => file.type.startsWith('image/')).slice(0, Math.max(0, 10 - allAssetIds.length))
    const additions = candidates.map((file) => ({ localId: randomUuid(), file, previewUrl: URL.createObjectURL(file), uploading: true }))
    setReferences((items) => [...items, ...additions]); setBusy('upload')
    await Promise.all(additions.map(async (item) => {
      try { const asset = await uploadAsset(item.file, 'product_reference'); if (mounted.current) setReferences((items) => items.map((value) => value.localId === item.localId ? { ...value, asset, uploading: false } : value)) }
      catch (error) { if (mounted.current) setReferences((items) => items.map((value) => value.localId === item.localId ? { ...value, uploading: false, error: errorText(error) } : value)) }
    }))
    setBusy('')
  }

  const productPasteZoneProps = useImagePaste({
    disabled: allAssetIds.length >= 10 || busy === 'upload',
    maxFiles: Math.max(0, 10 - allAssetIds.length),
    onPasteFiles: uploadFiles,
  })

  const removeReference = async (item: Reference) => {
    if (item.asset) await removeAsset(item.asset.id).catch(() => undefined)
    URL.revokeObjectURL(item.previewUrl); setReferences((items) => items.filter((value) => value.localId !== item.localId))
  }

  const recommend = async () => {
    if (!allAssetIds.length) return
    setBusy('recommend')
    try {
      const started = await startCategoryRecommendation(allAssetIds, `category-recommend:${randomUuid()}`)
      for (;;) { const result = await getCategoryRecommendation(started.job_id); if (result.status === 'succeeded') { setRecommendation(result); if (result.category_id) setSelectedCategoryId(result.category_id); break } if (result.status === 'failed') throw new Error(result.error_message || '品类推荐失败'); await wait(1200) }
    } catch (error) { showToast(errorText(error), 'error') } finally { setBusy('') }
  }

  const analyze = async () => {
    if (!allAssetIds.length || !selectedCategoryId) return
    setBusy('analyze')
    try {
      const started = await analyzeCategoryProduct({ product_image_asset_ids: allAssetIds, primary_asset_id: primaryAssetId || allAssetIds[0], selected_category_id: selectedCategoryId, project_id: session?.project_id || undefined, idempotency_key: `category-analyze:${randomUuid()}` })
      if (started.session_id !== sessionId) navigate(`/listing-workbench/${started.session_id}`, { replace: Boolean(sessionId) })
      for (;;) { const value = await getListingWorkflowSession(started.session_id); if (!mounted.current) return; applySession(value); if (value.status === 'generated') break; if (value.status === 'analysis_failed') throw new Error(value.error_message || '商品分析失败'); await wait(1500) }
      showToast('商品分析和Listing文案已生成，请编辑后确认。', 'success')
    } catch (error) { showToast(errorText(error), 'error') } finally { setBusy('') }
  }

  const save = async () => {
    if (!session) return
    setBusy('save')
    try { await queueDraftSave(); showToast('Listing草稿已保存。', 'success') }
    catch (error) { showToast(errorText(error), 'error') } finally { setBusy('') }
  }

  const optimizeListing = async (direction: 'en_to_zh' | 'zh_to_en') => {
    if (!session) return
    setBusy(direction)
    try {
      const started = await optimizeBilingualListing(session.id, {
        direction, listing_content: listingContent(), idempotency_key: `listing-copy:${direction}:${randomUuid()}`,
      })
      for (;;) {
        const result = await getBilingualListingOptimization(session.id, started.job_id)
        if (result.status === 'failed') throw new Error(result.error_message || 'Listing AI优化失败')
        if (result.status === 'succeeded' && result.listing_content) { setContent(result.listing_content); break }
        await wait(1200)
      }
      showToast(direction === 'en_to_zh' ? '中文说明已根据英文重新生成。' : '英文Listing已根据中文要求重新优化。', 'success')
    } catch (error) { showToast(errorText(error), 'error') } finally { setBusy('') }
  }

  const confirm = async () => {
    if (!session) return
    setBusy('confirm')
    await queueDraftSave()
    try { const value = await confirmListingWorkflowSession(session.id, { structured_attributes: attributes, listing_content: listingContent() }); applySession(value); showToast(`Listing V${value.listing_version_number} 已确认。`, 'success'); navigate(`/listing-workbench/${value.id}/select-output`) }
    catch (error) { showToast(errorText(error), 'error') } finally { setBusy('') }
  }

  return <div className="pb-10">
    <WorkflowSteps current={session ? 2 : 1} sessionId={session?.id} />
    {session && <div className="mb-3 flex justify-end"><AutoSaveIndicator state={saveState} savedAt={session.last_saved_at} onRetry={() => void queueDraftSave()} /></div>}
    <section className={panel}>
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-gray-100 bg-gradient-to-r from-blue-50 to-indigo-50 px-5 py-5 dark:border-white/[0.06] dark:from-blue-500/10 dark:to-indigo-500/10">
        <div><h1 className="text-xl font-bold dark:text-white">商品分析与 Listing 文案生成</h1><p className="mt-1 text-sm text-gray-600 dark:text-gray-300">上传产品图，人工确认品类，生成并编辑 Listing；图片制作将在确认后进入独立工作台。</p></div>
        <div className="flex flex-wrap gap-2"><Link to="/workspaces/listing/quick" className={primary}>快速生成</Link><Link to="/workspaces/listing/legacy" className={secondary}>进入原版 Listing 图工作台</Link></div>
      </header>
      <div className="space-y-7 p-5">
        <div className="grid gap-5 xl:grid-cols-2">
          <div {...productPasteZoneProps} className="rounded-xl outline-none focus:ring-2 focus:ring-blue-500/20"><div className="flex justify-between"><h2 className="font-bold dark:text-white">商品图片</h2><span className="text-xs text-gray-500">{allAssetIds.length}/10</span></div>
            {existingAssetIds.length > 0 && <div className="mt-3 rounded-xl bg-emerald-50 p-3 text-sm text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300">已保存 {existingAssetIds.length} 张商品参考图</div>}
            <label className="mt-3 flex cursor-pointer justify-center rounded-xl border border-dashed border-blue-300 bg-blue-50/40 p-5 text-center text-sm font-semibold text-blue-700"><span>{busy === 'upload' ? '正在上传…' : '选择文件，或点击本卡片后 Ctrl/⌘+V 粘贴 1–10 张产品图'}</span><input className="hidden" type="file" accept="image/*" multiple onChange={(event) => { void uploadFiles(event.target.files); event.currentTarget.value = '' }} /></label>
            <div className="mt-3 grid grid-cols-3 gap-3 sm:grid-cols-5">{references.map((item) => <div key={item.localId} className="relative overflow-hidden rounded-xl border border-gray-200"><img src={item.previewUrl} className="aspect-square w-full object-cover" alt={item.file.name} /><button className="absolute right-1 top-1 rounded bg-black/60 px-1.5 py-1 text-[10px] text-white" onClick={() => void removeReference(item)}>删除</button><div className="truncate p-2 text-[10px]">{item.error || item.file.name}</div></div>)}</div>
          </div>
          <div><h2 className="font-bold dark:text-white">人工确认品类</h2><button className={`${secondary} mt-3 w-full`} disabled={!allAssetIds.length || busy === 'recommend'} onClick={() => void recommend()}>AI 推荐品类（可选）</button>
            {recommendation && <div className="mt-2 rounded-xl bg-indigo-50 p-3 text-xs text-indigo-800">推荐：{recommendation.category_name || '无可靠匹配'}{recommendation.reason ? ` · ${recommendation.reason}` : ''}</div>}
            <input className={`${field} mt-3`} placeholder="搜索品类名称或代码" value={categorySearch} onChange={(event) => setCategorySearch(event.target.value)} />
            <select className={`${field} mt-2`} value={selectedCategoryId} onChange={(event) => setSelectedCategoryId(event.target.value)}><option value="">请选择品类</option>{visibleCategories.map((item) => <option value={item.id} key={item.id}>{item.category_name}</option>)}</select>
            <p className="mt-3 text-xs text-amber-700">最终品类必须由用户人工确认，AI 推荐不会自动提交。</p>
            <button className={`${primary} mt-4 w-full`} disabled={!allAssetIds.length || !selectedCategoryId || busy === 'analyze'} onClick={() => void analyze()}>{busy === 'analyze' ? 'AI分析和生成Listing中…' : session ? '重新分析并生成新草稿' : 'AI分析商品并生成Listing'}</button>
          </div>
        </div>

        {session && <><div className="border-t border-gray-100 pt-6 dark:border-white/[0.06]"><div className="flex justify-between"><div><h2 className="font-bold dark:text-white">商品分析</h2><p className="text-xs text-gray-500">{session.category_name} · {session.skill_name}{session.skill_version_number ? ` · Skill V${session.skill_version_number}` : ''}</p></div><span className="rounded-full bg-blue-50 px-3 py-1 text-xs font-semibold text-blue-700">{session.status}{session.listing_version_number ? ` · Listing V${session.listing_version_number}` : ''}</span></div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{attributeFields.map(({ code: key, name: label, type }) => <label key={key} className="text-xs font-semibold text-gray-600">{label}<input className={`${field} mt-1`} value={display(attributes[key])} onChange={(event) => setAttributes((value) => ({ ...value, [key]: parseConfiguredValue(type, event.target.value) }))} /></label>)}</div></div>
          <div className="border-t border-gray-100 pt-6 dark:border-white/[0.06]"><div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-bold dark:text-white">Listing 中英文对照</h2><p className="mt-1 text-xs text-gray-500">英文版用于最终 Listing；中文版用于运营理解、审核和修改。</p></div><div className="flex flex-wrap gap-2"><button className={secondary} disabled={Boolean(busy)} onClick={() => void optimizeListing('en_to_zh')}>{busy === 'en_to_zh' ? '正在更新中文…' : '根据英文更新中文'}</button><button className={primary} disabled={Boolean(busy)} onClick={() => void optimizeListing('zh_to_en')}>{busy === 'zh_to_en' ? '正在优化英文…' : '根据中文优化英文'}</button></div></div>
            <div className="mt-4 space-y-4">
              <BilingualTextCard label="Listing 标题" en={content.title.en} zh={content.title.zh} onEn={(value) => setLocalized('title', 'en', value)} onZh={(value) => setLocalized('title', 'zh', value)} />
              <div className="rounded-xl border border-gray-200 p-4 dark:border-white/[0.08]"><h3 className="font-semibold dark:text-white">五点描述</h3><div className="mt-3 space-y-4">{content.bullet_points.map((bullet, index) => <BilingualTextCard key={bullet.id} label={`卖点 ${index + 1}`} en={bullet.en} zh={bullet.zh} onEn={(value) => setBullet(index, 'en', value)} onZh={(value) => setBullet(index, 'zh', value)} compact />)}</div></div>
              <BilingualTextCard label="产品描述" en={content.description.en} zh={content.description.zh} onEn={(value) => setLocalized('description', 'en', value)} onZh={(value) => setLocalized('description', 'zh', value)} />
              <div className="grid gap-3 rounded-xl border border-gray-200 p-4 lg:grid-cols-2 dark:border-white/[0.08]"><label className="text-xs font-semibold text-gray-600">搜索关键词 · 英文（用于最终Listing）<textarea className={`${field} mt-1 min-h-24`} value={content.search_terms.en.join(', ')} onChange={(event) => setTerms('en', event.target.value)} /></label><label className="text-xs font-semibold text-gray-600">搜索关键词 · 中文（用于理解审核）<textarea className={`${field} mt-1 min-h-24`} value={content.search_terms.zh.join('、')} onChange={(event) => setTerms('zh', event.target.value)} /></label></div>
              {([['selling_points', '核心卖点'], ['usage_scenarios', '适用场景'], ['customization_notes', '定制说明'], ['cautions', '注意事项']] as const).map(([key, label]) => <BilingualTextCard key={key} label={label} en={content[key].en} zh={content[key].zh} onEn={(value) => setLocalized(key, 'en', value)} onZh={(value) => setLocalized(key, 'zh', value)} compact />)}
            </div>
          </div>
          <div className="flex flex-wrap justify-end gap-3 border-t border-gray-100 pt-5 dark:border-white/[0.06]"><button className={secondary} disabled={Boolean(busy)} onClick={() => void save()}>保存草稿</button><button className={secondary} disabled={Boolean(busy)} onClick={() => void analyze()}>重新分析</button><button className={primary} disabled={Boolean(busy) || !content.title.en.trim() || !content.bullet_points.some((item) => item.en.trim())} onClick={() => void confirm()}>{busy === 'confirm' ? '确认中…' : '确认Listing并进入下一步'}</button></div>
        </>}
      </div>
    </section>
  </div>
}
